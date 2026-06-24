"""Shopify products.json Parser.

Parses public shopify products.json catalog listings.
"""

from __future__ import annotations

import logging
from typing import Any
from webharvest.models import ProductData, ProductVariant

logger = logging.getLogger("webharvest.extractors.shopify_json")


class ShopifyJsonParser:
    """Parses Shopify products.json format into ProductData models."""

    @staticmethod
    def parse_products(data: dict[str, Any], base_url: str) -> list[ProductData]:
        """Parses list of products from Shopify JSON into ProductData objects."""
        products = []
        raw_products = data.get("products", [])
        if not isinstance(raw_products, list):
            return []

        # Remove trailing slash
        base_url = base_url.rstrip("/")

        for p in raw_products:
            if not isinstance(p, dict):
                continue
            try:
                title = p.get("title") or ""
                handle = p.get("handle") or ""
                url = f"{base_url}/products/{handle}" if handle else base_url

                # Images
                images = p.get("images", [])
                main_image = None
                additional_images = []
                if isinstance(images, list) and images:
                    main_image = images[0].get("src")
                    if main_image and main_image.startswith("//"):
                        main_image = f"https:{main_image}"
                    additional_images = [
                        img.get("src") for img in images[1:] if img.get("src")
                    ]
                    additional_images = [
                        f"https:{img}" if img.startswith("//") else img
                        for img in additional_images
                    ]

                # Vendor/Brand
                brand = p.get("vendor")

                # Type/Category
                category = p.get("product_type")

                # Tags
                tags = p.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]

                # Variants
                variants = []
                colors = set()
                sizes = set()

                raw_variants = p.get("variants", [])
                if isinstance(raw_variants, list):
                    for v in raw_variants:
                        if not isinstance(v, dict):
                            continue
                        
                        price_val = None
                        price_str = v.get("price")
                        if price_str is not None:
                            try:
                                price_val = float(price_str)
                            except (ValueError, TypeError):
                                pass

                        # Figure out size and color from options
                        color_val = None
                        size_val = None
                        
                        # Shopify has option1, option2, option3
                        # Let's inspect the options configuration to map correctly
                        options_config = p.get("options", [])
                        options_mapping = {}
                        if isinstance(options_config, list):
                            for idx, opt in enumerate(options_config):
                                name = opt.get("name", "").lower()
                                if "color" in name or "colour" in name:
                                    options_mapping[f"option{idx+1}"] = "color"
                                elif "size" in name:
                                    options_mapping[f"option{idx+1}"] = "size"

                        # Extract based on mapping, or fallback
                        for opt_key in ["option1", "option2", "option3"]:
                            val = v.get(opt_key)
                            if not val:
                                continue
                            role = options_mapping.get(opt_key)
                            if role == "color":
                                color_val = val
                            elif role == "size":
                                size_val = val
                            else:
                                # Fallback heuristic
                                val_lower = str(val).lower()
                                if val_lower in ["s", "m", "l", "xl", "xxl", "xs", "xxxl"] or any(char.isdigit() for char in val_lower):
                                    if not size_val:
                                        size_val = val
                                else:
                                    if not color_val:
                                        color_val = val

                        if color_val:
                            colors.add(color_val)
                        if size_val:
                            sizes.add(size_val)

                        # Check availability
                        in_stock = v.get("available", True)

                        var_img = v.get("featured_image", {}).get("src") if isinstance(v.get("featured_image"), dict) else None
                        if var_img and var_img.startswith("//"):
                            var_img = f"https:{var_img}"

                        variants.append(ProductVariant(
                            color=color_val,
                            size=size_val,
                            price=price_val,
                            sku=v.get("sku"),
                            in_stock=in_stock,
                            image_url=var_img
                        ))

                # Primary price
                primary_price = None
                if variants:
                    primary_price = variants[0].price

                description = p.get("body_html")

                products.append(ProductData(
                    title=title,
                    url=url,
                    source_site="shopify",
                    main_image_url=main_image,
                    price=primary_price,
                    description=description,
                    category=category,
                    variants=variants,
                    colors=sorted(list(colors)),
                    sizes=sorted(list(sizes)),
                    brand=brand,
                    tags=tags,
                    additional_images=additional_images,
                    raw_json=p
                ))

            except Exception as e:
                logger.warning("Failed to parse Shopify product JSON: %s", e)

        return products
