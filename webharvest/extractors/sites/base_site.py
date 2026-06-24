"""BaseSiteExtractor class.

Provides common structure and utilities for site-specific catalog extractors.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from webharvest.models import ProductData, ProductVariant

logger = logging.getLogger("webharvest.extractors.sites.base_site")

# ---------------------------------------------------------------------------
# Patterns to filter out non-product images
# ---------------------------------------------------------------------------
_ICON_LOGO_PATTERNS = re.compile(
    r"(logo|icon|favicon|sprite|badge|rating|star|flag|banner|placeholder|"
    r"loading|spinner|arrow|chevron|close|search|cart|menu|social|facebook|"
    r"twitter|instagram|pinterest|youtube|tiktok|payment|visa|mastercard|"
    r"paypal|amex|stripe|shopify-icon|avatar|profile-pic)",
    re.IGNORECASE,
)


class BaseSiteExtractor(ABC):
    """Abstract base class for all website extractors."""

    SITE_DOMAIN: str = ""
    FETCHER_TYPE: str = "static"  # static, dynamic, stealth
    RATE_LIMIT: dict[str, float] = {"rate": 0.5, "burst": 2}  # Default: 30 req/min

    @abstractmethod
    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        """Extracts product details from a single product page HTML."""
        pass

    @abstractmethod
    def extract_listing(self, html: str, url: str) -> list[str]:
        """Extracts product page URLs from a catalog or category listing page HTML."""
        pass

    # ------------------------------------------------------------------
    # Common extraction helpers — used by all site extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_main_image(soup: BeautifulSoup, url: str) -> Optional[str]:
        """Extract the main product image URL with smart priority.

        Priority order:
        1. og:image meta tag (most reliable for product pages)
        2. itemprop="image" element
        3. First image inside a product gallery container
        4. First large <img> that is not a logo/icon
        """
        # 1. og:image — most reliable
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            img_url = og["content"].strip()
            if img_url:
                return urljoin(url, img_url)

        # 2. itemprop="image"
        itemprop_img = soup.find(attrs={"itemprop": "image"})
        if itemprop_img:
            img_url = (
                itemprop_img.get("content")
                or itemprop_img.get("src")
                or itemprop_img.get("href")
            )
            if img_url:
                return urljoin(url, img_url.strip())

        # 3. Product gallery containers (common CSS class patterns)
        gallery_selectors = [
            {"class_": re.compile(r"product.*(image|gallery|photo|media)", re.I)},
            {"class_": re.compile(r"(main|primary|featured).*(image|photo|img)", re.I)},
            {"class_": re.compile(r"(image|photo|gallery).*(product|main|primary)", re.I)},
            {"id": re.compile(r"product.*(image|gallery|photo)", re.I)},
        ]
        for selector in gallery_selectors:
            container = soup.find(True, **selector)
            if container:
                img = container.find("img", src=True)
                if img and img.get("src"):
                    src = img["src"]
                    if not _is_non_product_image(src):
                        return urljoin(url, src.strip())

        # 4. First reasonable <img> that's not a logo/icon
        for img in soup.find_all("img", src=True):
            src = img.get("src", "")
            if not src or src.startswith("data:"):
                continue
            if _is_non_product_image(src):
                continue
            # Skip tiny images (likely icons)
            w = _int_or_none(img.get("width"))
            h = _int_or_none(img.get("height"))
            if w and w < 50:
                continue
            if h and h < 50:
                continue
            return urljoin(url, src.strip())

        return None

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> Optional[str]:
        """Extract product description from common locations.

        Priority:
        1. itemprop="description" element
        2. Product description container (CSS class/id)
        3. meta[name="description"]
        """
        # 1. itemprop="description"
        itemprop = soup.find(attrs={"itemprop": "description"})
        if itemprop:
            text = itemprop.get_text(strip=True)
            if text and len(text) > 10:
                return text

        # 2. Common description containers
        desc_patterns = [
            {"class_": re.compile(r"product.*(description|desc|details)", re.I)},
            {"class_": re.compile(r"(description|desc).*(product|content)", re.I)},
            {"id": re.compile(r"(product.*desc|tab.*desc|description)", re.I)},
            {"class_": "woocommerce-product-details__short-description"},
            {"class_": "product-description"},
            {"id": "tab-description"},
        ]
        for pattern in desc_patterns:
            tag = soup.find(True, **pattern)
            if tag:
                text = tag.get_text(strip=True)
                if text and len(text) > 10:
                    return text

        # 3. meta description (shorter, but better than nothing)
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            content = meta["content"].strip()
            if content and len(content) > 10:
                return content

        return None

    @staticmethod
    def _extract_variations(soup: BeautifulSoup) -> tuple[list[ProductVariant], list[str], list[str]]:
        """Extract product variations (color, size) from common UI patterns.

        Returns:
            Tuple of (variants_list, colors_list, sizes_list)
        """
        colors: set[str] = set()
        sizes: set[str] = set()
        variants: list[ProductVariant] = []

        # Common size values for heuristic classification
        size_keywords = {
            "xs", "s", "m", "l", "xl", "xxl", "xxxl", "2xl", "3xl", "4xl", "5xl",
            "one size", "os", "free size",
        }

        # 1. Look for <select> elements with size/color options
        for select in soup.find_all("select"):
            label_text = ""
            # Check associated label
            select_id = select.get("id", "")
            select_name = select.get("name", "")
            label = soup.find("label", attrs={"for": select_id}) if select_id else None
            if label:
                label_text = label.get_text(strip=True).lower()
            else:
                label_text = (select_name or select_id or "").lower()

            option_values = []
            for option in select.find_all("option"):
                val = option.get_text(strip=True)
                if val and val.lower() not in ("", "select", "choose", "pick", "--", "---"):
                    option_values.append(val)

            if not option_values:
                continue

            if "color" in label_text or "colour" in label_text or "màu" in label_text:
                colors.update(option_values)
            elif "size" in label_text or "kích" in label_text:
                sizes.update(option_values)
            else:
                # Heuristic: if values look like sizes
                if any(v.lower().strip() in size_keywords for v in option_values):
                    sizes.update(option_values)
                else:
                    colors.update(option_values)

        # 2. Look for swatch/variant elements (buttons, radio, data attributes)
        swatch_patterns = [
            {"class_": re.compile(r"(swatch|variant|option).*(color|colour)", re.I)},
            {"class_": re.compile(r"(color|colour).*(swatch|variant|option|selector)", re.I)},
        ]
        for pattern in swatch_patterns:
            for el in soup.find_all(True, **pattern):
                val = (
                    el.get("data-value")
                    or el.get("title")
                    or el.get("aria-label")
                    or el.get_text(strip=True)
                )
                if val and len(val) < 50:
                    colors.add(val)

        size_swatch_patterns = [
            {"class_": re.compile(r"(swatch|variant|option).*(size)", re.I)},
            {"class_": re.compile(r"(size).*(swatch|variant|option|selector)", re.I)},
        ]
        for pattern in size_swatch_patterns:
            for el in soup.find_all(True, **pattern):
                val = (
                    el.get("data-value")
                    or el.get("title")
                    or el.get("aria-label")
                    or el.get_text(strip=True)
                )
                if val and len(val) < 30:
                    sizes.add(val)

        # Build variant list from combinations
        color_list = sorted(list(colors))
        size_list = sorted(list(sizes))

        if color_list and size_list:
            for c in color_list:
                for s in size_list:
                    variants.append(ProductVariant(color=c, size=s))
        elif color_list:
            for c in color_list:
                variants.append(ProductVariant(color=c))
        elif size_list:
            for s in size_list:
                variants.append(ProductVariant(size=s))

        return variants, color_list, size_list

    @staticmethod
    def _extract_category(soup: BeautifulSoup) -> Optional[str]:
        """Extract product category from common locations.

        Priority:
        1. Breadcrumb navigation (last meaningful item)
        2. itemprop="category" 
        3. Product type meta/data attribute
        """
        # 1. Breadcrumbs
        breadcrumb_patterns = [
            {"class_": re.compile(r"breadcrumb", re.I)},
            {"id": re.compile(r"breadcrumb", re.I)},
            {"aria-label": "breadcrumb"},
            {"role": "navigation", "aria-label": re.compile(r"breadcrumb", re.I)},
        ]
        for pattern in breadcrumb_patterns:
            bc = soup.find(True, **pattern)
            if bc:
                # Get breadcrumb items
                items = bc.find_all(["a", "span", "li"])
                texts = []
                for item in items:
                    t = item.get_text(strip=True)
                    if t and t.lower() not in ("home", "trang chủ", "/", ">", "›", "»"):
                        texts.append(t)
                if texts:
                    # Return last meaningful breadcrumb (closest to product)
                    return texts[-1]

        # 2. itemprop="category"
        cat_el = soup.find(attrs={"itemprop": "category"})
        if cat_el:
            text = cat_el.get("content") or cat_el.get_text(strip=True)
            if text:
                return text

        # 3. Product category from data attributes or specific containers
        cat_patterns = [
            {"class_": re.compile(r"product.*(category|type)", re.I)},
            {"class_": re.compile(r"(category|type).*product", re.I)},
        ]
        for pattern in cat_patterns:
            el = soup.find(True, **pattern)
            if el:
                text = el.get_text(strip=True)
                if text and len(text) < 100:
                    return text

        return None


def _is_non_product_image(url: str) -> bool:
    """Check if URL looks like a non-product image (logo, icon, etc.)."""
    return bool(_ICON_LOGO_PATTERNS.search(url))


def _int_or_none(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
