"""
WebHarvest License Server — PostgreSQL Database Layer with in-memory mock fallback.

Uses asyncpg for async connection pooling.
If DATABASE_URL is not set, contains 'mock', or connection fails, falls back automatically
to an in-memory mock store so the license server & admin dashboard can be tested offline.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger("license.database")

pool: Optional[asyncpg.Pool] = None
is_mock = False

# In-memory mock database stores
_mock_keys: Dict[int, dict] = {}
_mock_key_by_str: Dict[str, dict] = {}
_mock_logs: List[dict] = []
_mock_daily_usage: Dict[str, int] = {}  # "key_id:date" -> urls_crawled
_mock_tx: Dict[int, dict] = {}  # order_code -> tx_dict
_mock_proxy_sessions: Dict[str, dict] = {}  # session_id -> session_dict
_mock_bandwidth: Dict[str, int] = {}  # "key:month" -> bytes_used

_key_id_seq = 1
_log_id_seq = 1
_tx_id_seq = 1


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

CREATE TABLE IF NOT EXISTS proxy_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(50) UNIQUE NOT NULL,
    license_key     VARCHAR(30) NOT NULL,
    target_domain   VARCHAR(255),
    bytes_used      BIGINT DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'active'
                    CHECK(status IN ('active','success','fail','timeout','blocked')),
    acquired_at     TIMESTAMPTZ DEFAULT NOW(),
    released_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bandwidth_usage (
    id              SERIAL PRIMARY KEY,
    license_key     VARCHAR(30) NOT NULL,
    month           VARCHAR(7) NOT NULL,
    bytes_used      BIGINT DEFAULT 0,
    UNIQUE(license_key, month)
);

CREATE INDEX IF NOT EXISTS idx_proxy_sessions_key ON proxy_sessions(license_key);
CREATE INDEX IF NOT EXISTS idx_proxy_sessions_status ON proxy_sessions(status);
CREATE INDEX IF NOT EXISTS idx_bandwidth_key_month ON bandwidth_usage(license_key, month);
"""


async def init_db(database_url: str) -> None:
    """Initialize connection pool or switch to Mock DB if database_url is empty/mock."""
    global pool, is_mock
    if not database_url or "mock" in database_url.lower():
        is_mock = True
        logger.warning("No database URL configured or using 'mock'. ENABLING IN-MEMORY DATABASE FALLBACK.")
        _setup_mock_data()
        return

    try:
        pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        logger.info("Database initialized successfully (PostgreSQL)")
    except Exception as e:
        logger.error("Failed to connect to PostgreSQL: %s. ENABLING IN-MEMORY DATABASE FALLBACK.", e)
        is_mock = True
        _setup_mock_data()


