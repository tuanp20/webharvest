"""BaseSiteExtractor class.

Provides common structure and utilities for site-specific catalog extractors.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional
from webharvest.models import ProductData

logger = logging.getLogger("webharvest.extractors.sites.base_site")


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
