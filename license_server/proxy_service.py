"""
WebHarvest License Server — DataImpulse Proxy Service.

Manages proxy sessions via DataImpulse residential proxy gateway.
Provides centralized proxy allocation with bandwidth quota tracking per license tier.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Dict

logger = logging.getLogger("license.proxy_service")

# ── DataImpulse Gateway ───────────────────────────────────────────────────

DI_HOST = "gw.dataimpulse.com"
DI_PORT_HTTP = 823
DI_PORT_SOCKS5 = 824


@dataclass
class ProxySession:
    """Represents an active proxy session allocated to a client."""
    session_id: str
    proxy_url: str
    license_key: str
    tier: str
    target_domain: str
    acquired_at: datetime
    ttl_seconds: int
    quota_remaining_bytes: int


@dataclass
class ProxyQuotaInfo:
    """Bandwidth quota information for a license key."""
    quota_bytes: int          # Total quota in bytes for current month
    used_bytes: int           # Bytes used this month
    remaining_bytes: int      # Bytes remaining
    quota_gb: float           # Total in GB (human readable)
    used_gb: float            # Used in GB
    remaining_gb: float       # Remaining in GB
    month: str                # YYYY-MM


# ── In-memory session store (for mock mode) ───────────────────────────────

_active_sessions: Dict[str, dict] = {}


class DataImpulseProxyService:
    """
    Proxy service that integrates with DataImpulse residential proxy gateway.
    
    Architecture:
    - Admin configures DI credentials in server .env
    - Client calls acquire() before crawling → gets a proxy URL
    - Client calls release() after crawling → reports bandwidth usage
    - Service tracks bandwidth per license key per month (quota enforcement)
    """

    def __init__(self, username: str, password: str, default_country: str = ""):
        self.username = username
        self.password = password
        self.default_country = default_country
        self._configured = bool(username and password)
        if self._configured:
            logger.info("DataImpulse proxy service initialized (user=%s)", username)
        else:
            logger.warning("DataImpulse credentials not configured — proxy service disabled")

    @property
    def is_configured(self) -> bool:
        return self._configured

    def build_proxy_url(self, country: str = "", sticky_session: str = "") -> str:
        """
        Build a DataImpulse proxy URL with optional targeting parameters.
        
        Format: http://username[__cr.XX][__ses.ID]:password@gw.dataimpulse.com:823
        """
        parts = [self.username]
        
        # Country targeting
        target_country = country or self.default_country
        if target_country:
            parts.append(f"cr.{target_country}")
        
        # Sticky session (keeps same IP for duration)
        if sticky_session:
            parts.append(f"ses.{sticky_session}")
        
        auth_user = "__".join(parts)
        return f"http://{auth_user}:{self.password}@{DI_HOST}:{DI_PORT_HTTP}"

    async def acquire_session(
        self,
        license_key: str,
        tier: str,
        target_url: str = "",
        country: str = "",
        db_module=None,
    ) -> Optional[ProxySession]:
        """
        Acquire a proxy session for a crawl request.
        
        Flow:
        1. Check if DataImpulse is configured
        2. Check bandwidth quota for the license key
        3. Generate proxy URL with optional targeting
        4. Create session record
        5. Return ProxySession
        """
        if not self._configured:
            logger.debug("Proxy service not configured, returning None (will fallback to local IP)")
            return None

        # Import tier config
        from .config import TIERS
        tier_cfg = TIERS.get(tier)
        if not tier_cfg:
            logger.warning("Unknown tier '%s' for proxy allocation", tier)
            return None

        # Check bandwidth quota
        if db_module:
            quota_info = await self._get_quota_info(license_key, tier, db_module)
            if quota_info and quota_info.remaining_bytes <= 0:
                logger.info("Proxy bandwidth quota exhausted for key=%s (used %.2f GB / %.2f GB)",
                            license_key[:10], quota_info.used_gb, quota_info.quota_gb)
                return None
            remaining = quota_info.remaining_bytes if quota_info else tier_cfg.proxy_quota_gb * 1_073_741_824
        else:
            remaining = int(tier_cfg.proxy_quota_gb * 1_073_741_824)

        # Extract domain from URL for logging
        target_domain = ""
        if target_url:
            try:
                from urllib.parse import urlparse
                target_domain = urlparse(target_url).netloc
            except Exception:
                target_domain = target_url[:50]

        now = datetime.now(timezone.utc)

        # Look for existing active session to reuse (cache hit)
        cached_session_id = None
        for s_id, s in list(_active_sessions.items()):
            # Clean up expired session if TTL has elapsed
            elapsed = (now - s["acquired_at"]).total_seconds()
            if elapsed >= tier_cfg.proxy_session_ttl:
                _active_sessions.pop(s_id, None)
                continue
            
            if s["license_key"] == license_key and s["target_domain"] == target_domain and s.get("country", "") == country:
                cached_session_id = s_id
                break

        if cached_session_id:
            s = _active_sessions[cached_session_id]
            logger.info("Server-side proxy acquisition cache HIT: reusing session=%s key=%s domain=%s country=%s",
                        cached_session_id[:8], license_key[:10], target_domain, country)
            return ProxySession(
                session_id=cached_session_id,
                proxy_url=s["proxy_url"],
                license_key=license_key,
                tier=tier,
                target_domain=target_domain,
                acquired_at=s["acquired_at"],
                ttl_seconds=tier_cfg.proxy_session_ttl,
                quota_remaining_bytes=int(remaining),
            )

        # Check concurrent sessions limit (only for cache miss)
        active_count = sum(1 for s in _active_sessions.values() if s["license_key"] == license_key)
        if active_count >= tier_cfg.max_concurrent_proxy:
            logger.info("Max concurrent proxy sessions reached for key=%s (%d/%d)",
                        license_key[:10], active_count, tier_cfg.max_concurrent_proxy)
            return None

        # Generate session
        session_id = str(uuid.uuid4())
        
        # Use sticky session for Pro/Unlimited tiers
        sticky = session_id[:8] if tier in ("pro", "unlimited") else ""
        proxy_url = self.build_proxy_url(country=country, sticky_session=sticky)

        session = ProxySession(
            session_id=session_id,
            proxy_url=proxy_url,
            license_key=license_key,
            tier=tier,
            target_domain=target_domain,
            acquired_at=now,
            ttl_seconds=tier_cfg.proxy_session_ttl,
            quota_remaining_bytes=remaining,
        )

        # Store in memory
        _active_sessions[session_id] = {
            "session_id": session_id,
            "license_key": license_key,
            "tier": tier,
            "target_domain": target_domain,
            "acquired_at": now,
            "proxy_url": proxy_url,
            "country": country,
        }

        # Store in DB
        if db_module:
            try:
                await db_module.create_proxy_session(
                    session_id=session_id,
                    license_key=license_key,
                    target_domain=target_domain,
                )
            except Exception as e:
                logger.warning("Failed to persist proxy session: %s", e)

        logger.info("Proxy session acquired: session=%s key=%s domain=%s",
                     session_id[:8], license_key[:10], target_domain)

        return session

    async def release_session(
        self,
        session_id: str,
        bytes_used: int = 0,
        status: str = "success",
        db_module=None,
    ) -> bool:
        """
        Release a proxy session and report bandwidth usage.
        
        Args:
            session_id: The session ID returned from acquire_session
            bytes_used: Number of bytes transferred through the proxy
            status: 'success', 'fail', 'timeout', 'blocked'
        """
        session_data = _active_sessions.pop(session_id, None)

        if db_module:
            try:
                await db_module.update_proxy_session(
                    session_id=session_id,
                    bytes_used=bytes_used,
                    status=status,
                )
                # Increment bandwidth usage
                if bytes_used > 0 and session_data:
                    await db_module.increment_bandwidth(
                        license_key=session_data["license_key"],
                        bytes_used=bytes_used,
                    )
            except Exception as e:
                logger.warning("Failed to update proxy session: %s", e)

        logger.info("Proxy session released: session=%s bytes=%d status=%s",
                     session_id[:8], bytes_used, status)
        return True

    async def get_quota(
        self,
        license_key: str,
        tier: str,
        db_module=None,
    ) -> ProxyQuotaInfo:
        """Get bandwidth quota information for a license key."""
        return await self._get_quota_info(license_key, tier, db_module)

    async def _get_quota_info(
        self,
        license_key: str,
        tier: str,
        db_module=None,
    ) -> ProxyQuotaInfo:
        """Internal: calculate quota info from DB or defaults."""
        from .config import TIERS
        tier_cfg = TIERS.get(tier)
        quota_gb = tier_cfg.proxy_quota_gb if tier_cfg else 1.0
        quota_bytes = int(quota_gb * 1_073_741_824)  # GB to bytes

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        used_bytes = 0

        if db_module:
            try:
                used_bytes = await db_module.get_bandwidth_usage(license_key, month)
            except Exception as e:
                logger.warning("Failed to get bandwidth usage: %s", e)

        remaining = max(0, quota_bytes - used_bytes)
        return ProxyQuotaInfo(
            quota_bytes=quota_bytes,
            used_bytes=used_bytes,
            remaining_bytes=remaining,
            quota_gb=quota_gb,
            used_gb=round(used_bytes / 1_073_741_824, 3),
            remaining_gb=round(remaining / 1_073_741_824, 3),
            month=month,
        )

    async def get_admin_stats(self, db_module=None) -> dict:
        """Get proxy system statistics for admin dashboard."""
        active_sessions = len(_active_sessions)
        
        stats = {
            "configured": self._configured,
            "di_username": self.username if self._configured else None,
            "active_sessions": active_sessions,
            "total_sessions": 0,
            "total_bytes_used": 0,
            "total_bytes_gb": 0.0,
        }

        if db_module:
            try:
                db_stats = await db_module.get_proxy_stats()
                stats.update(db_stats)
            except Exception as e:
                logger.warning("Failed to get proxy stats: %s", e)

        return stats