def _setup_mock_data():
    """Seed initial data into the mock database for demonstration purposes."""
    global _key_id_seq
    now = datetime.now(timezone.utc)

    # Key 1: Unused Basic
    k1 = {
        "id": 1, "key": "WH-ABCDE-23456-FGHJK-78923", "tier": "basic", "duration_months": 1,
        "status": "unused", "amount_vnd": 99000, "owner_email": "demo@webharvest.vn", "owner_name": "Nguyen Van A",
        "device_id": None, "device_name": None, "rebind_count": 0, "created_at": now - timedelta(days=2),
        "activated_at": None, "expires_at": None, "last_validated": None, "order_code": 10001,
        "payos_tx_id": "tx_abc123", "total_requests": 0, "total_urls": 0, "note": "Demo Unused Key",
    }
    _mock_keys[1] = k1
    _mock_key_by_str[k1["key"]] = k1

    # Key 2: Active Pro
    k2 = {
        "id": 2, "key": "WH-PR2XX-99999-XXXXX-22222", "tier": "pro", "duration_months": 3,
        "status": "active", "amount_vnd": 1347300, "owner_email": "pro@webharvest.vn", "owner_name": "Tran Van B",
        "device_id": "test_device_fingerprint_id", "device_name": "Windows PC / Chrome", "rebind_count": 0,
        "created_at": now - timedelta(days=30), "activated_at": now - timedelta(days=29),
        "expires_at": now + timedelta(days=61), "last_validated": now - timedelta(minutes=5),
        "order_code": 10002, "payos_tx_id": "tx_def456", "total_requests": 150, "total_urls": 2800,
        "note": "Demo Active Pro Key",
    }
    _mock_keys[2] = k2
    _mock_key_by_str[k2["key"]] = k2
    _mock_daily_usage["2:" + now.strftime("%Y-%m-%d")] = 145

    # Key 3: Expired Unlimited
    k3 = {
        "id": 3, "key": "WH-UN222-88888-YYYYY-33333", "tier": "unlimited", "duration_months": 1,
        "status": "expired", "amount_vnd": 899000, "owner_email": "expired@webharvest.vn", "owner_name": "Le Van C",
        "device_id": "old_laptop_id", "device_name": "Macbook Air", "rebind_count": 1,
        "created_at": now - timedelta(days=40), "activated_at": now - timedelta(days=40),
        "expires_at": now - timedelta(days=10), "last_validated": now - timedelta(days=10),
        "order_code": 10003, "payos_tx_id": "tx_ghi789", "total_requests": 1200, "total_urls": 85000,
        "note": "Demo Expired Key",
    }
    _mock_keys[3] = k3
    _mock_key_by_str[k3["key"]] = k3

    _key_id_seq = 4

    # Seed mock transactions
    _mock_tx[10001] = {
        "id": 1, "order_code": 10001, "amount": 99000, "tier": "basic", "duration_months": 1,
        "status": "paid", "buyer_email": "demo@webharvest.vn", "buyer_name": "Nguyen Van A",
        "device_id": None, "checkout_url": "http://checkout.url/1", "payos_tx_id": "tx_abc123",
        "webhook_payload": None, "key_id": 1, "created_at": now - timedelta(days=2), "updated_at": now - timedelta(days=2)
    }
    _mock_tx[10002] = {
        "id": 2, "order_code": 10002, "amount": 1347300, "tier": "pro", "duration_months": 3,
        "status": "paid", "buyer_email": "pro@webharvest.vn", "buyer_name": "Tran Van B",
        "device_id": "test_device_fingerprint_id", "checkout_url": "http://checkout.url/2", "payos_tx_id": "tx_def456",
        "webhook_payload": None, "key_id": 2, "created_at": now - timedelta(days=30), "updated_at": now - timedelta(days=29)
    }

    # Add mock logs
    global _log_id_seq
    _mock_logs.append({
        "id": 1, "key_id": 2, "action": "crawl", "url": "https://example.com/photos", "status": "success",
        "error_message": None, "ip_address": "127.0.0.1", "device_id": "test_device_fingerprint_id", "created_at": now - timedelta(minutes=5)
    })
    _mock_logs.append({
        "id": 2, "key_id": 2, "action": "validate", "url": "", "status": "success",
        "error_message": None, "ip_address": "127.0.0.1", "device_id": "test_device_fingerprint_id", "created_at": now - timedelta(minutes=6)
    })
    _mock_logs.append({
        "id": 3, "key_id": 3, "action": "crawl", "url": "https://imgur.com/gallery", "status": "error",
        "error_message": "Key has expired", "ip_address": "192.168.1.5", "device_id": "old_laptop_id", "created_at": now - timedelta(days=10)
    })
    _log_id_seq = 4


