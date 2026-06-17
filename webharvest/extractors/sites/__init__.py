"""Site-specific extractors registry."""

from __future__ import annotations

from urllib.parse import urlparse
from typing import Optional

from .base_site import BaseSiteExtractor
from .teepublic import TeePublicExtractor
from .teechip import TeeChipExtractor
from .teelaunch import TeeLaunchExtractor
from .gearlaunch import GearLaunchExtractor
from .merchize import MerchizeExtractor
from .spreadshirt import SpreadshirtExtractor
from .gooten import GootenExtractor
from .shopify import ShopifyExtractor
from .woocommerce import WooCommerceExtractor
from .printful import PrintfulExtractor
from .printify import PrintifyExtractor
from .gelato import GelatoExtractor
from .shopbase import ShopBaseExtractor
from .zazzle import ZazzleExtractor
from .ebay import EbayExtractor
from .redbubble import RedbubbleExtractor
from .society6 import Society6Extractor
from .teespring import TeeSpringExtractor
from .aliexpress import AliExpressExtractor

EXTRACTORS = [
    TeePublicExtractor,
    TeeChipExtractor,
    TeeLaunchExtractor,
    GearLaunchExtractor,
    MerchizeExtractor,
    SpreadshirtExtractor,
    GootenExtractor,
    ShopifyExtractor,
    WooCommerceExtractor,
    PrintfulExtractor,
    PrintifyExtractor,
    GelatoExtractor,
    ShopBaseExtractor,
    ZazzleExtractor,
    EbayExtractor,
    RedbubbleExtractor,
    Society6Extractor,
    TeeSpringExtractor,
    AliExpressExtractor,
]


def detect_extractor(url: str) -> Optional[BaseSiteExtractor]:
    """Detects and returns a matching SiteExtractor for the given URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not domain and parsed.path:
            # Handle URLs without scheme (e.g. ebay.com/...)
            domain = parsed.path.split("/")[0].lower()
            
        for extractor_cls in EXTRACTORS:
            # Check if domain contains target domain (e.g. "ebay.com" in "ebay.com")
            target = extractor_cls.SITE_DOMAIN.lower()
            if target and target in domain:
                return extractor_cls()
                
        # Default fallback to Shopify if it looks like a shopify store or shopify in domain
        if "shopify" in domain or "myshopify" in domain:
            return ShopifyExtractor()
            
        return None
    except Exception:
        return None
