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
            resp = None
            loop = asyncio.get_running_loop()

            try:
                # 1. Fetch start URL
                self._emit("fetch_page_start", {"url": start_url, "fetcher": fetcher_type})

                if fetcher_type == "stealth":
                    # For stealth sites, try curl_cffi TLS impersonation FIRST
                    # (lightweight, no browser dependency, works with proxies)
                    logger.info("Stealth site detected — trying curl_cffi TLS bypass first")
                    curl_resp = await self._try_curl_cffi_stealth(start_url)
                    if curl_resp and curl_resp.ok:
                        resp = curl_resp
                        # Create a StaticFetcher for subsequent pages (will also fallback)
                        fetcher = StaticFetcher(proxies=self.proxies)
                    else:
                        # Fallback to Playwright StealthFetcher
                        logger.info("curl_cffi failed, trying Playwright StealthFetcher")
                        try:
                            fetcher = StealthFetcher(proxies=self.proxies)
                            resp = await loop.run_in_executor(None, lambda: fetcher.get(start_url))
                        except Exception as pw_err:
                            logger.warning("Playwright StealthFetcher unavailable: %s", pw_err)
                            # Last resort: static fetcher with proxies
                            fetcher = StaticFetcher(proxies=self.proxies)
                            resp = await loop.run_in_executor(None, lambda: fetcher.get(start_url))

                elif fetcher_type == "dynamic":
                    try:
                        fetcher = DynamicFetcher(proxies=self.proxies)
                        resp = await loop.run_in_executor(None, lambda: fetcher.get(start_url))
                    except Exception as dyn_err:
                        logger.warning("DynamicFetcher unavailable: %s", dyn_err)
                        fetcher = StaticFetcher(proxies=self.proxies)
                        resp = await loop.run_in_executor(None, lambda: fetcher.get(start_url))
                else:
                    fetcher = StaticFetcher(proxies=self.proxies)
                    resp = await loop.run_in_executor(None, lambda: fetcher.get(start_url))

                # ── Fallback on 403/block for non-stealth fetchers ──
                if resp and (not resp.ok or not resp.html) and resp.status_code in (403, 503):
                    logger.warning(
                        "Fetch failed (status=%d) with %s, trying curl_cffi TLS fallback for %s",
                        resp.status_code, fetcher_type, start_url,
                    )
                    self._emit("fetcher_fallback", {
                        "url": start_url,
                        "from": fetcher_type,
                        "to": "curl_cffi",
                        "reason": f"HTTP {resp.status_code}",
                    })
                    curl_resp = await self._try_curl_cffi_stealth(start_url)
                    if curl_resp and curl_resp.ok:
                        resp = curl_resp

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
                    "local_image_path": getattr(p, "local_image_path", None),
                    "price": p.price,
                    "currency": p.currency,
                    "description": p.description,
                    "category": p.category,
                    "colors": p.colors,
                    "sizes": p.sizes,
                    "local_additional_images": getattr(p, "local_additional_images", []),
                    "variants": [
                        {
                            "color": v.color,
                            "size": v.size,
                            "price": v.price,
                            "sku": v.sku,
                            "in_stock": v.in_stock,
                            "image_url": v.image_url,
                            "local_image_path": getattr(v, "local_image_path", None),
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

    async def _try_curl_cffi_stealth(self, url: str) -> "Optional[FetchResponse]":
        """Last-resort fetch using curl_cffi with TLS impersonation + proxy rotation.

        Returns a FetchResponse on success, None on failure.
        """
        from webharvest.fetchers.base import FetchResponse
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            logger.warning("curl_cffi not installed — cannot use TLS impersonation fallback")
            return None

        targets = ["safari17_0", "chrome124", "chrome120", "safari15_5"]
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }

        loop = asyncio.get_running_loop()

        for target in targets:
            # Try with each proxy first, then direct
            proxy_configs = [{"https": p, "http": p} for p in self.proxies] + [None]

            for proxy_map in proxy_configs:
                def _sync_fetch(t=target, pm=proxy_map):
                    try:
                        resp = curl_requests.get(
                            url,
                            headers=headers,
                            impersonate=t,
                            timeout=20,
                            allow_redirects=True,
                            proxies=pm,
                        )
                        return resp.text, resp.status_code
                    except Exception as exc:
                        logger.debug("curl_cffi [%s] failed for %s: %s", t, url, exc)
                        return "", 0

                html, status = await loop.run_in_executor(None, _sync_fetch)

                if status == 200 and html and len(html) > 2000:
                    logger.info(
                        "curl_cffi [%s] succeeded for %s (status=%d, len=%d, proxy=%s)",
                        target, url, status, len(html), bool(proxy_map),
                    )
                    return FetchResponse(
                        html=html,
                        status_code=status,
                        headers={},
                        url=url,
                        content=html.encode("utf-8", errors="replace"),
                        encoding="utf-8",
                        elapsed=0.0,
                    )

        logger.warning("All curl_cffi TLS bypass attempts failed for %s", url)
        return None

    async def _download_bytes(self, url: str) -> Optional[bytes]:
        """Download raw bytes from URL with proxy fallback and curl_cffi bypass if needed."""
        import httpx
        loop = asyncio.get_running_loop()
        
        # Build client options
        proxy_configs = self.proxies + [None]
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        for proxy in proxy_configs:
            try:
                def _fetch():
                    proxies_dict = {"http://": proxy, "https://": proxy} if proxy else None
                    with httpx.Client(proxies=proxies_dict, timeout=15.0, verify=False) as client:
                        resp = client.get(url, headers=headers, follow_redirects=True)
                        if resp.status_code == 200:
                            return resp.content
                        return None
                        
                content = await loop.run_in_executor(None, _fetch)
                if content:
                    return content
            except Exception as e:
                logger.debug("httpx image download failed with proxy %s: %s", proxy, e)
                
        # Fallback to curl_cffi
        try:
            from curl_cffi import requests as curl_requests
            targets = ["safari17_0", "chrome124"]
            for target in targets:
                for proxy in proxy_configs:
                    def _sync_fetch():
                        proxies_dict = {"http": proxy, "https": proxy} if proxy else None
                        resp = curl_requests.get(
                            url,
                            headers=headers,
                            impersonate=target,
                            timeout=15,
                            allow_redirects=True,
                            proxies=proxies_dict,
                            verify=False
                        )
                        if resp.status_code == 200:
                            return resp.content
                        return None
                    try:
                        content = await loop.run_in_executor(None, _sync_fetch)
                        if content:
                            return content
                    except Exception:
                        pass
        except Exception:
            pass
            
        return None

    async def _download_product_image(self, url: str, site_domain: str) -> Optional[str]:
        """Download product image and save it locally.
        
        Returns the absolute local path to the downloaded file, or None if download fails.
        """
        if not url:
            return None
            
        import hashlib
        try:
            # Generate subfolder
            domain_folder = site_domain.replace(".", "_")
            outdir = self.output_dir / "images" / domain_folder
            outdir.mkdir(parents=True, exist_ok=True)
            
            # Extract extension
            ext = ".jpg"
            parsed = urlparse(url)
            path_ext = Path(parsed.path).suffix.lower()
            if path_ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".avif", ".ico"):
                ext = path_ext
                if ext == ".jpeg":
                    ext = ".jpg"
            
            # Generate unique filename using URL hash
            url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
            filename = f"{url_hash[:12]}{ext}"
            filepath = outdir / filename
            
            # If already exists, return absolute path directly
            if filepath.exists():
                return str(filepath.resolve())
                
            # Download image bytes
            data = await self._download_bytes(url)
            if data:
                filepath.write_bytes(data)
                logger.info("Saved product image to %s", filepath)
                return str(filepath.resolve())
        except Exception as e:
            logger.warning("Failed to download image %s: %s", url, e)
            
        return None

    async def _crawl_product_page(self, url: str, extractor: BaseSiteExtractor, fetcher: Any):
        """Crawls and extracts a single product page."""
        try:
            logger.info("Crawling product page: %s", url)
            self._emit("fetch_product_start", {"url": url})
            
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: fetcher.get(url))

            # Fallback on 403/block for individual product pages too
            if (not resp.ok or not resp.html) and resp.status_code in (403, 503):
                logger.warning(
                    "Product page fetch failed (status=%d), trying curl_cffi fallback for %s",
                    resp.status_code, url,
                )
                curl_resp = await self._try_curl_cffi_stealth(url)
                if curl_resp:
                    resp = curl_resp

            if not resp.ok or not resp.html:
                self._emit("fetch_product_failed", {"url": url, "status": resp.status_code})
                return

            # Extract product
            product_data = extractor.extract_product(resp.html, url)
            if product_data:
                # 1. Download main image
                if product_data.main_image_url:
                    local_img = await self._download_product_image(product_data.main_image_url, product_data.source_site)
                    if local_img:
                        product_data.local_image_path = local_img
                        
                # 2. Download variant images
                if product_data.variants:
                    for variant in product_data.variants:
                        if variant.image_url:
                            local_var_img = await self._download_product_image(variant.image_url, product_data.source_site)
                            if local_var_img:
                                variant.local_image_path = local_var_img

                # 3. Download additional images
                if product_data.additional_images:
                    product_data.local_additional_images = []
                    for add_img in product_data.additional_images:
                        local_add_img = await self._download_product_image(add_img, product_data.source_site)
                        if local_add_img:
                            product_data.local_additional_images.append(local_add_img)

                self._results.append(product_data)
                
                # Emit product success with local image URL
                fe_image = product_data.main_image_url
                if product_data.local_image_path:
                    from urllib.parse import quote
                    fe_image = f"/api/image?path={quote(product_data.local_image_path)}"
                    
                self._emit("product_extracted", {
                    "url": url,
                    "title": product_data.title,
                    "price": product_data.price,
                    "image": fe_image,
                    "variants_count": len(product_data.variants)
                })
            else:
                self._emit("product_extraction_failed", {"url": url, "reason": "Extractor returned None"})

        except Exception as e:
            logger.error("Error crawling product page %s: %s", url, e)
            self._emit("product_error", {"url": url, "error": str(e)})