async def close_db() -> None:
    """Close connection pool."""
    global pool, is_mock
    if is_mock:
        return
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
    global _key_id_seq, is_mock
    if is_mock:
        now = datetime.now(timezone.utc)
        row = {
            "id": _key_id_seq, "key": key, "tier": tier, "duration_months": duration_months,
            "status": "unused", "amount_vnd": amount_vnd, "owner_email": owner_email, "owner_name": owner_name,
            "device_id": None, "device_name": None, "rebind_count": 0, "created_at": now,
            "activated_at": None, "expires_at": None, "last_validated": None, "order_code": order_code,
            "payos_tx_id": None, "total_requests": 0, "total_urls": 0, "note": note
        }
        _mock_keys[_key_id_seq] = row
        _mock_key_by_str[key] = row
        _key_id_seq += 1
        return row

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
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        row = _mock_key_by_str.get(key)
        if not row:
            return None
        if row["status"] == "active":
            if row["device_id"] == device_id:
                return row
            if row["device_id"] is None:
                row["device_id"] = device_id
                row["device_name"] = device_name
                row["last_validated"] = now
                return row
            return None
        if row["status"] != "unused":
            return None

        row["status"] = "active"
        row["device_id"] = device_id
        row["device_name"] = device_name
        row["activated_at"] = now
        row["expires_at"] = now + timedelta(days=30 * row["duration_months"])
        row["last_validated"] = now
        return row

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1", key
        )
        if not row:
            return None

        if row["status"] == "active":
            # Already active — check device match
            if row["device_id"] == device_id:
                return dict(row)
            if row["device_id"] is None:
                updated = await conn.fetchrow(
                    """UPDATE license_keys
                       SET device_id=$2, device_name=$3, last_validated=$4
                       WHERE key=$1 AND status='active' AND device_id IS NULL
                       RETURNING *""",
                    key, device_id, device_name, now
                )
                return dict(updated) if updated else None
            return None

        if row["status"] != "unused":
            return None

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
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        row = _mock_key_by_str.get(key)
        if not row or row["status"] != "active":
            return None
        if row["device_id"] != device_id:
            return None
        if row["expires_at"] and row["expires_at"] < now:
            row["status"] = "expired"
            return None
        row["last_validated"] = now
        row["total_requests"] += 1
        return row

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row:
            return None
        if row["device_id"] != device_id:
            return None
        if row["expires_at"] and row["expires_at"] < now:
            await conn.execute(
                "UPDATE license_keys SET status='expired' WHERE id=$1", row["id"]
            )
            return None

        await conn.execute(
            "UPDATE license_keys SET last_validated=$2, total_requests=total_requests+1 WHERE id=$1",
            row["id"], now,
        )
        return dict(row)


async def rebind_key(key: str, new_device_id: str, new_device_name: str = None) -> dict | None:
    """Rebind a key to a new device (max MAX_REBINDS times)."""
    global is_mock
    from .config import MAX_REBINDS

    if is_mock:
        row = _mock_key_by_str.get(key)
        if not row or row["status"] != "active":
            return None
        if row["rebind_count"] >= MAX_REBINDS:
            return None
        row["device_id"] = new_device_id
        row["device_name"] = new_device_name
        row["rebind_count"] += 1
        return row

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row:
            return None
        if row["rebind_count"] >= MAX_REBINDS:
            return None
        updated = await conn.fetchrow(
            """UPDATE license_keys
               SET device_id=$2, device_name=$3, rebind_count=rebind_count+1
               WHERE key=$1 AND status='active'
               RETURNING *""",
            key, new_device_id, new_device_name,
        )
        return dict(updated) if updated else None


async def deactivate_key_device(key: str, device_id: str) -> dict | None:
    """Deactivate a key by clearing its device binding if the device matches."""
    global is_mock
    if is_mock:
        row = _mock_key_by_str.get(key)
        if not row or row["status"] != "active":
            return None
        if row["device_id"] != device_id:
            return None
        row["device_id"] = None
        row["device_name"] = None
        return row

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row:
            return None
        if row["device_id"] != device_id:
            return None

        updated = await conn.fetchrow(
            """UPDATE license_keys
               SET device_id=NULL, device_name=NULL
               WHERE key=$1 AND status='active' AND device_id=$2
               RETURNING *""",
            key, device_id
        )
        return dict(updated) if updated else None


async def revoke_key(key: str) -> bool:
    global is_mock
    if is_mock:
        row = _mock_key_by_str.get(key)
        if row and row["status"] in ("active", "unused"):
            row["status"] = "revoked"
            return True
        return False

    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE license_keys SET status='revoked' WHERE key=$1 AND status IN ('active','unused')",
            key,
        )
        return result == "UPDATE 1"


async def extend_key(key: str, extra_months: int) -> dict | None:
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        row = _mock_key_by_str.get(key)
        if not row or not row["expires_at"]:
            return None
        base = max(row["expires_at"], now)
        row["expires_at"] = base + timedelta(days=30 * extra_months)
        return row

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM license_keys WHERE key=$1 AND status='active'", key
        )
        if not row or not row["expires_at"]:
            return None
        base = max(row["expires_at"], now)
        new_expires = base + timedelta(days=30 * extra_months)
        updated = await conn.fetchrow(
            "UPDATE license_keys SET expires_at=$2 WHERE id=$1 RETURNING *",
            row["id"], new_expires,
        )
        return dict(updated) if updated else None


