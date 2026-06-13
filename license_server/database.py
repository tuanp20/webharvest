"""
WebHarvest License Server — PostgreSQL Database Layer.

Uses asyncpg for async connection pooling and raw SQL for maximum control.
All settlement operations use PG transactions (no Saga needed).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger("license.database")

pool: Optional[asyncpg.Pool] = None

# ── Schema ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS license_keys (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(30) UNIQUE NOT NULL,
    tier            VARCHAR(10) NOT NULL CHECK(tier IN ('basic','pro','unlimited')),
    duration_months SMALLINT NOT NULL CHECK(duration_months IN (1,3,6,12)),
    status          VARCHAR(10) NOT NULL DEFAULT 'unused'
                    CHECK(status IN ('unused','active','expired','revoked')),
    amount_vnd      INTEGER NOT NULL DEFAULT 0,
    owner_email     VARCHAR(255),
    owner_name      VARCHAR(255),
    device_id       VARCHAR(128),
    device_name     VARCHAR(255),
    rebind_count    SMALLINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    activated_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    last_validated  TIMESTAMPTZ,
    order_code      BIGINT,
    payos_tx_id     VARCHAR(100),
    total_requests  INTEGER DEFAULT 0,
    total_urls      INTEGER DEFAULT 0,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS request_logs (
    id              SERIAL PRIMARY KEY,
    key_id          INTEGER REFERENCES license_keys(id) ON DELETE SET NULL,
    action          VARCHAR(20) NOT NULL,
    url             TEXT,
    status          VARCHAR(20),
    error_message   TEXT,
    ip_address      VARCHAR(45),
    device_id       VARCHAR(128),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_usage (
    id              SERIAL PRIMARY KEY,
    key_id          INTEGER REFERENCES license_keys(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    urls_crawled    INTEGER DEFAULT 0,
    requests_count  INTEGER DEFAULT 0,
    UNIQUE(key_id, date)
);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id              SERIAL PRIMARY KEY,
    order_code      BIGINT UNIQUE NOT NULL,
    amount          INTEGER NOT NULL,
    tier            VARCHAR(10) NOT NULL,
    duration_months SMALLINT NOT NULL,
    status          VARCHAR(12) DEFAULT 'pending'
                    CHECK(status IN ('pending','paid','cancelled')),
    buyer_email     VARCHAR(255),
    buyer_name      VARCHAR(255),
    device_id       VARCHAR(128),
    checkout_url    TEXT,
    payos_tx_id     VARCHAR(100),
    webhook_payload JSONB,
    key_id          INTEGER REFERENCES license_keys(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_keys_status ON license_keys(status);
CREATE INDEX IF NOT EXISTS idx_keys_device ON license_keys(device_id);
CREATE INDEX IF NOT EXISTS idx_keys_expires ON license_keys(expires_at);
CREATE INDEX IF NOT EXISTS idx_logs_key_date ON request_logs(key_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_created ON request_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_key_date ON daily_usage(key_id, date);
CREATE INDEX IF NOT EXISTS idx_tx_status ON payment_transactions(status);
CREATE INDEX IF NOT EXISTS idx_tx_created ON payment_transactions(created_at DESC);
"""


async def init_db(database_url: str) -> None:
    """Initialize connection pool and create tables."""
    global pool
    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database initialized")


async def close_db() -> None:
    """Close connection pool."""
    global pool
    if pool:
        await pool.close()
        pool = None


# ── License Key CRUD ──────────────────────────────────────────────────────

async def create_key(
    key: str, tier: str, duration_months: int, amount_vnd: int = 0,
    order_code: int = None, owner_email: str = None, owner_name: str = None,
    note: str = None,
) -> dict:
    """Insert a new license key (status='unused')."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO license_keys
               (key, tier, duration_months, amount_vnd, order_code, owner_email, owner_name, note)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING *""",
            key, tier, duration_months, amount_vnd, order_code, owner_email, owner_name, note,
        )
        return dict(row)


