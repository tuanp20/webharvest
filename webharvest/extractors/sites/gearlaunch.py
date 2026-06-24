"""GearLaunch Extractor.

Extracts products from GearLaunch.
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


class GearLaunchExtractor(BaseSiteExtractor):
    """GearLaunch Extractor (Tầng 1 - Static)."""

    SITE_DOMAIN = "gearlaunch.com"
    FETCHER_TYPE = "static"
    RATE_LIMIT = {"rate": 0.5, "burst": 3}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        json_ld_list = ContentExtractor._extract_json_ld(BeautifulSoup(html, "lxml"))
        product = JsonLdProductParser.parse(json_ld_list, url, self.SITE_DOMAIN)
        if product:
            return product

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
        category = self._extract_category(soup) or "Custom Apparel"

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
            if "/product/" in href or "/campaign/" in href or "/store/" in href:
                full_url = urljoin(url, href)
                if full_url not in links:
                    links.append(full_url)
        return links