async def get_key_by_key(key: str) -> dict | None:
    global is_mock
    if is_mock:
        return _mock_key_by_str.get(key)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM license_keys WHERE key=$1", key)
        return dict(row) if row else None


async def get_key_by_device(device_id: str) -> dict | None:
    global is_mock
    if is_mock:
        active = [k for k in _mock_keys.values() if k["device_id"] == device_id and k["status"] == "active"]
        if active:
            active.sort(key=lambda x: x["expires_at"] or datetime.min, reverse=True)
            return active[0]
        return None

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
    global is_mock
    if is_mock:
        filtered = list(_mock_keys.values())
        if status:
            filtered = [k for k in filtered if k["status"] == status]
        if tier:
            filtered = [k for k in filtered if k["tier"] == tier]
        if search:
            search_l = search.lower()
            filtered = [k for k in filtered if (
                search_l in (k["key"] or "").lower() or
                search_l in (k["owner_email"] or "").lower() or
                search_l in (k["device_id"] or "").lower()
            )]

        filtered.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
        total = len(filtered)
        offset = (page - 1) * limit
        return filtered[offset:offset+limit], total

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
        # Handle index positioning for limit and offset
        rows = await conn.fetch(
            f"SELECT * FROM license_keys {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params, limit, offset,
        )
        return [dict(r) for r in rows], total


async def auto_expire_keys() -> int:
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        expired_count = 0
        for k in _mock_keys.values():
            if k["status"] == "active" and k["expires_at"] and k["expires_at"] < now:
                k["status"] = "expired"
                expired_count += 1
        return expired_count

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
    global is_mock
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if is_mock:
        return _mock_daily_usage.get(f"{key_id}:{date}", 0)

    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT urls_crawled FROM daily_usage WHERE key_id=$1 AND date=$2",
            key_id, date,
        )
        return val or 0


