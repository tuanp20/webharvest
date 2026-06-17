"""TeePublic Extractor.

Extracts products from TeePublic.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData, ProductVariant
from webharvest.extractors.json_parsers.json_ld import JsonLdProductParser
from webharvest.extractors.content import ContentExtractor
from .base_site import BaseSiteExtractor


class TeePublicExtractor(BaseSiteExtractor):
    """TeePublic Extractor (Tầng 1 - Static)."""

    SITE_DOMAIN = "teepublic.com"
    FETCHER_TYPE = "static"
    RATE_LIMIT = {"rate": 0.5, "burst": 3}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # 1. Try JSON-LD first
        json_ld_list = ContentExtractor._extract_json_ld(BeautifulSoup(html, "lxml"))
        product = JsonLdProductParser.parse(json_ld_list, url, self.SITE_DOMAIN)
        if product:
            return product

        # 2. Fallback to CSS Selectors
        soup = BeautifulSoup(html, "lxml")
        
        # Title
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Price
        price_val = None
        price_tag = soup.find("span", class_=re.compile(r"price", re.I)) or soup.find(itemprop="price")
        if price_tag:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except ValueError:
                pass

        # Image
        img_tag = soup.find("img", class_=re.compile(r"product-image|preview", re.I)) or soup.find("meta", property="og:image")
        image_url = None
        if img_tag:
            image_url = img_tag.get("content") or img_tag.get("src")

        # Description
        desc_tag = soup.find(class_=re.compile(r"description", re.I))
        description = desc_tag.get_text(strip=True) if desc_tag else None

        # Category
        category = "T-Shirt"
        breadcrumbs = soup.find(class_=re.compile(r"breadcrumb", re.I))
        if breadcrumbs:
            category = breadcrumbs.get_text(" > ", strip=True)

        return ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=image_url,
            price=price_val,
            description=description,
            category=category
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        # Find product links (typically cards or design tiles)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/t-shirt/" in href or "/show/" in href:
                full_url = urljoin(url, href)
                if full_url not in links:
                    links.append(full_url)
        return links
