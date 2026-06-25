"""WooCommerce Extractor.

Extracts products from WooCommerce stores.
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

        # WooCommerce-specific gallery image, fallback to base helper
        image_url = None
        gallery_div = soup.find("div", class_="woocommerce-product-gallery__image")
        if gallery_div:
            nested_img = gallery_div.find("img")
            if nested_img:
                image_url = nested_img.get("src")
        if not image_url:
            wp_img = soup.find("img", class_="wp-post-image")
            if wp_img:
                image_url = wp_img.get("src")
        if not image_url:
            image_url = self._extract_main_image(soup, url)

        # Description — WooCommerce specific containers first
        desc_tag = soup.find("div", class_="woocommerce-product-details__short-description") or soup.find("div", id="tab-description")
        description = desc_tag.get_text(strip=True) if desc_tag else None
        if not description:
            description = self._extract_description(soup)

        # Variations
        variants, colors, sizes = self._extract_variations(soup)

        # Category
        category = self._extract_category(soup) or "Shop Product"

        return ProductData(
            title=title,
            url=url,
            source_site="woocommerce",
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
