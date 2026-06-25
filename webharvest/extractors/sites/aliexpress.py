"""AliExpress Extractor.

Extracts products from AliExpress.
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


class AliExpressExtractor(BaseSiteExtractor):
    """AliExpress Extractor (Tầng 3 - Stealth)."""

    SITE_DOMAIN = "aliexpress.com"
    FETCHER_TYPE = "stealth"
    RATE_LIMIT = {"rate": 0.08, "burst": 1}
    WAIT_TIMEOUT = 5000  # Wait 5 seconds for JS to populate product data

    def extract_product(self, html: str, url: str) -> Optional[ProductData]:
        soup = BeautifulSoup(html, "lxml")
        
        # Try JSON-LD first (but bypass/skip if it's the skeleton "Aliexpress" JSON-LD)
        json_ld_list = ContentExtractor._extract_json_ld(soup)
        product = JsonLdProductParser.parse(json_ld_list, url, self.SITE_DOMAIN)
        
        if product and product.title and product.title.lower() != "aliexpress" and product.price:
            product.title = re.sub(r"\s+-\s+AliExpress.*", "", product.title, flags=re.I).strip()
            
            # Supplement JSON-LD with DOM-extracted details (variations, category, description)
            variants, colors, sizes = self._extract_aliexpress_variations(soup)
            product.variants = variants
            product.colors = colors
            product.sizes = sizes
            
            if not product.description or len(product.description) < 20:
                product.description = self._extract_description(soup)
            if not product.category or product.category == "E-commerce item":
                product.category = self._extract_category(soup) or "E-commerce item"
                
            # If additional images are empty:
            if not product.additional_images:
                images = []
                for img in soup.find_all("img", class_=re.compile(r"product-img")):
                    src = img.get("src") or img.get("data-src")
                    cleaned = self._clean_image_url(src)
                    if cleaned and cleaned not in images:
                        images.append(cleaned)
                if images:
                    product.main_image_url = images[0]
                    product.additional_images = images[1:]

            # Aggregate variant/classification images into additional_images
            existing_images = set(product.additional_images or [])
            if product.main_image_url:
                existing_images.add(product.main_image_url)
            
            additional_list = list(product.additional_images or [])
            if product.variants:
                for variant in product.variants:
                    if variant.image_url and variant.image_url not in existing_images:
                        existing_images.add(variant.image_url)
                        additional_list.append(variant.image_url)
            product.additional_images = additional_list

            return product

        # Fallback to custom robust DOM parsing
        soup = BeautifulSoup(html, "lxml")
        
        # 1. Title
        title = None
        title_elem = soup.select_one('[data-pl="product-title"]')
        if title_elem:
            title = title_elem.get_text(strip=True)
        else:
            for h1 in soup.find_all("h1"):
                text = h1.get_text(strip=True)
                if text.lower() != "aliexpress" and text:
                    title = text
                    break
        if not title:
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

        # Remove " - AliExpress", " - AliExpress.com", etc.
        title = re.sub(r"\s+-\s+AliExpress.*", "", title, flags=re.I).strip()

        # 2. Price and Currency
        current_price = None
        currency = "VND"  # Default fallback

        curr_el = soup.find(class_=re.compile(r"price-default--current"))
        if curr_el:
            current_price = curr_el.get_text(strip=True)

        price_val, parsed_curr = self._parse_price_and_currency(current_price)
        if not price_val and not current_price:
            # Fallback to legacy price current tags if needed
            price_tag = soup.find(class_=re.compile(r"price-current|product-price|uniform-banner-box-price", re.I))
            if price_tag:
                price_val, parsed_curr = self._parse_price_and_currency(price_tag.get_text(strip=True))
        
        if parsed_curr:
            currency = parsed_curr

        # 3. Clean and Resolve Images
        images = []
        for img in soup.find_all("img", class_=re.compile(r"product-img")):
            src = img.get("src") or img.get("data-src")
            cleaned = self._clean_image_url(src)
            if cleaned and cleaned not in images:
                images.append(cleaned)
                
        # Fallback to og:image if no images found
        if not images:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                images.append(self._clean_image_url(og_img.get("content")))
        if not images:
            # Use base main image extraction fallback
            fallback_img = self._extract_main_image(soup, url)
            if fallback_img:
                images.append(self._clean_image_url(fallback_img))

        main_image = images[0] if images else None
        additional_images = images[1:] if len(images) > 1 else []

        # 4. Description
        description = self._extract_description(soup)

        # 5. Category
        category = self._extract_category(soup) or "E-commerce item"

        # 6. Variations
        variants, colors, sizes = self._extract_aliexpress_variations(soup)

        if not title or title.lower() in ("aliexpress", "aliexpress.com") or price_val is None:
            return None

        product_data = ProductData(
            title=title,
            url=url,
            source_site=self.SITE_DOMAIN,
            main_image_url=main_image,
            price=price_val,
            currency=currency,
            description=description,
            category=category,
            variants=variants,
            colors=colors,
            sizes=sizes,
            additional_images=additional_images,
        )

        # Aggregate variant/classification images into additional_images
        existing_images = set(product_data.additional_images or [])
        if product_data.main_image_url:
            existing_images.add(product_data.main_image_url)
        
        additional_list = list(product_data.additional_images or [])
        if product_data.variants:
            for variant in product_data.variants:
                if variant.image_url and variant.image_url not in existing_images:
                    existing_images.add(variant.image_url)
                    additional_list.append(variant.image_url)
        product_data.additional_images = additional_list

        return product_data

    def _clean_image_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        # remove sizing/compression suffixes
        url = re.sub(r'_(?:[0-9]+x[0-9]+|Q[0-9]+|q[0-9]+)[^/]*$', '', url)
        # remove file format conversions
        url = re.sub(r'\.webp$|\.avif$', '', url)
        return url

    def _parse_price_and_currency(self, price_str: Optional[str]) -> tuple[Optional[float], str]:
        if not price_str:
            return None, "VND"
            
        currency_map = {
            '₫': 'VND',
            '$': 'USD',
            '€': 'EUR',
            '£': 'GBP',
            '¥': 'CNY',
            'руб': 'RUB',
            'rub': 'RUB',
        }
        
        # Clean the string for currency search
        price_str_clean = price_str.replace(" ", "")
        
        currency = "VND"
        for symbol, curr in currency_map.items():
            if symbol in price_str_clean.lower():
                currency = curr
                break
                
        # Extract digits, dot, comma
        cleaned = re.sub(r"[^\d.,]", "", price_str_clean)
        if not cleaned:
            return None, currency
            
        # Standardize number format
        if currency == "VND":
            val_str = re.sub(r"[^\d]", "", cleaned)
            return float(val_str) if val_str else None, currency
            
        dots = cleaned.count('.')
        commas = cleaned.count(',')
        
        if dots == 1 and commas == 0:
            parts = cleaned.split('.')
            if len(parts[1]) == 3:
                cleaned = cleaned.replace('.', '')
        elif commas == 1 and dots == 0:
            parts = cleaned.split(',')
            if len(parts[1]) == 3:
                cleaned = cleaned.replace(',', '')
            else:
                cleaned = cleaned.replace(',', '.')
        elif dots > 0 and commas > 0:
            if cleaned.find(',') < cleaned.find('.'):
                cleaned = cleaned.replace(',', '')
            else:
                cleaned = cleaned.replace('.', '').replace(',', '.')
        elif dots > 1:
            cleaned = cleaned.replace('.', '')
        elif commas > 1:
            cleaned = cleaned.replace(',', '')
            
        try:
            return float(cleaned), currency
        except ValueError:
            return None, currency

    def _extract_aliexpress_variations(
        self, soup: BeautifulSoup
    ) -> tuple[list[ProductVariant], list[str], list[str]]:
        extracted_colors = []  # list of dict: {"name": str, "image_url": str, "in_stock": bool}
        extracted_sizes = []   # list of dict: {"name": str, "in_stock": bool}
        
        # Match all possible wrappers
        raw_wraps = soup.find_all(class_=re.compile(r"sku-item--property|sku-property|sku-item--wrap|sku--wrap"))
        
        # Filter to keep only leaf wrappers (discard parent wrappers containing other wrappers)
        prop_wraps = []
        for w in raw_wraps:
            is_parent = False
            for other in raw_wraps:
                if other is not w and other in w.descendants:
                    is_parent = True
                    break
            if not is_parent:
                prop_wraps.append(w)
                
        for wrap in prop_wraps:
            title_el = wrap.find(class_=re.compile(r"sku-item--title|sku-title"))
            prop_title = title_el.get_text(strip=True).lower() if title_el else ""
            
            is_color = any(k in prop_title for k in ("color", "colour", "màu", "style", "type", "pattern", "model"))
            is_size = any(k in prop_title for k in ("size", "kích", "specification", "cap", "storage", "dung lượng", "length", "dài"))
            
            if not is_color and not is_size:
                if not extracted_colors:
                    is_color = True
                else:
                    is_size = True
                    
            option_elements = wrap.find_all(class_=re.compile(r"sku-item--image|sku-item--text|sku-item--box|sku-item--skus"))
            for opt in option_elements:
                img = opt.find("img")
                img_src = self._clean_image_url(img.get("src") or img.get("data-src")) if img else None
                
                is_sold_out = any("soldOut" in c for c in opt.get("class", []))
                in_stock = not is_sold_out
                
                txt = opt.get_text(strip=True)
                if not txt and img:
                    txt = img.get("alt") or img.get("title") or ""
                    
                if not txt:
                    continue
                    
                if is_color:
                    if not any(c["name"] == txt for c in extracted_colors):
                        extracted_colors.append({
                            "name": txt,
                            "image_url": img_src,
                            "in_stock": in_stock
                        })
                else:
                    if not any(s["name"] == txt for s in extracted_sizes):
                        extracted_sizes.append({
                            "name": txt,
                            "in_stock": in_stock
                        })
                        
        variants = []
        color_list = [c["name"] for c in extracted_colors]
        size_list = [s["name"] for s in extracted_sizes]
        
        if extracted_colors and extracted_sizes:
            for c in extracted_colors:
                for s in extracted_sizes:
                    variants.append(ProductVariant(
                        color=c["name"],
                        size=s["name"],
                        in_stock=c["in_stock"] and s["in_stock"],
                        image_url=c["image_url"]
                    ))
        elif extracted_colors:
            for c in extracted_colors:
                variants.append(ProductVariant(
                    color=c["name"],
                    in_stock=c["in_stock"],
                    image_url=c["image_url"]
                ))
        elif extracted_sizes:
            for s in extracted_sizes:
                variants.append(ProductVariant(
                    size=s["name"],
                    in_stock=s["in_stock"]
                ))
                
        return variants, color_list, size_list


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

    def is_product_url(self, url: str) -> bool:
        """Determines if a URL is an AliExpress product detail page."""
        parsed = urlparse(url)
        return "/item/" in parsed.path
