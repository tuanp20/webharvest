"""Shopify Extractor.

Extracts products from Shopify stores.
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from urllib.parse import urlparse
import httpx
from webharvest.models import ProductData
from webharvest.extractors.json_parsers.shopify_json import ShopifyJsonParser
from .base_site import BaseSiteExtractor

logger = logging.getLogger("webharvest.extractors.sites.shopify")


class ShopifyExtractor(BaseSiteExtractor):
    """Shopify Extractor (Tầng 2 - Static/JSON)."""

    SITE_DOMAIN = "shopify"
    FETCHER_TYPE = "static"
    RATE_LIMIT = {"rate": 0.5, "burst": 5}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # Shopify pages often have .json equivalent: url + ".json"
        # Let's try to load the product JSON directly for perfect structured data!
        try:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            json_url = url.split("?")[0].rstrip("/") + ".json"
            
            # Use a fast sync HTTP request to get the json since we are inside sync extract_product
            # (WebHarvest extractors are called synchronously after fetching HTML)
            resp = httpx.get(json_url, timeout=5.0)
            if resp.status_code == 200:
                p_data = resp.json()
                if "product" in p_data:
                    # Map to the format parse_products expects
                    wrapped = {"products": [p_data["product"]]}
                    parsed_products = ShopifyJsonParser.parse_products(wrapped, base_url)
                    if parsed_products:
                        return parsed_products[0]
        except Exception as e:
            logger.debug("Failed to fetch shopify product JSON directly: %s", e)

        # Fallback to JSON-LD if direct JSON fetch failed
        from webharvest.extractors.content import ContentExtractor
        from bs4 import BeautifulSoup
        from webharvest.extractors.json_parsers.json_ld import JsonLdProductParser
        
        soup = BeautifulSoup(html, "lxml")
        json_ld_list = ContentExtractor._extract_json_ld(soup)
        product = JsonLdProductParser.parse(json_ld_list, url, "shopify")
        if product:
            return product

        # Final fallback: use base helpers
        import re
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
        category = self._extract_category(soup) or "Shopify Product"

        return ProductData(
            title=title,
            url=url,
            source_site="shopify",
            main_image_url=image_url,
            price=price_val,
            description=description,
            category=category,
            variants=variants,
            colors=colors,
            sizes=sizes,
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        # If the listing page is catalog, we can directly query /products.json
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        json_url = f"{base_url}/products.json?limit=250"
        
        links = []
        try:
            resp = httpx.get(json_url, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                for p in data.get("products", []):
                    handle = p.get("handle")
                    if handle:
                        links.append(f"{base_url}/products/{handle}")
                return links
        except Exception as e:
            logger.debug("Failed to fetch Shopify listing products.json: %s", e)

        # Fallback to standard link parsing if /products.json is blocked or not Shopify
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/products/" in href:
                full_url = f"{base_url}{href}" if href.startswith("/") else href
                if full_url not in links:
                    links.append(full_url)
        return links
