"""WooCommerce Extractor.

Extracts products from WooCommerce stores.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from webharvest.models import ProductData
from webharvest.extractors.json_parsers.json_ld import JsonLdProductParser
from webharvest.extractors.content import ContentExtractor
from .base_site import BaseSiteExtractor


class WooCommerceExtractor(BaseSiteExtractor):
    """WooCommerce Extractor (Tầng 2 - Static/JSON)."""

    SITE_DOMAIN = "woocommerce"
    FETCHER_TYPE = "static"
    RATE_LIMIT = {"rate": 0.5, "burst": 3}

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # WooCommerce stores highly standard schema.org JSON-LD
        json_ld_list = ContentExtractor._extract_json_ld(BeautifulSoup(html, "lxml"))
        product = JsonLdProductParser.parse(json_ld_list, url, "woocommerce")
        if product:
            return product

        # Fallback to WooCommerce standard product selectors
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1", class_="product_title") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Price
        price_val = None
        price_tag = soup.find("p", class_="price") or soup.find(class_="woocommerce-Price-amount")
        if price_tag:
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_tag.get_text()))
            except ValueError:
                pass

        # Image
        image_url = None
        img_tag = soup.find("div", class_="woocommerce-product-gallery__image") or soup.find("img", class_="wp-post-image")
        if img_tag:
            if isinstance(img_tag, BeautifulSoup):
                nested_img = img_tag.find("img")
                if nested_img:
                    image_url = nested_img.get("src")
            else:
                image_url = img_tag.get("src")

        # Description
        desc_tag = soup.find("div", class_="woocommerce-product-details__short-description") or soup.find("div", id="tab-description")
        description = desc_tag.get_text(strip=True) if desc_tag else None

        return ProductData(
            title=title,
            url=url,
            source_site="woocommerce",
            main_image_url=image_url,
            price=price_val,
            description=description,
            category="Shop Product"
        )

    def extract_listing(self, html: str, url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # WooCommerce standard list selectors (.product a, .woocommerce-loop-product__link)
        for a in soup.find_all("a", class_=re.compile(r"woocommerce-LoopProduct-link|product__link", re.I)):
            href = a["href"]
            full_url = urljoin(url, href)
            if full_url not in links:
                links.append(full_url)
                
        # Also scan generic shop/product links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/product/" in href or "/shop/" in href:
                full_url = urljoin(url, href)
                if "/product-category/" not in full_url and "/shop/" not in href:
                    if full_url not in links:
                        links.append(full_url)
                        
        return links
