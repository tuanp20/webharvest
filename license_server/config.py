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
    proxy_quota_gb: float         # Monthly proxy bandwidth quota in GB
    proxy_session_ttl: int        # Proxy session TTL in seconds
    max_concurrent_proxy: int     # Max concurrent proxy sessions


TIERS: Dict[str, TierConfig] = {
    "basic": TierConfig(
        name="Basic",
        max_daily_urls=50,
        max_concurrent=1,
        allowed_fetchers=["auto", "static"],
        batch_crawl=False,
        stealth_mode=False,
        proxy_quota_gb=1.0,
        proxy_session_ttl=120,
        max_concurrent_proxy=1,
    ),
    "pro": TierConfig(
        name="Pro",
        max_daily_urls=500,
        max_concurrent=5,
        allowed_fetchers=["auto", "static", "dynamic", "stealth"],
        batch_crawl=True,
        stealth_mode=True,
        proxy_quota_gb=10.0,
        proxy_session_ttl=300,
        max_concurrent_proxy=3,
    ),
    "unlimited": TierConfig(
        name="Unlimited",
        max_daily_urls=999_999,
        max_concurrent=20,
        allowed_fetchers=["auto", "static", "dynamic", "stealth"],
        batch_crawl=True,
        stealth_mode=True,
        proxy_quota_gb=50.0,
        proxy_session_ttl=600,
        max_concurrent_proxy=5,
    ),
    "trial": TierConfig(
        name="Dùng thử",
        max_daily_urls=20,
        max_concurrent=5,
        allowed_fetchers=["auto", "static", "dynamic", "stealth"],
        batch_crawl=True,
        stealth_mode=True,
        proxy_quota_gb=0.5,
        proxy_session_ttl=300,
        max_concurrent_proxy=3,
    ),
}


# ── Pricing Matrix (VND) ─────────────────────────────────────────────────
# Discounts: 3mo → -10%, 6mo → -15%, 12mo → -20%

PRICING: Dict[str, Dict[int, int]] = {
    "basic":     {1: 149_000,  3: 402_300,  6: 759_900,   12: 1_430_400},
    "pro":       {1: 699_000,  3: 1_887_300, 6: 3_564_900, 12: 6_710_400},
    "unlimited": {1: 1_499_000, 3: 4_047_300, 6: 7_649_900, 12: 14_390_400},
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

# Trial system
TRIAL_MAX_URLS = 20  # Total lifetime URLs for trial
TRIAL_EXPIRY_DAYS = 14  # Trial expires after 14 days


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

    # DataImpulse Proxy
    di_username: str = ""
    di_password: str = ""
    di_default_country: str = ""

    # Admin
    admin_password: str = "admin"  # MUST be changed in production

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""

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
            di_username=os.getenv("DI_USERNAME", ""),
            di_password=os.getenv("DI_PASSWORD", ""),
            di_default_country=os.getenv("DI_DEFAULT_COUNTRY", ""),
            admin_password=os.getenv("ADMIN_PASSWORD", "admin"),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from_email=os.getenv("SMTP_FROM_EMAIL", ""),
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
        "proxy_quota_gb": tc.proxy_quota_gb,
        "proxy_session_ttl": tc.proxy_session_ttl,
        "max_concurrent_proxy": tc.max_concurrent_proxy,
    }


def packages_list() -> list[dict]:
    """Return all packages for the pricing page."""
    result = []

    # Add trial package (free)
    trial_cfg = TIERS.get("trial")
    if trial_cfg:
        result.append({
            "tier": "trial",
            "tier_name": trial_cfg.name,
            "duration_months": 0,
            "duration_label": f"{TRIAL_EXPIRY_DAYS} ngày",
            "price": 0,
            "features": {
                "max_total_urls": TRIAL_MAX_URLS,
                "max_daily_urls": trial_cfg.max_daily_urls,
                "max_concurrent": trial_cfg.max_concurrent,
                "batch_crawl": trial_cfg.batch_crawl,
                "stealth_mode": trial_cfg.stealth_mode,
                "proxy_quota_gb": trial_cfg.proxy_quota_gb,
                "all_features_unlocked": True,
            },
        })

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
                    "proxy_quota_gb": tier_cfg.proxy_quota_gb,
                },
            })
    return result
