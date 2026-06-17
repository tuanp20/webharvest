"""eBay Extractor.

Extracts listings from eBay.
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


class EbayExtractor(BaseSiteExtractor):
    """eBay Extractor (Tầng 2 - Dynamic)."""

    SITE_DOMAIN = "ebay.com"
    FETCHER_TYPE = "dynamic"
    RATE_LIMIT = {"rate": 0.15, "burst": 2}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        json_ld_list = ContentExtractor._extract_json_ld(BeautifulSoup(html, "lxml"))
        product = JsonLdProductParser.parse(json_ld_list, url, self.SITE_DOMAIN)
        if product:
            return product

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1", class_="x-item-title__mainTitle") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        price_val = None
        price_tag = soup.find("div", class_="x-price-primary") or soup.find(itemprop="price")
        if price_tag:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except ValueError:
                pass

        image_url = None
        img_tag = soup.find("img", id="icImg") or soup.find("meta", property="og:image")
        if img_tag:
            image_url = img_tag.get("content") or img_tag.get("src")

        return ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=image_url,
            price=price_val,
            description=None,
            category="eBay Listing"
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/itm/" in href:
                # remove tracking params
                clean_url = href.split("?")[0]
                full_url = urljoin(url, clean_url)
                if full_url not in links:
                    links.append(full_url)
        return links
