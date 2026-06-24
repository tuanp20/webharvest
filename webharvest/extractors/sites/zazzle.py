"""Zazzle Extractor.

Extracts products from Zazzle.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData
from webharvest.extractors.json_parsers.nextdata import NextDataParser
from .base_site import BaseSiteExtractor


class ZazzleExtractor(BaseSiteExtractor):
    """Zazzle Extractor (Tầng 2 - Dynamic)."""

    SITE_DOMAIN = "zazzle.com"
    FETCHER_TYPE = "dynamic"
    RATE_LIMIT = {"rate": 0.2, "burst": 2}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # 1. Try __NEXT_DATA__
        next_data = NextDataParser.extract(html)
        if next_data:
            product_props = NextDataParser.find_key_recursive(next_data, "product")
            if product_props and isinstance(product_props[0], dict):
                p = product_props[0]
                title = p.get("title") or p.get("name") or ""
                price = p.get("price") or p.get("formattedPrice")
                if price and isinstance(price, str):
                    try:
                        price = float(re.sub(r"[^\d.]", "", price))
                    except ValueError:
                        price = None
                
                return ProductData(
                    title=title,
                    url=url,
                    source_site=self.SITE_DOMAIN,
                    main_image_url=p.get("mainImageUrl") or p.get("imageUrl") or p.get("thumbnailUrl"),
                    price=price,
                    description=p.get("description"),
                    category=p.get("categoryName") or p.get("category"),
                )

        # 2. Fallback to selectors
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

        image_url = self._extract_main_image(soup, url)
        description = self._extract_description(soup)
        variants, colors, sizes = self._extract_variations(soup)
        category = self._extract_category(soup) or "Custom Gifts"

        return ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=image_url,
            price=price_val,
            description=description,
            category=category,
            variants=variants,
            colors=colors,
            sizes=sizes,
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/pd/" in href or "/product/" in href:
                full_url = urljoin(url, href)
                if full_url not in links:
                    links.append(full_url)
        return links
