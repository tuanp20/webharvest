"""AliExpress Extractor.

Extracts products from AliExpress.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData
from webharvest.extractors.json_parsers.json_ld import JsonLdProductParser
from webharvest.extractors.content import ContentExtractor
from .base_site import BaseSiteExtractor


class AliExpressExtractor(BaseSiteExtractor):
    """AliExpress Extractor (Tầng 3 - Stealth)."""

    SITE_DOMAIN = "aliexpress.com"
    FETCHER_TYPE = "stealth"
    RATE_LIMIT = {"rate": 0.08, "burst": 1}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # Try JSON-LD first
        json_ld_list = ContentExtractor._extract_json_ld(BeautifulSoup(html, "lxml"))
        product = JsonLdProductParser.parse(json_ld_list, url, self.SITE_DOMAIN)
        if product:
            return product

        # Fallback to selectors
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Remove "Buy ... online on AliExpress" etc.
        title = title.split(" - ")[0]

        price_val = None
        # Try different price classes
        price_tag = soup.find(class_=re.compile(r"price-current|product-price|uniform-banner-box-price", re.I))
        if price_tag:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except ValueError:
                pass

        image_url = None
        img_tag = soup.find("img", class_=re.compile(r"magnifier-image|product-image", re.I)) or soup.find("meta", property="og:image")
        if img_tag:
            image_url = img_tag.get("content") or img_tag.get("src")

        return ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=image_url,
            price=price_val,
            description=None,
            category="E-commerce item"
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/item/" in href:
                # remove URL params
                clean_url = href.split("?")[0]
                # resolve relative protocol-less url (e.g. //www.aliexpress.com/item/...)
                if clean_url.startswith("//"):
                    full_url = f"https:{clean_url}"
                else:
                    full_url = urljoin(url, clean_url)
                if full_url not in links:
                    links.append(full_url)
        return links
