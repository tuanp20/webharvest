"""Gelato Extractor.

Extracts products from Gelato.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData
from .base_site import BaseSiteExtractor


class GelatoExtractor(BaseSiteExtractor):
    """Gelato Extractor (Tầng 2 - Dynamic)."""

    SITE_DOMAIN = "gelato.com"
    FETCHER_TYPE = "dynamic"
    RATE_LIMIT = {"rate": 0.2, "burst": 2}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
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
            category="Custom Products"
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/products/" in href or "/product/" in href:
                full_url = urljoin(url, href)
                if full_url not in links:
                    links.append(full_url)
        return links
