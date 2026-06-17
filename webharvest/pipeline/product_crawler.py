"""ProductCrawlPipeline class.

Orchestrates product scraping:
1. Detects the appropriate site extractor.
2. Identifies if the URL is a listing or a product page.
3. Crawls listing page to discover product detail URLs.
4. Crawls product detail pages using correct fetcher (static, dynamic, stealth).
5. Parses structured product information (variants, price, title, image, categories).
6. Respects rate limits, rotation of proxies, and fallback logic.
"""

from __future__ import annotations

import asyncio
import logging
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
from webharvest.models import ProductData, ProductVariant
from webharvest.extractors.sites import detect_extractor, BaseSiteExtractor
from webharvest.fetchers import StaticFetcher, DynamicFetcher, StealthFetcher
from webharvest.extractors.json_parsers.json_ld import JsonLdProductParser
from webharvest.extractors.content import ContentExtractor

logger = logging.getLogger("webharvest.pipeline.product_crawler")


class GenericSiteExtractor(BaseSiteExtractor):
    """Generic fallback extractor using JSON-LD, NEXT_DATA and standard meta tags."""

    SITE_DOMAIN = "generic"
    FETCHER_TYPE = "static"

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # 1. Try JSON-LD
        soup = BeautifulSoup(html, "lxml")
        json_ld_list = ContentExtractor._extract_json_ld(soup)
        product = JsonLdProductParser.parse(json_ld_list, url, "generic")
        if product:
            return product

        # 2. Try standard meta/HTML selectors
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        
        # Strip standard suffix
        if " - " in title:
            title = title.split(" - ")[0]

        price_val = None
        price_tag = soup.find(itemprop="price") or soup.find(class_=lambda x: x and "price" in x.lower())
        if price_tag:
            try:
                import re
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except Exception:
                pass

        image_url = None
        img_tag = soup.find("meta", property="og:image") or soup.find("img")
        if img_tag:
            image_url = img_tag.get("content") or img_tag.get("src")
            if image_url:
                image_url = urljoin(url, image_url)

        description_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(itemprop="description")
        description = description_tag.get("content") if description_tag else None

        return ProductData(
            title=title,
            url=url,
            source_site="generic",
            main_image_url=image_url,
            price=price_val,
            description=description,
            category="Product"
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        # Find any links that look like products
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product/" in href or "/products/" in href or "/p/" in href or "-p-" in href:
                full_url = urljoin(url, href)
                if full_url not in links:
                    links.append(full_url)
        return links


class ProductCrawlPipeline:
    """Orchestrates crawler execution for product catalogs."""

    def __init__(
        self,
        urls: List[str],
        output_dir: str = "./output",
        max_products: int = 50,
        proxies: Optional[List[str]] = None,
        on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.urls = urls
        self.output_dir = Path(output_dir)
        self.max_products = max_products
        self.proxies = proxies or []
        self.on_progress = on_progress or (lambda event, data: None)

        self._results: List[ProductData] = []
        self._visited_product_urls: set[str] = set()

    def _emit(self, event: str, data: Dict[str, Any]):
        """Emit progress event to listener."""
        try:
            self.on_progress(event, data)
        except Exception as e:
            logger.error("Error emitting event %s: %s", event, e)

    async def run(self) -> List[ProductData]:
        """Runs the product crawl pipeline."""
        self._emit("product_crawl_start", {"urls": self.urls, "max_products": self.max_products})
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for start_url in self.urls:
            if len(self._results) >= self.max_products:
                break

            logger.info("Processing start URL: %s", start_url)
            extractor = detect_extractor(start_url)
            if not extractor:
                logger.info("No site-specific extractor found for %s, using fallback", start_url)
                extractor = GenericSiteExtractor()

            # Initialize correct fetcher
            fetcher_type = extractor.FETCHER_TYPE
            logger.info("Using fetcher type: %s for %s", fetcher_type, start_url)

            fetcher = None
            if fetcher_type == "stealth":
                fetcher = StealthFetcher(proxies=self.proxies)
            elif fetcher_type == "dynamic":
                fetcher = DynamicFetcher(proxies=self.proxies)
            else:
                fetcher = StaticFetcher(proxies=self.proxies)

            try:
                # 1. Fetch start URL
                self._emit("fetch_page_start", {"url": start_url, "fetcher": fetcher_type})
                loop = asyncio.get_running_loop()
                
                # Fetch page inside thread pool
                resp = await loop.run_in_executor(None, lambda: fetcher.get(start_url))
                
                if not resp.ok or not resp.html:
                    self._emit("fetch_page_failed", {"url": start_url, "status": resp.status_code})
                    continue

                self._emit("fetch_page_success", {"url": start_url, "status": resp.status_code})

                # 2. Check if listing page or product page
                product_urls = extractor.extract_listing(resp.html, start_url)
                
                if product_urls:
                    # It's a listing page!
                    logger.info("Detected listing page with %d product URLs", len(product_urls))
                    self._emit("listing_detected", {"url": start_url, "count": len(product_urls)})

                    for prod_url in product_urls:
                        if len(self._results) >= self.max_products:
                            break
                        if prod_url in self._visited_product_urls:
                            continue
                        self._visited_product_urls.add(prod_url)

                        # Respect rate limit
                        rate = extractor.RATE_LIMIT.get("rate", 0.5)
                        delay = 1.0 / rate if rate > 0 else 1.0
                        logger.debug("Applying politeness delay: %.2fs", delay)
                        await asyncio.sleep(delay)

                        # Crawl individual product page
                        await self._crawl_product_page(prod_url, extractor, fetcher)

                else:
                    # It's a single product page
                    logger.info("Detected single product page: %s", start_url)
                    await self._crawl_product_page(start_url, extractor, fetcher)

            except Exception as e:
                logger.error("Error crawling starting URL %s: %s", start_url, e)
                self._emit("error", {"url": start_url, "error": str(e)})
            finally:
                if fetcher:
                    try:
                        fetcher.close()
                    except Exception:
                        pass

        # Save all results to a JSON file
        try:
            output_file = self.output_dir / "products.json"
            products_json = []
            for p in self._results:
                # Convert dataclass to dict
                p_dict = {
                    "title": p.title,
                    "url": p.url,
                    "source_site": p.source_site,
                    "main_image_url": p.main_image_url,
                    "price": p.price,
                    "currency": p.currency,
                    "description": p.description,
                    "category": p.category,
                    "colors": p.colors,
                    "sizes": p.sizes,
                    "variants": [
                        {
                            "color": v.color,
                            "size": v.size,
                            "price": v.price,
                            "sku": v.sku,
                            "in_stock": v.in_stock,
                            "image_url": v.image_url,
                        }
                        for v in p.variants
                    ],
                }
                products_json.append(p_dict)

            output_file.write_text(json.dumps(products_json, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Saved %d products to %s", len(self._results), output_file)
        except Exception as e:
            logger.error("Failed to save products JSON file: %s", e)

        self._emit("product_crawl_done", {"count": len(self._results)})
        return self._results

    async def _crawl_product_page(self, url: str, extractor: BaseSiteExtractor, fetcher: Any):
        """Crawls and extracts a single product page."""
        try:
            logger.info("Crawling product page: %s", url)
            self._emit("fetch_product_start", {"url": url})
            
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: fetcher.get(url))

            if not resp.ok or not resp.html:
                self._emit("fetch_product_failed", {"url": url, "status": resp.status_code})
                return

            # Extract product
            product_data = extractor.extract_product(resp.html, url)
            if product_data:
                # Clean variants to filter out paid/upsell variants or specific types if needed
                # (Requirements: "Hiện tại loại bỏ những size phải trả phí, sẽ lên phương án xử lý sau")
                # Since we don't have paid sizes defined yet, we keep all standard variants
                self._results.append(product_data)
                self._emit("product_extracted", {
                    "url": url,
                    "title": product_data.title,
                    "price": product_data.price,
                    "image": product_data.main_image_url,
                    "variants_count": len(product_data.variants)
                })
            else:
                self._emit("product_extraction_failed", {"url": url, "reason": "Extractor returned None"})

        except Exception as e:
            logger.error("Error crawling product page %s: %s", url, e)
            self._emit("product_error", {"url": url, "error": str(e)})