async def increment_daily_usage(key_id: int, urls: int = 1) -> int:
    global is_mock
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if is_mock:
        ck = f"{key_id}:{today}"
        current = _mock_daily_usage.get(ck, 0)
        _mock_daily_usage[ck] = current + urls
        # Increment total urls on key
        key_row = _mock_keys.get(key_id)
        if key_row:
            key_row["total_urls"] = key_row.get("total_urls", 0) + urls
        return _mock_daily_usage[ck]

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
    global is_mock, _log_id_seq
    if is_mock:
        log_entry = {
            "id": _log_id_seq, "key_id": key_id, "action": action, "url": url, "status": status,
            "error_message": error_message, "ip_address": ip_address, "device_id": device_id,
            "created_at": datetime.now(timezone.utc)
        }
        _mock_logs.append(log_entry)
        _log_id_seq += 1
        return

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
    global is_mock
    if is_mock:
        filtered = _mock_logs
        if key_id:
            filtered = [l for l in filtered if l["key_id"] == key_id]
        if status:
            filtered = [l for l in filtered if l["status"] == status]
        if date_from:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            filtered = [l for l in filtered if l["created_at"] >= df]
        if date_to:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00") + "T23:59:59+00:00")
            filtered = [l for l in filtered if l["created_at"] <= dt]

        filtered.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)

        # Map details
        result_logs = []
        for l in filtered:
            k = _mock_keys.get(l["key_id"]) if l["key_id"] else None
            result_logs.append({
                **l,
                "license_key": k["key"] if k else None,
                "tier": k["tier"] if k else None
            })

        total = len(result_logs)
        offset = (page - 1) * limit
        return result_logs[offset:offset+limit], total

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
    global is_mock, _tx_id_seq
    if is_mock:
        now = datetime.now(timezone.utc)
        tx = {
            "id": _tx_id_seq, "order_code": order_code, "amount": amount, "tier": tier,
            "duration_months": duration_months, "status": "pending", "buyer_email": buyer_email,
            "buyer_name": buyer_name, "device_id": device_id, "checkout_url": checkout_url,
            "payos_tx_id": None, "webhook_payload": None, "key_id": None,
            "created_at": now, "updated_at": now
        }
        _mock_tx[order_code] = tx
        _tx_id_seq += 1
        return tx

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
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        tx = _mock_tx.get(order_code)
        if not tx or tx["status"] != "pending":
            return None

        tx["status"] = "paid"
        tx["payos_tx_id"] = payos_data.get("reference", "")
        tx["webhook_payload"] = payos_data
        tx["updated_at"] = now

        # Find or create key
        existing = None
        if tx["device_id"]:
            # Find active key for device
            active = [k for k in _mock_keys.values() if k["device_id"] == tx["device_id"] and k["status"] == "active"]
            if active:
                active.sort(key=lambda x: x["expires_at"] or datetime.min, reverse=True)
                existing = active[0]

        if existing and existing["tier"] == tx["tier"]:
            # Extend existing
            base = max(existing["expires_at"] or now, now)
            existing["expires_at"] = base + timedelta(days=30 * tx["duration_months"])
            existing["amount_vnd"] += tx["amount"]
            key_row = existing
        else:
            # Create new key
            global _key_id_seq
            key_row = {
                "id": _key_id_seq, "key": generated_key, "tier": tx["tier"], "duration_months": tx["duration_months"],
                "status": "unused", "amount_vnd": tx["amount"], "owner_email": tx["buyer_email"],
                "owner_name": tx["buyer_name"], "device_id": tx["device_id"], "device_name": None,
                "rebind_count": 0, "created_at": now, "activated_at": None, "expires_at": None, "last_validated": None,
                "order_code": order_code, "payos_tx_id": tx["payos_tx_id"], "total_requests": 0, "total_urls": 0,
                "note": "Generated via checkout"
            }
            _mock_keys[_key_id_seq] = key_row
            _mock_key_by_str[generated_key] = key_row
            _key_id_seq += 1

        tx["key_id"] = key_row["id"]
        return key_row

    async with pool.acquire() as conn:
        async with conn.transaction():
            tx = await conn.fetchrow(
                """UPDATE payment_transactions
                   SET status='paid', payos_tx_id=$2, webhook_payload=$3::jsonb, updated_at=$4
                   WHERE order_code=$1 AND status='pending'
                   RETURNING *""",
                order_code, payos_data.get("reference", ""), 
                json.dumps(payos_data), now,
            )
            if not tx:
                return None

            existing = None
            if tx["device_id"]:
                existing = await conn.fetchrow(
                    "SELECT * FROM license_keys WHERE device_id=$1 AND status='active' ORDER BY expires_at DESC LIMIT 1",
                    tx["device_id"],
                )

            if existing and existing["tier"] == tx["tier"]:
                base = max(existing["expires_at"] or now, now)
                new_expires = base + timedelta(days=30 * tx["duration_months"])
                key_row = await conn.fetchrow(
                    """UPDATE license_keys SET expires_at=$2, amount_vnd=amount_vnd+$3
                       WHERE id=$1 RETURNING *""",
                    existing["id"], new_expires, tx["amount"],
                )
            else:
                key_row = await conn.fetchrow(
                    """INSERT INTO license_keys
                       (key, tier, duration_months, amount_vnd, order_code, 
                        owner_email, owner_name, device_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                       RETURNING *""",
                    generated_key, tx["tier"], tx["duration_months"], tx["amount"],
                    order_code, tx["buyer_email"], tx["buyer_name"], tx["device_id"],
                )

            await conn.execute(
                "UPDATE payment_transactions SET key_id=$2 WHERE order_code=$1",
                order_code, key_row["id"],
            )
            return dict(key_row)


async def get_transaction_by_order(order_code: int) -> dict | None:
    global is_mock
    if is_mock:
        return _mock_tx.get(order_code)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payment_transactions WHERE order_code=$1", order_code
        )
        return dict(row) if row else None


async def cancel_transaction(order_code: int) -> bool:
    global is_mock
    if is_mock:
        tx = _mock_tx.get(order_code)
        if tx and tx["status"] == "pending":
            tx["status"] = "cancelled"
            tx["updated_at"] = datetime.now(timezone.utc)
            return True
        return False

    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE payment_transactions SET status='cancelled', updated_at=NOW() WHERE order_code=$1 AND status='pending'",
            order_code,
        )
        return result == "UPDATE 1"


# ── Dashboard Stats ───────────────────────────────────────────────────────

