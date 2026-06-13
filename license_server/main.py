"""
WebHarvest License Server — FastAPI Application.

Central API server for license key validation, PayOS payments, and admin dashboard.
Deploy on VPS; desktop apps call this server for every session.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

from . import database as db
from .config import (
    Settings, TIERS, PRICING, VALID_DURATIONS, VALID_TIERS,
    get_price, get_tier_config, tier_to_dict, packages_list, MAX_REBINDS,
)
from .license import generate_key, is_valid_key_format, ValidationResult, generate_order_code
from .payos_service import PayOSService, PayOSError

logger = logging.getLogger("license.server")

settings: Settings = None
payos: PayOSService = None

# Simple admin token store (in-memory, reset on restart)
_admin_tokens: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global settings, payos

    settings = Settings.from_env()
    await db.init_db(settings.database_url)

    payos = PayOSService(
        client_id=settings.payos_client_id,
        api_key=settings.payos_api_key,
        checksum_key=settings.payos_checksum_key,
    )

    # Confirm webhook URL with PayOS
    if settings.payos_webhook_url:
        asyncio.create_task(_confirm_webhook())

    # Start background auto-expire task
    asyncio.create_task(_auto_expire_loop())

    logger.info("License server started on %s:%d", settings.host, settings.port)
    yield

    await db.close_db()
    logger.info("License server stopped")


async def _confirm_webhook():
    try:
        await payos.confirm_webhook_url(settings.payos_webhook_url)
    except Exception as e:
        logger.warning("Webhook confirm failed: %s", e)


async def _auto_expire_loop():
    """Background task: auto-expire keys every 5 minutes."""
    while True:
        try:
            await db.auto_expire_keys()
        except Exception as e:
            logger.error("Auto-expire error: %s", e)
        await asyncio.sleep(300)


app = FastAPI(
    title="WebHarvest License Server",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for desktop apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _serialize_row(row: dict) -> dict:
    """Convert asyncpg Record values to JSON-serializable types."""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


async def _require_admin(request: Request):
    """Dependency: require valid admin token."""
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token or token not in _admin_tokens:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "webharvest-license-server", "version": "1.0.0"}


# ══════════════════════════════════════════════════════════════════════════
#  PUBLIC API — Desktop App Endpoints
# ══════════════════════════════════════════════════════════════════════════

# ── Packages ──────────────────────────────────────────────────────────────

@app.get("/api/packages")
async def list_packages():
    return {"success": True, "data": packages_list()}


# ── License Activation ───────────────────────────────────────────────────

class ActivateRequest(BaseModel):
    key: str
    device_id: str
    device_name: str = ""


@app.post("/api/license/activate")
async def activate_license(req: ActivateRequest, request: Request):
    if not is_valid_key_format(req.key):
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid key format", "error_code": "INVALID_FORMAT"})

    result = await db.activate_key(req.key, req.device_id, req.device_name)
    if not result:
        # Check why it failed
        existing = await db.get_key_by_key(req.key)
        if not existing:
            await db.log_request(action="activate", status="error", error_message="Key not found",
                                 ip_address=_get_client_ip(request), device_id=req.device_id)
            return JSONResponse(status_code=404, content={"success": False, "error": "Key not found", "error_code": "NOT_FOUND"})
        if existing["status"] == "active" and existing["device_id"] != req.device_id:
            await db.log_request(key_id=existing["id"], action="activate", status="error",
                                 error_message="Device mismatch", ip_address=_get_client_ip(request), device_id=req.device_id)
            return JSONResponse(status_code=403, content={"success": False, "error": "Key is bound to another device", "error_code": "DEVICE_MISMATCH"})
        if existing["status"] in ("expired", "revoked"):
            return JSONResponse(status_code=403, content={"success": False, "error": f"Key is {existing['status']}", "error_code": existing["status"].upper()})

    tier_cfg = get_tier_config(result["tier"])
    await db.log_request(key_id=result["id"], action="activate", status="success",
                         ip_address=_get_client_ip(request), device_id=req.device_id)

    return {
        "success": True,
        "data": {
            "key": result["key"],
            "tier": result["tier"],
            "tier_name": tier_cfg.name if tier_cfg else result["tier"],
            "status": result["status"],
            "expires_at": result["expires_at"].isoformat() if result.get("expires_at") else None,
            "limits": tier_to_dict(result["tier"]),
        },
    }


# ── License Validation ───────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    key: str
    device_id: str
    action: str = "validate"  # 'validate', 'crawl', 'batch_crawl'
    url: str = ""


@app.post("/api/license/validate")
async def validate_license(req: ValidateRequest, request: Request):
    if not is_valid_key_format(req.key):
        return JSONResponse(status_code=400, content=ValidationResult(
            valid=False, error="Invalid key format", error_code="INVALID_FORMAT"
        ).to_dict())

    key_row = await db.validate_key(req.key, req.device_id)
    if not key_row:
        existing = await db.get_key_by_key(req.key)
        error_code = "NOT_FOUND"
        error_msg = "Key not found"
        key_id = None
        if existing:
            key_id = existing["id"]
            if existing["status"] == "expired":
                error_code, error_msg = "EXPIRED", "Key has expired"
            elif existing["status"] == "revoked":
                error_code, error_msg = "REVOKED", "Key has been revoked"
            elif existing["device_id"] and existing["device_id"] != req.device_id:
                error_code, error_msg = "DEVICE_MISMATCH", "Key is bound to another device"

        await db.log_request(key_id=key_id, action=req.action, url=req.url, status="error",
                             error_message=error_msg, ip_address=_get_client_ip(request), device_id=req.device_id)
        return JSONResponse(status_code=403, content=ValidationResult(
            valid=False, error=error_msg, error_code=error_code
        ).to_dict())

    tier_cfg = get_tier_config(key_row["tier"])

    # Check daily limit
    daily_used = await db.get_daily_usage(key_row["id"])
    max_daily = tier_cfg.max_daily_urls if tier_cfg else 50

    if req.action in ("crawl", "batch_crawl") and daily_used >= max_daily:
        await db.log_request(key_id=key_row["id"], action=req.action, url=req.url, status="rate_limited",
                             error_message=f"Daily limit reached ({daily_used}/{max_daily})",
                             ip_address=_get_client_ip(request), device_id=req.device_id)
        return JSONResponse(status_code=429, content=ValidationResult(
            valid=False, error=f"Daily URL limit reached ({daily_used}/{max_daily})",
            error_code="RATE_LIMITED", tier=key_row["tier"],
            daily_urls_used=daily_used, daily_urls_remaining=0,
        ).to_dict())

    # Check batch_crawl permission
    if req.action == "batch_crawl" and tier_cfg and not tier_cfg.batch_crawl:
        await db.log_request(key_id=key_row["id"], action=req.action, url=req.url, status="error",
                             error_message="Batch crawl not available for this tier",
                             ip_address=_get_client_ip(request), device_id=req.device_id)
        return JSONResponse(status_code=403, content=ValidationResult(
            valid=False, error="Batch crawl requires Pro or Unlimited tier",
            error_code="TIER_RESTRICTED", tier=key_row["tier"],
        ).to_dict())

    # Increment usage if it's a crawl action
    if req.action in ("crawl", "batch_crawl"):
        await db.increment_daily_usage(key_row["id"], urls=1)

    await db.log_request(key_id=key_row["id"], action=req.action, url=req.url, status="success",
                         ip_address=_get_client_ip(request), device_id=req.device_id)

    return ValidationResult(
        valid=True, tier=key_row["tier"],
        tier_name=tier_cfg.name if tier_cfg else key_row["tier"],
        expires_at=key_row["expires_at"].isoformat() if key_row.get("expires_at") else None,
        max_daily_urls=max_daily,
        max_concurrent=tier_cfg.max_concurrent if tier_cfg else 1,
        batch_crawl=tier_cfg.batch_crawl if tier_cfg else False,
        stealth_mode=tier_cfg.stealth_mode if tier_cfg else False,
        proxy_support=tier_cfg.proxy_support if tier_cfg else False,
        allowed_fetchers=tier_cfg.allowed_fetchers if tier_cfg else ["static"],
        daily_urls_used=daily_used,
        daily_urls_remaining=max(0, max_daily - daily_used),
    ).to_dict()


# ── License Info ──────────────────────────────────────────────────────────

@app.get("/api/license/info")
async def license_info(key: str = Query(...)):
    key_row = await db.get_key_by_key(key)
    if not key_row:
        raise HTTPException(status_code=404, detail="Key not found")
    tier_cfg = get_tier_config(key_row["tier"])
    daily_used = await db.get_daily_usage(key_row["id"]) if key_row["status"] == "active" else 0
    return {
        "success": True,
        "data": {
            **_serialize_row(key_row),
            "tier_name": tier_cfg.name if tier_cfg else key_row["tier"],
            "limits": tier_to_dict(key_row["tier"]),
            "daily_urls_used": daily_used,
        },
    }


# ── Device Rebinding ─────────────────────────────────────────────────────

class RebindRequest(BaseModel):
    key: str
    new_device_id: str
    new_device_name: str = ""


@app.post("/api/license/rebind")
async def rebind_license(req: RebindRequest, request: Request):
    result = await db.rebind_key(req.key, req.new_device_id, req.new_device_name)
    if not result:
        existing = await db.get_key_by_key(req.key)
        if existing and existing["rebind_count"] >= MAX_REBINDS:
            return JSONResponse(status_code=403, content={
                "success": False,
                "error": f"Rebind limit reached ({MAX_REBINDS}). Contact admin.",
                "error_code": "REBIND_LIMIT",
            })
        raise HTTPException(status_code=404, detail="Key not found or not active")

    return {"success": True, "data": _serialize_row(result)}


# ══════════════════════════════════════════════════════════════════════════
#  PAYMENT API — PayOS Integration
# ══════════════════════════════════════════════════════════════════════════

class CreatePaymentRequest(BaseModel):
    tier: str
    duration_months: int
    device_id: str = ""
    buyer_email: str = ""
    buyer_name: str = ""
    return_url: str = ""
    cancel_url: str = ""


@app.post("/api/payments/create-link")
async def create_payment_link(req: CreatePaymentRequest):
    if req.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {req.tier}")
    if req.duration_months not in VALID_DURATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid duration: {req.duration_months}")

    price = get_price(req.tier, req.duration_months)
    if not price:
        raise HTTPException(status_code=400, detail="Invalid tier/duration combination")

    order_code = generate_order_code()
    description = f"WebHarvest {TIERS[req.tier].name}"

    try:
        payment_data = await payos.create_payment_link(
            order_code=order_code,
            amount=price,
            description=description,
            return_url=req.return_url or settings.payos_webhook_url.replace("/webhook", "/return"),
            cancel_url=req.cancel_url or req.return_url or "https://webharvest.vn",
            buyer_name=req.buyer_name,
            buyer_email=req.buyer_email,
        )
    except PayOSError as e:
        logger.error("PayOS create link failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    # Save transaction
    await db.create_transaction(
        order_code=order_code, amount=price, tier=req.tier,
        duration_months=req.duration_months, device_id=req.device_id,
        buyer_email=req.buyer_email, buyer_name=req.buyer_name,
        checkout_url=payment_data.get("checkoutUrl", ""),
    )

    return {
        "success": True,
        "data": {
            "order_code": order_code,
            "checkout_url": payment_data.get("checkoutUrl", ""),
            "amount": price,
        },
    }


@app.post("/api/payments/webhook")
async def payment_webhook(request: Request):
    """PayOS webhook — MUST always return 200 (same as xuongmedia)."""
    try:
        body = await request.json()

        # Verify signature
        verified_data = payos.verify_webhook(body)
        if not verified_data:
            logger.warning("Webhook verification failed")
            return {"success": True, "data": {"received": True, "note": "verification_skipped"}}

        order_code = int(verified_data.get("orderCode", 0))

        # Test/ping webhook
        if not order_code or order_code == 0:
            return {"success": True, "data": {"received": True, "test": True}}

        # Check if paid
        is_paid = (
            verified_data.get("code") == "00"
            or body.get("code") == "00"
            or body.get("success") is True
            or "thanh cong" in str(verified_data.get("desc", body.get("desc", ""))).lower()
        )

        if is_paid:
            new_key = generate_key()
            result = await db.settle_payment(order_code, verified_data, new_key)
            if result:
                logger.info("Payment settled: order=%d key=%s", order_code, result.get("key", "extended"))
        else:
            await db.cancel_transaction(order_code)

        return {"success": True, "data": {"received": True}}

    except Exception as e:
        logger.error("Webhook error: %s", e)
        return {"success": True, "data": {"received": True, "error": "internal"}}


class VerifyPendingRequest(BaseModel):
    order_code: int
    device_id: str = ""


@app.post("/api/payments/verify-pending")
async def verify_pending(req: VerifyPendingRequest):
    """Frontend polls this after PayOS checkout to confirm payment."""
    tx = await db.get_transaction_by_order(req.order_code)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx["status"] == "paid":
        # Already settled — find the key
        if tx["key_id"]:
            async with db.pool.acquire() as conn:
                key_row = await conn.fetchrow("SELECT * FROM license_keys WHERE id=$1", tx["key_id"])
                if key_row:
                    return {"success": True, "data": {"status": "paid", "key": key_row["key"],
                                                      "tier": key_row["tier"]}}
        return {"success": True, "data": {"status": "paid", "already_processed": True}}

    # Query PayOS for real status
    try:
        payos_info = await payos.get_payment_info(req.order_code)
    except Exception as e:
        logger.warning("PayOS query failed: %s", e)
        raise HTTPException(status_code=502, detail="Cannot check PayOS status")

    payos_status = str(payos_info.get("status", "")).upper()

    if payos_status == "PAID":
        new_key = generate_key()
        result = await db.settle_payment(req.order_code, payos_info, new_key)
        if result:
            return {"success": True, "data": {"status": "paid", "key": result["key"],
                                               "tier": result["tier"], "just_confirmed": True}}
        # Already settled by webhook
        return {"success": True, "data": {"status": "paid", "already_processed": True}}

    if payos_status in ("CANCELLED", "EXPIRED"):
        await db.cancel_transaction(req.order_code)
        return {"success": True, "data": {"status": "cancelled"}}

    return {"success": True, "data": {"status": "pending", "payos_status": payos_status}}


# ══════════════════════════════════════════════════════════════════════════
#  ADMIN API — Dashboard Management
# ══════════════════════════════════════════════════════════════════════════

class AdminLoginRequest(BaseModel):
    password: str


@app.post("/api/admin/auth")
async def admin_login(req: AdminLoginRequest):
    if req.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid password")
    token = secrets.token_hex(32)
    _admin_tokens.add(token)
    return {"success": True, "token": token}


@app.get("/api/admin/dashboard")
async def admin_dashboard(
    date_from: str = None, date_to: str = None,
    _token: str = Depends(_require_admin),
):
    stats = await db.get_dashboard_stats(date_from, date_to)
    return {"success": True, "data": stats}


@app.get("/api/admin/keys")
async def admin_list_keys(
    status: str = None, tier: str = None, search: str = None,
    page: int = 1, limit: int = 50,
    _token: str = Depends(_require_admin),
):
    keys, total = await db.get_all_keys(status=status, tier=tier, search=search, page=page, limit=limit)
    return {
        "success": True,
        "data": [_serialize_row(k) for k in keys],
        "meta": {"page": page, "limit": limit, "total": total},
    }


class AdminCreateKeyRequest(BaseModel):
    tier: str
    duration_months: int
    owner_email: str = ""
    owner_name: str = ""
    note: str = ""
    count: int = 1  # Batch create


@app.post("/api/admin/keys")
async def admin_create_key(req: AdminCreateKeyRequest, _token: str = Depends(_require_admin)):
    if req.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail="Invalid tier")
    if req.duration_months not in VALID_DURATIONS:
        raise HTTPException(status_code=400, detail="Invalid duration")

    price = get_price(req.tier, req.duration_months) or 0
    count = max(1, min(req.count, 100))

    created = []
    for _ in range(count):
        key = generate_key()
        row = await db.create_key(
            key=key, tier=req.tier, duration_months=req.duration_months,
            amount_vnd=price, owner_email=req.owner_email,
            owner_name=req.owner_name, note=req.note,
        )
        created.append(_serialize_row(row))

    return {"success": True, "data": created}


@app.get("/api/admin/keys/{key}")
async def admin_get_key(key: str, _token: str = Depends(_require_admin)):
    row = await db.get_key_by_key(key)
    if not row:
        raise HTTPException(status_code=404, detail="Key not found")
    daily_used = await db.get_daily_usage(row["id"]) if row["status"] == "active" else 0
    return {"success": True, "data": {**_serialize_row(row), "daily_urls_used": daily_used}}


class AdminUpdateKeyRequest(BaseModel):
    action: str  # 'revoke', 'extend', 'reset_device', 'update_note'
    extend_months: int = 0
    note: str = ""


@app.patch("/api/admin/keys/{key}")
async def admin_update_key(key: str, req: AdminUpdateKeyRequest, _token: str = Depends(_require_admin)):
    existing = await db.get_key_by_key(key)
    if not existing:
        raise HTTPException(status_code=404, detail="Key not found")

    if req.action == "revoke":
        await db.revoke_key(key)
        return {"success": True, "message": "Key revoked"}

    if req.action == "extend":
        if req.extend_months <= 0:
            raise HTTPException(status_code=400, detail="extend_months must be positive")
        result = await db.extend_key(key, req.extend_months)
        return {"success": True, "data": _serialize_row(result) if result else None}

    if req.action == "reset_device":
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE license_keys SET device_id=NULL, device_name=NULL, rebind_count=0 WHERE key=$1",
                key,
            )
        return {"success": True, "message": "Device binding reset"}

    if req.action == "update_note":
        async with db.pool.acquire() as conn:
            await conn.execute("UPDATE license_keys SET note=$2 WHERE key=$1", key, req.note)
        return {"success": True, "message": "Note updated"}

    raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")


@app.delete("/api/admin/keys/{key}")
async def admin_delete_key(key: str, _token: str = Depends(_require_admin)):
    await db.revoke_key(key)
    return {"success": True, "message": "Key revoked"}


@app.get("/api/admin/requests")
async def admin_request_logs(
    key_id: int = None, status: str = None,
    date_from: str = None, date_to: str = None,
    page: int = 1, limit: int = 50,
    _token: str = Depends(_require_admin),
):
    logs, total = await db.get_request_logs(
        key_id=key_id, status=status, date_from=date_from, date_to=date_to,
        page=page, limit=limit,
    )
    return {
        "success": True,
        "data": [_serialize_row(l) for l in logs],
        "meta": {"page": page, "limit": limit, "total": total},
    }


@app.get("/api/admin/revenue")
async def admin_revenue(
    group_by: str = "day", date_from: str = None, date_to: str = None,
    _token: str = Depends(_require_admin),
):
    report = await db.get_revenue_report(group_by=group_by, date_from=date_from, date_to=date_to)
    return {"success": True, "data": [_serialize_row(r) for r in report]}


# ── Serve Admin Dashboard ─────────────────────────────────────────────────

_static_dir = Path(__file__).parent / "static"
_admin_dir = _static_dir / "admin"


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    index = _admin_dir / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Admin dashboard not found</h1>")


# Mount static files
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
