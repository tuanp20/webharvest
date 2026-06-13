"""
WebHarvest License Server — Configuration & Tier Definitions.

Pricing, feature limits, and environment-based settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List


# ── Tier Definitions ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class TierConfig:
    name: str
    max_daily_urls: int
    max_concurrent: int
    allowed_fetchers: List[str]
    batch_crawl: bool
    stealth_mode: bool
    proxy_support: bool


TIERS: Dict[str, TierConfig] = {
    "basic": TierConfig(
        name="Basic",
        max_daily_urls=50,
        max_concurrent=1,
        allowed_fetchers=["auto", "static"],
        batch_crawl=False,
        stealth_mode=False,
        proxy_support=False,
    ),
    "pro": TierConfig(
        name="Pro",
        max_daily_urls=500,
        max_concurrent=5,
        allowed_fetchers=["auto", "static", "dynamic", "stealth"],
        batch_crawl=True,
        stealth_mode=True,
        proxy_support=True,
    ),
    "unlimited": TierConfig(
        name="Unlimited",
        max_daily_urls=999_999,
        max_concurrent=20,
        allowed_fetchers=["auto", "static", "dynamic", "stealth"],
        batch_crawl=True,
        stealth_mode=True,
        proxy_support=True,
    ),
}


# ── Pricing Matrix (VND) ─────────────────────────────────────────────────
# Discounts: 3mo → -10%, 6mo → -15%, 12mo → -20%

PRICING: Dict[str, Dict[int, int]] = {
    "basic":     {1: 99_000,  3: 267_300,  6: 504_900,  12: 950_400},
    "pro":       {1: 499_000, 3: 1_347_300, 6: 2_544_900, 12: 4_790_400},
    "unlimited": {1: 899_000, 3: 2_427_300, 6: 4_585_900, 12: 8_630_400},
}

DURATION_LABELS: Dict[int, str] = {
    1: "1 tháng",
    3: "3 tháng",
    6: "6 tháng",
    12: "1 năm",
}

VALID_DURATIONS = [1, 3, 6, 12]
VALID_TIERS = list(TIERS.keys())

# Max device rebinds allowed per key (before needing admin reset)
MAX_REBINDS = 2

# License validation cache TTL (seconds) — desktop app caches this long
VALIDATION_CACHE_TTL = 300  # 5 minutes

# Offline grace period (seconds) — desktop app allows offline usage this long
OFFLINE_GRACE_PERIOD = 86_400  # 24 hours


# ── Environment Config ────────────────────────────────────────────────────

@dataclass
class Settings:
    # Database
    database_url: str = ""

    # PayOS
    payos_client_id: str = ""
    payos_api_key: str = ""
    payos_checksum_key: str = ""
    payos_webhook_url: str = ""

    # Admin
    admin_password: str = "admin"  # MUST be changed in production

    # Server
    host: str = "0.0.0.0"
    port: int = 8443
    debug: bool = False

    # CORS — desktop apps calling from localhost
    cors_origins: List[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        origins_raw = os.getenv("CORS_ORIGINS", "*")
        origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://webharvest:webharvest@localhost:5432/webharvest_license",
            ),
            payos_client_id=os.getenv("PAYOS_CLIENT_ID", ""),
            payos_api_key=os.getenv("PAYOS_API_KEY", ""),
            payos_checksum_key=os.getenv("PAYOS_CHECKSUM_KEY", ""),
            payos_webhook_url=os.getenv("PAYOS_WEBHOOK_URL", ""),
            admin_password=os.getenv("ADMIN_PASSWORD", "admin"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8443")),
            debug=os.getenv("DEBUG", "").lower() in ("1", "true", "yes"),
            cors_origins=origins,
        )


def get_price(tier: str, duration_months: int) -> int | None:
    """Return price in VND for a tier + duration combo, or None if invalid."""
    return PRICING.get(tier, {}).get(duration_months)


def get_tier_config(tier: str) -> TierConfig | None:
    """Return the TierConfig for a tier name, or None if invalid."""
    return TIERS.get(tier)


def tier_to_dict(tier: str) -> dict | None:
    """Return tier config as a JSON-serializable dict."""
    tc = TIERS.get(tier)
    if not tc:
        return None
    return {
        "name": tc.name,
        "max_daily_urls": tc.max_daily_urls,
        "max_concurrent": tc.max_concurrent,
        "allowed_fetchers": tc.allowed_fetchers,
        "batch_crawl": tc.batch_crawl,
        "stealth_mode": tc.stealth_mode,
        "proxy_support": tc.proxy_support,
    }


def packages_list() -> list[dict]:
    """Return all packages for the pricing page."""
    result = []
    for tier_key, tier_cfg in TIERS.items():
        for duration, price in PRICING[tier_key].items():
            result.append({
                "tier": tier_key,
                "tier_name": tier_cfg.name,
                "duration_months": duration,
                "duration_label": DURATION_LABELS[duration],
                "price": price,
                "features": {
                    "max_daily_urls": tier_cfg.max_daily_urls,
                    "max_concurrent": tier_cfg.max_concurrent,
                    "batch_crawl": tier_cfg.batch_crawl,
                    "stealth_mode": tier_cfg.stealth_mode,
                    "proxy_support": tier_cfg.proxy_support,
                },
            })
    return result
