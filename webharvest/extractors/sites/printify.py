"""Printify Extractor.

Extracts products from Printify.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData
from .base_site import BaseSiteExtractor


class PrintifyExtractor(BaseSiteExtractor):
    """Printify Extractor (Tầng 2 - Dynamic)."""

    SITE_DOMAIN = "printify.com"
    FETCHER_TYPE = "dynamic"
    RATE_LIMIT = {"rate": 0.2, "burst": 2}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Price
        price_val = None
        price_tag = soup.find(class_=re.compile(r"price|cost", re.I)) or soup.find("span", text=re.compile(r"\$\d+"))
        if price_tag:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except ValueError:
                pass

        # Use smart image extraction
        image_url = self._extract_main_image(soup, url)
        description = self._extract_description(soup)
        variants, colors, sizes = self._extract_variations(soup)
        category = self._extract_category(soup) or "Print on Demand"

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
            if "/app/products" in href or "/product/" in href:
                full_url = urljoin(url, href)
                if full_url not in links:
                    links.append(full_url)
        return links