async def activate_key(key: str, device_id: str, device_name: str = None) -> dict | None:
    """Activate an unused key and bind it to a device. Returns updated row or None."""
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1", key
        )
        if not row:
            return None

        if row["status"] == "active":
            # Already active — check device match
            if row["device_id"] == device_id:
                return dict(row)  # Same device, return info
            return None  # Different device

        if row["status"] != "unused":
            return None  # expired or revoked

        expires_at = now + timedelta(days=30 * row["duration_months"])
        updated = await conn.fetchrow(
            """UPDATE license_keys
               SET status='active', device_id=$2, device_name=$3,
                   activated_at=$4, expires_at=$5, last_validated=$4
               WHERE key=$1 AND status='unused'
               RETURNING *""",
            key, device_id, device_name, now, expires_at,
        )
        return dict(updated) if updated else None


async def validate_key(key: str, device_id: str) -> dict | None:
    """Validate a key + device combo. Returns key row if valid, None otherwise."""
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row:
            return None
        if row["device_id"] != device_id:
            return None
        if row["expires_at"] and row["expires_at"] < now:
            # Auto-expire
            await conn.execute(
                "UPDATE license_keys SET status='expired' WHERE id=$1", row["id"]
            )
            return None

        # Update last_validated and increment total_requests
        await conn.execute(
            "UPDATE license_keys SET last_validated=$2, total_requests=total_requests+1 WHERE id=$1",
            row["id"], now,
        )
        return dict(row)


async def rebind_key(key: str, new_device_id: str, new_device_name: str = None) -> dict | None:
    """Rebind a key to a new device (max MAX_REBINDS times)."""
    from .config import MAX_REBINDS
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row:
            return None
        if row["rebind_count"] >= MAX_REBINDS:
            return None  # Exceeded rebind limit
        updated = await conn.fetchrow(
            """UPDATE license_keys
               SET device_id=$2, device_name=$3, rebind_count=rebind_count+1
               WHERE key=$1 AND status='active'
               RETURNING *""",
            key, new_device_id, new_device_name,
        )
        return dict(updated) if updated else None


async def revoke_key(key: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE license_keys SET status='revoked' WHERE key=$1 AND status IN ('active','unused')",
            key,
        )
        return result == "UPDATE 1"


async def extend_key(key: str, extra_months: int) -> dict | None:
    """Extend an active key's expiration by extra_months."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row or not row["expires_at"]:
            return None
        base = max(row["expires_at"], datetime.now(timezone.utc))
        new_expires = base + timedelta(days=30 * extra_months)
        updated = await conn.fetchrow(
            "UPDATE license_keys SET expires_at=$2 WHERE id=$1 RETURNING *",
            row["id"], new_expires,
        )
        return dict(updated) if updated else None


async def get_key_by_key(key: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM license_keys WHERE key=$1", key)
        return dict(row) if row else None


async def get_key_by_device(device_id: str) -> dict | None:
    """Find active key bound to a device."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE device_id=$1 AND status='active' ORDER BY expires_at DESC LIMIT 1",
            device_id,
        )
        return dict(row) if row else None


async def get_all_keys(
    status: str = None, tier: str = None, search: str = None,
    page: int = 1, limit: int = 50,
) -> tuple[list[dict], int]:
    """List keys with filters, pagination. Returns (rows, total_count)."""
    conditions = []
    params = []
    idx = 1

    if status:
        conditions.append(f"status=${idx}")
        params.append(status)
        idx += 1
    if tier:
        conditions.append(f"tier=${idx}")
        params.append(tier)
        idx += 1
    if search:
        conditions.append(f"(key ILIKE ${idx} OR owner_email ILIKE ${idx} OR device_id ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * limit

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM license_keys {where}", *params)
        rows = await conn.fetch(
            f"SELECT * FROM license_keys {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params, limit, offset,
        )
        return [dict(r) for r in rows], total


async def auto_expire_keys() -> int:
    """Mark expired keys. Returns count of newly expired keys."""
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE license_keys SET status='expired' WHERE status='active' AND expires_at < $1",
            now,
        )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.info("Auto-expired %d keys", count)
        return count


# ── Daily Usage ───────────────────────────────────────────────────────────