async def get_dashboard_stats(date_from: str = None, date_to: str = None) -> dict:
    global is_mock
    if is_mock:
        keys_val = list(_mock_keys.values())
        total_keys = len(keys_val)
        active_keys = len([k for k in keys_val if k["status"] == "active"])
        expired_keys = len([k for k in keys_val if k["status"] == "expired"])
        unused_keys = len([k for k in keys_val if k["status"] == "unused"])

        total_devices = len(set([k["device_id"] for k in keys_val if k["device_id"] is not None]))

        tier_counts = {}
        for k in keys_val:
            if k["status"] == "active":
                tier_counts[k["tier"]] = tier_counts.get(k["tier"], 0) + 1

        tx_list = list(_mock_tx.values())
        total_revenue = 0
        total_transactions = 0
        for tx in tx_list:
            if tx["status"] == "paid":
                # Filter date if requested
                if date_from:
                    df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                    if tx["created_at"] < df:
                        continue
                if date_to:
                    dt = datetime.fromisoformat(date_to.replace("Z", "+00:00") + "T23:59:59+00:00")
                    if tx["created_at"] > dt:
                        continue
                total_revenue += tx["amount"]
                total_transactions += 1

        total_requests = len(_mock_logs)
        error_requests = len([l for l in _mock_logs if l["status"] == "error"])

        return {
            "keys": {
                "total": total_keys, "active": active_keys,
                "expired": expired_keys, "unused": unused_keys,
            },
            "devices": total_devices,
            "tiers": tier_counts,
            "revenue": {
                "total_vnd": total_revenue,
                "total_transactions": total_transactions,
            },
            "requests": {
                "total": total_requests,
                "errors": error_requests,
            },
        }

    async with pool.acquire() as conn:
        total_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys")
        active_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys WHERE status='active'")
        expired_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys WHERE status='expired'")
        unused_keys = await conn.fetchval("SELECT COUNT(*) FROM license_keys WHERE status='unused'")

        total_devices = await conn.fetchval(
            "SELECT COUNT(DISTINCT device_id) FROM license_keys WHERE device_id IS NOT NULL"
        )

        tier_counts = await conn.fetch(
            "SELECT tier, COUNT(*) as count FROM license_keys WHERE status='active' GROUP BY tier"
        )

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
    global is_mock
    if is_mock:
        tx_list = list(_mock_tx.values())
        report_data = {}  # (period, tier) -> {revenue, count}
        for tx in tx_list:
            if tx["status"] != "paid":
                continue
            if date_from:
                df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                if tx["created_at"] < df:
                    continue
            if date_to:
                dt = datetime.fromisoformat(date_to.replace("Z", "+00:00") + "T23:59:59+00:00")
                if tx["created_at"] > dt:
                    continue

            period_date = tx["created_at"].replace(hour=0, minute=0, second=0, microsecond=0)
            if group_by == "month":
                period_date = period_date.replace(day=1)

            period = period_date.isoformat()
            key = (period, tx["tier"])
            if key not in report_data:
                report_data[key] = {"revenue": 0, "transactions": 0}
            report_data[key]["revenue"] += tx["amount"]
            report_data[key]["transactions"] += 1

        results = []
        for (period, tier), v in report_data.items():
            results.append({
                "period": datetime.fromisoformat(period),
                "revenue": v["revenue"],
                "transactions": v["transactions"],
                "tier": tier
            })
        results.sort(key=lambda x: x["period"], reverse=True)
        return results

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


# ── Proxy Sessions & Bandwidth ───────────────────────────────────────────

async def create_proxy_session(
    session_id: str, license_key: str, target_domain: str = "",
) -> dict:
    """Create a new proxy session record."""
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        session = {
            "session_id": session_id,
            "license_key": license_key,
            "target_domain": target_domain,
            "bytes_used": 0,
            "status": "active",
            "acquired_at": now,
            "released_at": None,
        }
        _mock_proxy_sessions[session_id] = session
        return session

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO proxy_sessions (session_id, license_key, target_domain)
               VALUES ($1, $2, $3)
               RETURNING *""",
            session_id, license_key, target_domain,
        )
        return dict(row)


async def update_proxy_session(
    session_id: str, bytes_used: int = 0, status: str = "success",
) -> bool:
    """Update a proxy session with usage data and mark as released."""
    global is_mock
    now = datetime.now(timezone.utc)

    if is_mock:
        session = _mock_proxy_sessions.get(session_id)
        if session:
            session["bytes_used"] = bytes_used
            session["status"] = status
            session["released_at"] = now
            return True
        return False

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE proxy_sessions
               SET bytes_used=$2, status=$3, released_at=$4
               WHERE session_id=$1""",
            session_id, bytes_used, status, now,
        )
        return result == "UPDATE 1"


