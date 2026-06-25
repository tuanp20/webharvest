"""JSON-LD Product Parser.

Extracts structured Product data from Schema.org JSON-LD tags.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from webharvest.models import ProductData, ProductVariant

logger = logging.getLogger("webharvest.extractors.json_ld")


class JsonLdProductParser:
    """Parses Schema.org/Product JSON-LD to ProductData."""

    @staticmethod
    def parse(json_ld_list: list[dict], url: str, source_site: str) -> Optional[ProductData]:
        """Finds a Product object in JSON-LD list and parses it."""
        product_obj = None

        # Recursively search for @type = Product
        def find_product(obj: Any) -> Optional[dict]:
            if isinstance(obj, dict):
                t = obj.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    return obj
                for val in obj.values():
                    found = find_product(val)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = find_product(item)
                    if found:
                        return found
            return None

        for doc in json_ld_list:
            product_obj = find_product(doc)
            if product_obj:
                break

        if not product_obj:
            return None

        try:
            title = product_obj.get("name") or ""
            if not title and "name" in product_obj:
                title = str(product_obj["name"])

            # Image
            from urllib.parse import urljoin
            image = product_obj.get("image")
            def _resolve_img(img):
                if not img:
                    return None
                if isinstance(img, str):
                    return img
                if isinstance(img, dict):
                    return img.get("contentUrl") or img.get("contentURL") or img.get("url")
                if isinstance(img, list) and img:
                    return _resolve_img(img[0])
                return None
            main_image = _resolve_img(image)
            if main_image:
                main_image = urljoin(url, main_image.strip())

            # Description
            description = product_obj.get("description")

            # Category
            category = product_obj.get("category")
            if isinstance(category, dict):
                category = category.get("name")

            # Brand
            brand = product_obj.get("brand")
            brand_name = None
            if isinstance(brand, dict):
                brand_name = brand.get("name")
            elif isinstance(brand, str):
                brand_name = brand

            # Price & Currency & Variants
            offers = product_obj.get("offers")
            price = None
            currency = "USD"
            variants = []
            colors = set()
            sizes = set()

            def parse_offer(offer: dict) -> ProductVariant:
                p_val = None
                p_str = offer.get("price")
                if p_str is not None:
                    try:
                        p_val = float(p_str)
                    except (ValueError, TypeError):
                        pass

                sku = offer.get("sku")
                avail = offer.get("availability")
                in_stock = True
                if avail and "OutOfStock" in str(avail):
                    in_stock = False

                # Variations: try explicit fields first
                color = offer.get("color")
                size = offer.get("size")

                # Parse from offer name (common format: "Color / Size" or "Color - Size")
                if not color and not size:
                    offer_name = offer.get("name") or ""
                    if offer_name:
                        # Common separators: " / ", " - ", " | "
                        for sep in [" / ", " - ", " | "]:
                            if sep in offer_name:
                                parts = [p.strip() for p in offer_name.split(sep)]
                                if len(parts) >= 2:
                                    # Heuristic: if second part looks like a size
                                    _size_keywords = {"xs", "s", "m", "l", "xl", "xxl", "xxxl",
                                                      "2xl", "3xl", "4xl", "5xl", "one size"}
                                    if parts[-1].lower().strip() in _size_keywords:
                                        color = parts[0]
                                        size = parts[-1]
                                    elif parts[0].lower().strip() in _size_keywords:
                                        size = parts[0]
                                        color = parts[-1]
                                    else:
                                        # Assume first=color, last=size if both exist
                                        color = parts[0]
                                        size = parts[-1] if len(parts) > 1 else None
                                break

                    # Also try extracting from SKU (format: "PRODUCT-COLOR-SIZE")
                    if not color and not size and sku:
                        sku_parts = sku.split("-")
                        if len(sku_parts) >= 3:
                            # Last part is often size, second-to-last is color
                            potential_size = sku_parts[-1].strip()
                            _size_keywords = {"xs", "s", "m", "l", "xl", "xxl", "xxxl",
                                              "2xl", "3xl", "4xl", "5xl"}
                            if potential_size.lower() in _size_keywords:
                                size = potential_size
                                color = sku_parts[-2].strip()

                # Clean up color/size if they contain the title or duplicate separators
                if color:
                    color = color.strip()
                    if title:
                        title_clean = title.strip()
                        if color.lower().startswith(title_clean.lower()):
                            color = color[len(title_clean):].strip()
                    color = color.strip(" -/|").strip()
                    if not color or color in ["-", "--", "---"]:
                        color = None

                if size:
                    size = size.strip()
                    if title:
                        title_clean = title.strip()
                        if size.lower().startswith(title_clean.lower()):
                            size = size[len(title_clean):].strip()
                    size = size.strip(" -/|").strip()
                    if not size or size in ["-", "--", "---"]:
                        size = None

                return ProductVariant(
                    color=color,
                    size=size,
                    price=p_val,
                    sku=sku,
                    in_stock=in_stock
                )

            if isinstance(offers, dict):
                # Check for nested offers array (aggregate offers)
                nested_offers = offers.get("offers")
                if isinstance(nested_offers, list):
                    for off in nested_offers:
                        if isinstance(off, dict):
                            v = parse_offer(off)
                            variants.append(v)
                            if v.color:
                                colors.add(v.color)
                            if v.size:
                                sizes.add(v.size)
                else:
                    # Single offer
                    v = parse_offer(offers)
                    price = v.price
                    currency = offers.get("priceCurrency") or "USD"
                    if v.color or v.size:
                        variants.append(v)
                        if v.color:
                            colors.add(v.color)
                        if v.size:
                            sizes.add(v.size)
            elif isinstance(offers, list):
                for off in offers:
                    if isinstance(off, dict):
                        v = parse_offer(off)
                        variants.append(v)
                        if v.color:
                            colors.add(v.color)
                        if v.size:
                            sizes.add(v.size)

            # Fallback price from single offers if empty
            if price is None and variants:
                price = variants[0].price

            # Ratings
            rating_val = None
            review_count = None
            aggregate_rating = product_obj.get("aggregateRating")
            if isinstance(aggregate_rating, dict):
                try:
                    rating_val = float(aggregate_rating.get("ratingValue") or 0)
                    review_count = int(aggregate_rating.get("reviewCount") or aggregate_rating.get("ratingCount") or 0)
                except (ValueError, TypeError):
                    pass

            return ProductData(
                title=title,
                url=url,
                source_site=source_site,
                main_image_url=main_image,
                price=price,
                currency=currency,
                description=description,
                category=category,
                variants=variants,
                colors=sorted(list(colors)),
                sizes=sorted(list(sizes)),
                brand=brand_name,
                rating=rating_val,
                review_count=review_count,
                raw_json=product_obj
            )

        except Exception as e:
            logger.warning("Failed to parse JSON-LD product: %s", e)
            return None