async def get_daily_usage(key_id: int, date: str = None) -> int:
    """Get URLs crawled today for a key."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT urls_crawled FROM daily_usage WHERE key_id=$1 AND date=$2",
            key_id, date,
        )
        return val or 0


async def increment_daily_usage(key_id: int, urls: int = 1) -> int:
    """Increment daily URL counter. Returns new total."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO daily_usage (key_id, date, urls_crawled, requests_count)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (key_id, date)
               DO UPDATE SET urls_crawled = daily_usage.urls_crawled + $3,
                             requests_count = daily_usage.requests_count + 1
               RETURNING urls_crawled""",
            key_id, today, urls,
        )
        return row["urls_crawled"]


# ── Request Logs ──────────────────────────────────────────────────────────

async def log_request(
    key_id: int = None, action: str = "", url: str = None,
    status: str = None, error_message: str = None,
    ip_address: str = None, device_id: str = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO request_logs (key_id, action, url, status, error_message, ip_address, device_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            key_id, action, url, status, error_message, ip_address, device_id,
        )


async def get_request_logs(
    key_id: int = None, status: str = None,
    date_from: str = None, date_to: str = None,
    page: int = 1, limit: int = 50,
) -> tuple[list[dict], int]:
    conditions = []
    params = []
    idx = 1

    if key_id:
        conditions.append(f"r.key_id=${idx}")
        params.append(key_id)
        idx += 1
    if status:
        conditions.append(f"r.status=${idx}")
        params.append(status)
        idx += 1
    if date_from:
        conditions.append(f"r.created_at >= ${idx}::timestamptz")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"r.created_at <= ${idx}::timestamptz")
        params.append(date_to + "T23:59:59Z")
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * limit

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM request_logs r {where}", *params
        )
        rows = await conn.fetch(
            f"""SELECT r.*, lk.key as license_key, lk.tier
                FROM request_logs r
                LEFT JOIN license_keys lk ON r.key_id = lk.id
                {where}
                ORDER BY r.created_at DESC
                LIMIT ${idx} OFFSET ${idx+1}""",
            *params, limit, offset,
        )
        return [dict(r) for r in rows], total


# ── Payment Transactions ─────────────────────────────────────────────────

async def create_transaction(
    order_code: int, amount: int, tier: str, duration_months: int,
    device_id: str = None, buyer_email: str = None, buyer_name: str = None,
    checkout_url: str = None,
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO payment_transactions
               (order_code, amount, tier, duration_months, device_id, buyer_email, buyer_name, checkout_url)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING *""",
            order_code, amount, tier, duration_months, device_id, buyer_email, buyer_name, checkout_url,
        )
        return dict(row)


async def settle_payment(order_code: int, payos_data: dict, generated_key: str) -> dict | None:
    """Atomically mark payment as paid and create license key.

    Single PG transaction — no Saga needed.
    Idempotent: returns None if already paid.
    """
    from .config import get_price
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Lock and update transaction
            tx = await conn.fetchrow(
                """UPDATE payment_transactions
                   SET status='paid', payos_tx_id=$2, webhook_payload=$3::jsonb, updated_at=$4
                   WHERE order_code=$1 AND status='pending'
                   RETURNING *""",
                order_code, payos_data.get("reference", ""), 
                __import__("json").dumps(payos_data), now,
            )
            if not tx:
                return None  # Already paid or not found — idempotent

            # 2. Check if device already has an active key → extend instead
            existing = None
            if tx["device_id"]:
                existing = await conn.fetchrow(
                    "SELECT * FROM license_keys WHERE device_id=$1 AND status='active' ORDER BY expires_at DESC LIMIT 1",
                    tx["device_id"],
                )

            if existing and existing["tier"] == tx["tier"]:
                # Extend existing key
                base = max(existing["expires_at"], now)
                new_expires = base + timedelta(days=30 * tx["duration_months"])
                key_row = await conn.fetchrow(
                    """UPDATE license_keys SET expires_at=$2, amount_vnd=amount_vnd+$3
                       WHERE id=$1 RETURNING *""",
                    existing["id"], new_expires, tx["amount"],
                )
            else:
                # 3. Create new license key
                key_row = await conn.fetchrow(
                    """INSERT INTO license_keys
                       (key, tier, duration_months, amount_vnd, order_code, 
                        owner_email, owner_name, device_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                       RETURNING *""",
                    generated_key, tx["tier"], tx["duration_months"], tx["amount"],
                    order_code, tx["buyer_email"], tx["buyer_name"], tx["device_id"],
                )

            # 4. Link key to transaction
            await conn.execute(
                "UPDATE payment_transactions SET key_id=$2 WHERE order_code=$1",
                order_code, key_row["id"],
            )

            return dict(key_row)


