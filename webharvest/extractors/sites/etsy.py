"""Etsy Extractor.

Extracts products from Etsy listings and shop pages.
Uses stealth fetcher (curl_cffi TLS impersonation) because Etsy
employs DataDome anti-bot which blocks standard HTTP clients.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from webharvest.models import ProductData, ProductVariant
from webharvest.extractors.json_parsers.json_ld import JsonLdProductParser
from webharvest.extractors.content import ContentExtractor
from .base_site import BaseSiteExtractor


class EtsyExtractor(BaseSiteExtractor):
    """Etsy Extractor (Stealth — DataDome protected)."""

    SITE_DOMAIN = "etsy.com"
    FETCHER_TYPE = "stealth"
    RATE_LIMIT = {"rate": 0.3, "burst": 1}  # Conservative: ~18 req/min

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        # 1. Try JSON-LD (Etsy embeds Product schema)
        soup = BeautifulSoup(html, "lxml")
        json_ld_list = ContentExtractor._extract_json_ld(soup)
        product = JsonLdProductParser.parse(json_ld_list, url, self.SITE_DOMAIN)
        if product:
            # Enrich with Etsy-specific data
            product = self._enrich_from_html(product, soup, url)
            return product

        # 2. Fallback: parse Etsy's __NEXT_DATA__ or HTML structure
        return self._parse_from_html(soup, url)

    def _enrich_from_html(self, product: ProductData, soup: BeautifulSoup, url: str) -> ProductData:
        """Enrich JSON-LD product with Etsy-specific HTML details."""
        # Extract all images (Etsy has image carousel)
        if not product.main_image_url:
            og_img = soup.find("meta", property="og:image")
            if og_img:
                product.main_image_url = og_img.get("content")

        # Extract variants from variation selectors
        variants = self._extract_variants(soup)
        if variants and not product.variants:
            product.variants = variants

        # Extract category breadcrumbs
        breadcrumbs = soup.find_all("a", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumbs:
            cats = [b.get_text(strip=True) for b in breadcrumbs if b.get_text(strip=True)]
            if cats:
                product.category = " > ".join(cats)

        return product

    def _parse_from_html(self, soup: BeautifulSoup, url: str) -> Optional[ProductData]:
        """Parse product from HTML when JSON-LD is unavailable."""
        # Title
        title_tag = soup.find("h1", {"data-buy-box-listing-title": True}) or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "")

        # Price
        price_val = None
        price_tag = soup.find("div", {"data-buy-box-region": "price"})
        if price_tag:
            price_text = price_tag.get_text(strip=True)
            try:
                price_val = float(re.sub(r"[^\d.]", "", price_text.split()[0]))
            except (ValueError, IndexError):
                pass

        if price_val is None:
            price_meta = soup.find("meta", property="product:price:amount")
            if price_meta:
                try:
                    price_val = float(price_meta.get("content", "0"))
                except ValueError:
                    pass

        # Currency
        currency = "USD"
        currency_meta = soup.find("meta", property="product:price:currency")
        if currency_meta:
            currency = currency_meta.get("content", "USD")

        # Image
        image_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img:
            image_url = og_img.get("content")
        if not image_url:
            img_tag = soup.find("img", class_=re.compile(r"listing.*image", re.I))
            if img_tag:
                image_url = img_tag.get("src")

        # Description
        description = None
        desc_meta = soup.find("meta", attrs={"name": "description"})
        if desc_meta:
            description = desc_meta.get("content")

        # Variants
        variants = self._extract_variants(soup)

        return ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=image_url,
            price=price_val,
            currency=currency,
            description=description,
            category="Handmade / Vintage",
            variants=variants,
        )

    def _extract_variants(self, soup: BeautifulSoup) -> list[ProductVariant]:
        """Extract product variants from Etsy variation selectors."""
        variants = []
        # Etsy uses select elements with id like 'variation-selector-*'
        selectors = soup.find_all("select", id=re.compile(r"variation-selector", re.I))
        for sel in selectors:
            options = sel.find_all("option")
            for opt in options:
                val = opt.get_text(strip=True)
                if val and not opt.get("disabled") and val.lower() not in ("select an option", "choose"):
                    variants.append(ProductVariant(
                        color=val if "color" in sel.get("id", "").lower() else "",
                        size=val if "size" in sel.get("id", "").lower() else "",
                    ))
        return variants

    def extract_listing(self, html: str, url: str) -> list[str]:
        """Extract product URLs from Etsy shop or search listing pages.

        Only returns URLs that match the pattern /listing/{digits}/{slug}
        and excludes sub-pages (favoriters, reviews, etc.) and the current URL itself.
        """
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()

        # Pattern: /listing/{numeric_id}/{slug} — must end with slug, not sub-pages
        listing_pattern = re.compile(r"/listing/(\d+)/[a-z0-9_-]+(?:\?|$)", re.I)

        # Exclude sub-pages of listings
        exclude_suffixes = (
            "/favoriters", "/reviews", "/shipping", "/related",
            "/similar", "/report", "/share",
        )

        # Extract current listing ID to avoid self-referencing
        current_match = re.search(r"/listing/(\d+)/", url)
        current_listing_id = current_match.group(1) if current_match else None

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/listing/" not in href:
                continue

            # Skip sub-pages
            if any(href.rstrip("/").endswith(suffix) for suffix in exclude_suffixes):
                continue

            # Must match valid listing pattern
            if not listing_pattern.search(href):
                continue

            full_url = urljoin(url, href)
            # Clean tracking params
            parsed = urlparse(full_url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

            # Skip self-reference (same listing ID as current page)
            link_match = re.search(r"/listing/(\d+)/", clean_url)
            if link_match and current_listing_id and link_match.group(1) == current_listing_id:
                continue

            if clean_url not in seen:
                seen.add(clean_url)
                links.append(clean_url)

        return links