async def get_bandwidth_usage(license_key: str, month: str = None) -> int:
    """Get total bytes used by a license key for a given month."""
    global is_mock
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    if is_mock:
        return _mock_bandwidth.get(f"{license_key}:{month}", 0)

    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT bytes_used FROM bandwidth_usage WHERE license_key=$1 AND month=$2",
            license_key, month,
        )
        return val or 0


async def increment_bandwidth(license_key: str, bytes_used: int, month: str = None) -> int:
    """Increment bandwidth usage for a license key."""
    global is_mock
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    if is_mock:
        ck = f"{license_key}:{month}"
        current = _mock_bandwidth.get(ck, 0)
        _mock_bandwidth[ck] = current + bytes_used
        return _mock_bandwidth[ck]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO bandwidth_usage (license_key, month, bytes_used)
               VALUES ($1, $2, $3)
               ON CONFLICT (license_key, month)
               DO UPDATE SET bytes_used = bandwidth_usage.bytes_used + $3
               RETURNING bytes_used""",
            license_key, month, bytes_used,
        )
        return row["bytes_used"]


async def get_proxy_stats() -> dict:
    """Get aggregate proxy statistics for admin dashboard."""
    global is_mock

    if is_mock:
        sessions = list(_mock_proxy_sessions.values())
        total_sessions = len(sessions)
        active_sessions = len([s for s in sessions if s["status"] == "active"])
        total_bytes = sum(s.get("bytes_used", 0) for s in sessions)

        # Current month bandwidth
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        month_bytes = sum(v for k, v in _mock_bandwidth.items() if k.endswith(f":{month}"))

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "total_bytes_used": total_bytes,
            "total_bytes_gb": round(total_bytes / 1_073_741_824, 3),
            "month_bytes_used": month_bytes,
            "month_bytes_gb": round(month_bytes / 1_073_741_824, 3),
        }

    async with pool.acquire() as conn:
        total_sessions = await conn.fetchval("SELECT COUNT(*) FROM proxy_sessions")
        active_sessions = await conn.fetchval(
            "SELECT COUNT(*) FROM proxy_sessions WHERE status='active'"
        )
        total_bytes = await conn.fetchval(
            "SELECT COALESCE(SUM(bytes_used), 0) FROM proxy_sessions"
        )

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        month_bytes = await conn.fetchval(
            "SELECT COALESCE(SUM(bytes_used), 0) FROM bandwidth_usage WHERE month=$1",
            month,
        )

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "total_bytes_used": total_bytes,
            "total_bytes_gb": round(total_bytes / 1_073_741_824, 3),
            "month_bytes_used": month_bytes or 0,
            "month_bytes_gb": round((month_bytes or 0) / 1_073_741_824, 3),
        }


async def get_proxy_sessions(
    license_key: str = None, status: str = None,
    page: int = 1, limit: int = 50,
) -> tuple[list[dict], int]:
    """Get proxy session history with optional filters."""
    global is_mock

    if is_mock:
        filtered = list(_mock_proxy_sessions.values())
        if license_key:
            filtered = [s for s in filtered if s["license_key"] == license_key]
        if status:
            filtered = [s for s in filtered if s["status"] == status]
        filtered.sort(key=lambda x: x["acquired_at"], reverse=True)
        total = len(filtered)
        offset = (page - 1) * limit
        return filtered[offset:offset + limit], total

    conditions = []
    params = []
    idx = 1

    if license_key:
        conditions.append(f"license_key=${ idx}")
        params.append(license_key)
        idx += 1
    if status:
        conditions.append(f"status=${idx}")
        params.append(status)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * limit

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM proxy_sessions {where}", *params
        )
        rows = await conn.fetch(
            f"""SELECT * FROM proxy_sessions {where}
                ORDER BY acquired_at DESC
                LIMIT ${idx} OFFSET ${idx+1}""",
            *params, limit, offset,
        )
        return [dict(r) for r in rows], total