async def get_transaction_by_order(order_code: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payment_transactions WHERE order_code=$1", order_code
        )
        return dict(row) if row else None


async def cancel_transaction(order_code: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE payment_transactions SET status='cancelled', updated_at=NOW() WHERE order_code=$1 AND status='pending'",
            order_code,
        )
        return result == "UPDATE 1"


# ── Dashboard Stats ───────────────────────────────────────────────────────

async def get_dashboard_stats(date_from: str = None, date_to: str = None) -> dict:
    """Get aggregate stats for admin dashboard."""
    async with pool.acquire() as conn:
        # Key stats
        total_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys")
        active_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys WHERE status='active'")
        expired_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys WHERE status='expired'")
        unused_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys WHERE status='unused'")

        # Unique devices
        total_devices = await conn.fetchval(
            "SELECT COUNT(DISTINCT device_id) FROM license_keys WHERE device_id IS NOT NULL"
        )

        # Tier breakdown
        tier_counts = await conn.fetch(
            "SELECT tier, COUNT(*) as count FROM license_keys WHERE status='active' GROUP BY tier"
        )

        # Revenue
        revenue_conditions = ["status='paid'"]
        rev_params = []
        idx = 1
        if date_from:
            revenue_conditions.append(f"created_at >= ${idx}::timestamptz")
            rev_params.append(date_from)
            idx += 1
        if date_to:
            revenue_conditions.append(f"created_at <= ${idx}::timestamptz")
            rev_params.append(date_to + "T23:59:59Z")
            idx += 1

        rev_where = " AND ".join(revenue_conditions)
        total_revenue = await conn.fetchval(
            f"SELECT COALESCE(SUM(amount), 0) FROM payment_transactions WHERE {rev_where}",
            *rev_params,
        )
        total_transactions = await conn.fetchval(
            f"SELECT COUNT(*) FROM payment_transactions WHERE {rev_where}",
            *rev_params,
        )

        # Request stats
        total_requests = await conn.fetchval("SELECT COUNT(*) FROM request_logs")
        error_requests = await conn.fetchval(
            "SELECT COUNT(*) FROM request_logs WHERE status='error'"
        )

        return {
            "keys": {
                "total": total_keys, "active": active_keys,
                "expired": expired_keys, "unused": unused_keys,
            },
            "devices": total_devices,
            "tiers": {r["tier"]: r["count"] for r in tier_counts},
            "revenue": {
                "total_vnd": total_revenue,
                "total_transactions": total_transactions,
            },
            "requests": {
                "total": total_requests,
                "errors": error_requests,
            },
        }


async def get_revenue_report(group_by: str = "day", date_from: str = None, date_to: str = None) -> list[dict]:
    """Revenue grouped by day or month."""
    if group_by == "month":
        date_trunc = "month"
    else:
        date_trunc = "day"

    conditions = ["status='paid'"]
    params = []
    idx = 1
    if date_from:
        conditions.append(f"created_at >= ${idx}::timestamptz")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"created_at <= ${idx}::timestamptz")
        params.append(date_to + "T23:59:59Z")
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT DATE_TRUNC('{date_trunc}', created_at) as period,
                       SUM(amount) as revenue,
                       COUNT(*) as transactions,
                       tier
                FROM payment_transactions
                WHERE {where}
                GROUP BY period, tier
                ORDER BY period DESC""",
            *params,
        )
        return [dict(r) for r in rows]
