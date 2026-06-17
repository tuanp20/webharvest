"""Printful Extractor.

Extracts products from Printful.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData, ProductVariant
from webharvest.extractors.json_parsers.nextdata import NextDataParser
from .base_site import BaseSiteExtractor


class PrintfulExtractor(BaseSiteExtractor):
    """Printful Extractor (Tầng 2 - Dynamic)."""

    SITE_DOMAIN = "printful.com"
    FETCHER_TYPE = "dynamic"
    RATE_LIMIT = {"rate": 0.2, "burst": 2}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # 1. Try __NEXT_DATA__ first
        next_data = NextDataParser.extract(html)
        if next_data:
            # Let's search for catalog product properties inside props
            # Printful typically has catalog product structure in props.pageProps
            product_props = NextDataParser.find_key_recursive(next_data, "product")
            if product_props and isinstance(product_props[0], dict):
                p = product_props[0]
                title = p.get("title") or p.get("name") or ""
                variants = []
                colors = set()
                sizes = set()

                raw_variants = p.get("variants") or p.get("files") or []
                if isinstance(raw_variants, list):
                    for v in raw_variants:
                        if not isinstance(v, dict):
                            continue
                        color = v.get("color")
                        size = v.get("size")
                        price = v.get("price")
                        sku = v.get("sku")
                        
                        if color:
                            colors.add(color)
                        if size:
                            sizes.add(size)
                        
                        variants.append(ProductVariant(
                            color=color,
                            size=size,
                            price=float(price) if price else None,
                            sku=sku,
                            in_stock=v.get("in_stock", True),
                            image_url=v.get("image") or v.get("preview_url")
                        ))

                main_img = p.get("image") or p.get("thumbnail_url")
                
                return ProductData(
                    title=title,
                    url=url,
                    source_site=self.SITE_DOMAIN,
                    main_image_url=main_img,
                    price=float(p.get("price", 0)) if p.get("price") else None,
                    description=p.get("description"),
                    category=p.get("category_name") or p.get("category"),
                    variants=variants,
                    colors=sorted(list(colors)),
                    sizes=sorted(list(sizes)),
                    raw_json=p
                )

        # 2. Fallback to standard selector-based extraction
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        price_val = None
        price_tag = soup.find(class_=re.compile(r"price|amount", re.I))
        if price_tag:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except ValueError:
                pass

        image_url = None
        img_tag = soup.find("meta", property="og:image") or soup.find("img")
        if img_tag:
            image_url = img_tag.get("content") or img_tag.get("src")

        return ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=image_url,
            price=price_val,
            description=None,
            category="Custom Apparel"
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        # Parse listing links
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/custom/" in href or "/product/" in href:
                # avoid listing pagination / categories
                if not any(x in href for x in ["/custom-products", "/custom/"]):
                    full_url = urljoin(url, href)
                    if full_url not in links:
                        links.append(full_url)
        return links
