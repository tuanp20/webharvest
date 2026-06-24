"""
WebHarvest License Server — Key Generation & Validation.

Handles cryptographic key generation, device fingerprinting, and tier enforcement.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# Key alphabet: uppercase letters + digits, excluding ambiguous chars (0/O, 1/I/L)
_KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_KEY_GROUP_LEN = 5
_KEY_GROUPS = 4
_KEY_PREFIX = "WH"


def generate_key() -> str:
    """Generate a cryptographically secure license key.

    Format: WH-XXXXX-XXXXX-XXXXX-XXXXX
    Uses secrets module for cryptographic randomness.
    Alphabet excludes ambiguous characters (0/O, 1/I/L) for readability.
    """
    groups = []
    for _ in range(_KEY_GROUPS):
        group = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_GROUP_LEN))
        groups.append(group)
    return f"{_KEY_PREFIX}-" + "-".join(groups)


def is_valid_key_format(key: str) -> bool:
    """Check if a string matches the WH-XXXXX-XXXXX-XXXXX-XXXXX format."""
    if not key or not isinstance(key, str):
        return False
    parts = key.split("-")
    if len(parts) != _KEY_GROUPS + 1:
        return False
    if parts[0] != _KEY_PREFIX:
        return False
    for part in parts[1:]:
        if len(part) != _KEY_GROUP_LEN:
            return False
        if not all(c in _KEY_ALPHABET for c in part):
            return False
    return True


@dataclass
class ValidationResult:
    """Result of a license key validation check."""
    valid: bool
    error: Optional[str] = None
    error_code: Optional[str] = None
    tier: Optional[str] = None
    tier_name: Optional[str] = None
    expires_at: Optional[str] = None
    max_daily_urls: int = 0
    max_concurrent: int = 0
    batch_crawl: bool = False
    stealth_mode: bool = False
    proxy_quota_gb: float = 0
    allowed_fetchers: list = None
    daily_urls_used: int = 0
    daily_urls_remaining: int = 0

    # Trial-specific fields
    is_trial: bool = False
    trial_remaining: int = 0
    trial_total: int = 0

    def __post_init__(self):
        if self.allowed_fetchers is None:
            self.allowed_fetchers = []

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "error": self.error,
            "error_code": self.error_code,
            "tier": self.tier,
            "tier_name": self.tier_name,
            "expires_at": self.expires_at,
            "limits": {
                "max_daily_urls": self.max_daily_urls,
                "max_concurrent": self.max_concurrent,
                "batch_crawl": self.batch_crawl,
                "stealth_mode": self.stealth_mode,
                "proxy_quota_gb": self.proxy_quota_gb,
                "allowed_fetchers": self.allowed_fetchers,
                "daily_urls_used": self.daily_urls_used,
                "daily_urls_remaining": self.daily_urls_remaining,
                "is_trial": self.is_trial,
                "trial_remaining": self.trial_remaining,
                "trial_total": self.trial_total,
            },
        }


def generate_order_code() -> int:
    """Generate a unique order code for PayOS (same approach as xuongmedia)."""
    import time
    timestamp_part = int(time.time() * 1000) % 10_000_000_000
    random_part = secrets.randbelow(90_000) + 10_000
    order_code = int(f"{timestamp_part}{random_part}")
    if order_code > 9_007_199_254_740_991:  # Number.MAX_SAFE_INTEGER
        return timestamp_part
    return order_code
