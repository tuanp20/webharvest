from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import shutil
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from webharvest.config import CrawlConfig, FetcherType
from webharvest.pipeline import CrawlPipeline, ProductCrawlPipeline
from webharvest.batch_parser import parse_file, parse_google_sheet, ParseResult

import httpx as _httpx
import json as _json

# Configure logging
logger = logging.getLogger("webharvest.server")

app = FastAPI(
    title="WebHarvest API",
    description="Backend API for WebHarvest scraper & image downloader UI",
    version="1.0.0",
)

# PyInstaller compatibility: resolve static dir from bundle or source
if getattr(sys, "frozen", False):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).parent

static_dir = _base / "webharvest" / "static" if getattr(sys, "frozen", False) else _base / "static"
static_dir.mkdir(parents=True, exist_ok=True)


def _get_proxies_file_path() -> Path:
    """Resolve path to proxies.txt next to the executable or project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "proxies.txt"
    return Path(__file__).parent.parent / "proxies.txt"


def _get_settings_path() -> Path:
    """Resolve path to webharvest_settings.json next to the executable or project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "webharvest_settings.json"
    return Path(__file__).parent.parent / "webharvest_settings.json"


# ── License Validation Layer ──────────────────────────────────────────────

try:
    from dotenv import load_dotenv
    if getattr(sys, "frozen", False):
        load_dotenv(Path(sys.executable).parent / ".env")
    else:
        load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "http://127.0.0.1:8443")
_license_cache: Dict[str, Any] = {}  # {key: {data, cached_at}}
_LICENSE_CACHE_TTL = 300  # 5 minutes
_LICENSE_GRACE_PERIOD = 86_400  # 24 hours offline grace
_license_cache_file: Path = (
    Path(sys.executable).parent / ".license_cache.json"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent / ".license_cache.json"
)


def _generate_device_id() -> str:
    """Generate a stable device fingerprint from hardware characteristics."""
    parts = [
        platform.node(),           # hostname
        platform.system(),         # OS
        platform.machine(),        # arch
        platform.processor(),      # CPU
    ]
    # Try to get MAC address
    try:
        mac = uuid.getnode()
        parts.append(str(mac))
    except Exception:
        pass
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _get_device_name() -> str:
    return f"{platform.node()} / {platform.system()} {platform.release()}"


async def validate_license(key: str, device_id: str, action: str = "validate") -> Dict[str, Any]:
    """Validate license key against the central license server.

    Uses 5-minute in-memory cache and 24-hour offline grace period.
    Returns validation result dict or raises HTTPException.
    """
    if not LICENSE_SERVER_URL:
        # No license server configured → free mode (development)
        return {"valid": True, "tier": "unlimited", "limits": {
            "max_daily_urls": 999999, "max_concurrent": 20,
            "batch_crawl": True, "stealth_mode": True, "proxy_support": True,
            "allowed_fetchers": ["auto", "static", "dynamic", "stealth"],
        }}

    # Check in-memory cache
    cache_key = f"{key}:{device_id}"
    cached = _license_cache.get(cache_key)
    if cached and (time.time() - cached["cached_at"]) < _LICENSE_CACHE_TTL:
        return cached["data"]

    # Call license server
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{LICENSE_SERVER_URL}/api/license/validate",
                json={"key": key, "device_id": device_id, "action": action},
            )
            data = resp.json()

            if resp.status_code == 200 and data.get("valid"):
                # Cache successful validation
                _license_cache[cache_key] = {"data": data, "cached_at": time.time()}
                # Save to disk for offline grace
                _save_license_cache(key, device_id, data)
                return data
            else:
                # Server reachable but validation failed
                error = data.get("error", "License validation failed")
                error_code = data.get("error_code", "INVALID")
                raise HTTPException(status_code=403, detail={"error": error, "error_code": error_code})

    except _httpx.RequestError:
        # Server unreachable → check offline grace period
        return _check_offline_grace(key, device_id)


def _save_license_cache(key: str, device_id: str, data: dict):
    """Persist validation to disk for offline grace."""
    try:
        cache = {}
        if _license_cache_file.exists():
            cache = _json.loads(_license_cache_file.read_text(encoding="utf-8"))
        cache[f"{key}:{device_id}"] = {
            "data": data,
            "validated_at": time.time(),
        }
        _license_cache_file.write_text(
            _json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Failed to save license cache: %s", e)


def _check_offline_grace(key: str, device_id: str) -> dict:
    """Allow offline usage if last validation was within grace period."""
    try:
        if _license_cache_file.exists():
            cache = _json.loads(_license_cache_file.read_text(encoding="utf-8"))
            entry = cache.get(f"{key}:{device_id}")
            if entry:
                elapsed = time.time() - entry["validated_at"]
                if elapsed < _LICENSE_GRACE_PERIOD:
                    logger.info("Using offline license grace (%.0fh remaining)", (_LICENSE_GRACE_PERIOD - elapsed) / 3600)
                    return entry["data"]
    except Exception as e:
        logger.warning("Failed to read license cache: %s", e)

    raise HTTPException(status_code=503, detail={
        "error": "License server unreachable and offline grace period expired",
        "error_code": "OFFLINE_EXPIRED",
    })


# Health check for desktop app readiness probe
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


# ── Device ID & License Endpoints (for frontend) ─────────────────────────

@app.get("/api/device-id")
async def get_device_id():
    """Return this machine's hardware fingerprint for license binding."""
    return {
        "device_id": _generate_device_id(),
        "device_name": _get_device_name(),
    }


class LicenseActivateBody(BaseModel):
    key: str


@app.post("/api/license/activate-local")
async def activate_license_local(body: LicenseActivateBody):
    """Activate a license key from the desktop app."""
    if not LICENSE_SERVER_URL:
        return {"success": True, "data": {"tier": "unlimited", "message": "Dev mode"}}

    device_id = _generate_device_id()
    device_name = _get_device_name()

    try:
        async with _httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{LICENSE_SERVER_URL}/api/license/activate",
                json={"key": body.key, "device_id": device_id, "device_name": device_name},
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("success"):
                # Cache the validation
                vdata = data.get("data", {})
                vdata["valid"] = True
                _license_cache[f"{body.key}:{device_id}"] = {"data": vdata, "cached_at": time.time()}
                _save_license_cache(body.key, device_id, vdata)
                return data
            return {"success": False, "error": data.get("error", "Activation failed"),
                    "error_code": data.get("error_code", "UNKNOWN")}
    except _httpx.RequestError as e:
        return {"success": False, "error": f"Cannot reach license server: {e}", "error_code": "UNREACHABLE"}


@app.post("/api/license/validate-local")
async def validate_license_local(body: LicenseActivateBody):
    """Validate current license from the desktop app (used on startup & periodically)."""
    device_id = _generate_device_id()
    try:
        result = await validate_license(body.key, device_id, "validate")
        return {"success": True, "data": result}
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
        return {"success": False, **detail}


@app.get("/api/license/packages")
async def get_license_packages():
    """Proxy packages list from license server."""
    if not LICENSE_SERVER_URL:
        return {"success": True, "data": []}
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{LICENSE_SERVER_URL}/api/packages")
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


class CreatePaymentBody(BaseModel):
    tier: str
    duration_months: int
    buyer_email: str = ""
    buyer_name: str = ""


@app.post("/api/license/create-payment")
async def create_payment_local(body: CreatePaymentBody):
    """Create PayOS payment link via license server."""
    if not LICENSE_SERVER_URL:
        return {"success": False, "error": "License server not configured"}
    device_id = _generate_device_id()
    try:
        async with _httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{LICENSE_SERVER_URL}/api/payments/create-link",
                json={**body.model_dump(), "device_id": device_id},
            )
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


class VerifyPaymentBody(BaseModel):
    order_code: int


@app.post("/api/license/verify-payment")
async def verify_payment_local(body: VerifyPaymentBody):
    """Poll payment status from license server."""
    if not LICENSE_SERVER_URL:
        return {"success": False, "error": "License server not configured"}
    device_id = _generate_device_id()
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{LICENSE_SERVER_URL}/api/payments/verify-pending",
                json={"order_code": body.order_code, "device_id": device_id},
            )
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Proxy Settings (save/load DataImpulse credentials locally) ────────────
class ProxySettings(BaseModel):
    provider: str = "none"           # "none" | "dataimpulse" | "manual"
    di_username: str = ""
    di_password: str = ""
    di_country: str = ""
    di_session: str = "0"            # "0" = rotating, "10"/"30"/"60" = sticky
    manual_proxy: str = ""


@app.get("/api/proxy-settings")
async def get_proxy_settings():
    """Load saved proxy settings from local JSON file."""
    path = _get_settings_path()
    if path.exists():
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            proxy_cfg = data.get("proxy", {})
            return {"ok": True, "settings": proxy_cfg}
        except Exception as e:
            logger.warning("Failed to read settings: %s", e)
    return {"ok": True, "settings": {}}


@app.post("/api/proxy-settings")
async def save_proxy_settings(settings: ProxySettings):
    """Save proxy settings to local JSON file."""
    path = _get_settings_path()
    try:
        existing = {}
        if path.exists():
            existing = _json.loads(path.read_text(encoding="utf-8"))
        existing["proxy"] = settings.model_dump()
        path.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        logger.error("Failed to save settings: %s", e)
        return {"ok": False, "error": str(e)}


@app.post("/api/test-proxy")
async def test_proxy(data: dict):
    """Test a proxy URL by making a request to httpbin.org/ip."""
    proxy_url = data.get("proxy", "").strip()
    if not proxy_url:
        return {"ok": False, "error": "Proxy URL is empty"}
    try:
        async with _httpx.AsyncClient(proxy=proxy_url, timeout=15) as client:
            resp = await client.get("https://httpbin.org/ip")
            ip_info = resp.json().get("origin", "unknown")
            return {"ok": True, "ip": ip_info, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Serve index.html at root
@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>WebHarvest UI Static Files Not Found</h1>")


# Serve image dynamically from local path (supports custom output directories)
@app.get("/api/image")
async def get_image(path: str = Query(..., description="Absolute path to the downloaded image file")):
    filepath = Path(path).resolve()
    
    # Validation: exists, is a file
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
        
    # Validation: is an image extension
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff", ".avif"}
    if filepath.suffix.lower() not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Invalid image file type")
        
    return FileResponse(str(filepath))


# List history of downloaded images from output directory
@app.get("/api/history")
async def get_history(output_dir: str = Query("./output", description="Directory to scan for downloaded images")):
    resolved_dir = Path(output_dir).expanduser().resolve()
    if not resolved_dir.exists() or not resolved_dir.is_dir():
        return {"images": []}
        
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff", ".avif"}
    images = []
    
    # Walk through the output directory
    for file_path in resolved_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in allowed_extensions:
            # Domain is the parent directory relative to resolved_dir
            try:
                domain = file_path.parent.relative_to(resolved_dir).name
            except ValueError:
                domain = "unknown"
                
            stat = file_path.stat()
            images.append({
                "name": file_path.name,
                "domain": domain if domain else "root",
                "path": str(file_path),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
            
    # Sort by modification time (newest first)
    images.sort(key=lambda x: x["mtime"], reverse=True)
    return {"images": images}


# WebSocket endpoint for real-time crawl streaming
@app.websocket("/api/ws/crawl")
async def ws_crawl(websocket: WebSocket):
    await websocket.accept()
    
    try:
        # 1. Receive crawl config
        data = await websocket.receive_json()
        
        url = data.get("url", "").strip()
        if not url:
            await websocket.send_json({"event": "error", "data": {"message": "URL is required"}})
            await websocket.close()
            return
            
        output_dir = data.get("output_dir", "./output").strip()
        depth = int(data.get("depth", 0))
        max_pages = int(data.get("max_pages", 100))
        fetcher_str = data.get("fetcher", "auto")
        min_file_size = int(data.get("min_file_size", 0))
        allowed_formats = set(data.get("allowed_formats", ["jpg", "jpeg", "png", "gif", "webp"]))
        
        # Parse fetcher
        try:
            fetcher = FetcherType(fetcher_str.lower())
        except ValueError:
            fetcher = FetcherType.AUTO

        # Smart auto-detect: force stealth for sites known to use anti-bot
        _STEALTH_DOMAINS = ["etsy.com", "pinterest.com", "instagram.com", "tiktok.com"]
        from urllib.parse import urlparse as _urlparse
        _domain = _urlparse(url).netloc.lower()
        if fetcher == FetcherType.AUTO and any(d in _domain for d in _STEALTH_DOMAINS):
            logger.info("Auto-detected anti-bot site (%s), forcing stealth fetcher", _domain)
            fetcher = FetcherType.STEALTH
            
        # Parse proxy setting
        proxy = data.get("proxy", None)
        if proxy and isinstance(proxy, str):
            proxy = proxy.strip() or None
        else:
            proxy = None

        # Load backup proxies from proxies.txt next to app
        backup_proxies: list[str] = []
        if proxy:
            backup_proxies.append(proxy)
        _proxies_file = _get_proxies_file_path()
        if _proxies_file and _proxies_file.exists():
            try:
                for line in _proxies_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and line not in backup_proxies:
                        backup_proxies.append(line)
            except Exception:
                pass
        logger.info("Backup proxies loaded: %d", len(backup_proxies))

        # Build CrawlConfig  (proxy=None → use local IP first)
        config = CrawlConfig(
            url=url,
            output_dir=output_dir,
            depth=depth,
            max_pages=max_pages,
            fetcher=fetcher,
            min_file_size=min_file_size,
            allowed_formats=allowed_formats,
            create_dirs=True,
            overwrite=False,
            proxy=proxy,  # Start directly with the configured proxy (e.g. DataImpulse or manual proxy)
        )
        
        # 2. Set up thread-safe event queue for the websocket stream
        queue = asyncio.Queue()

        # Map backend event names → frontend event names
        _EVENT_MAP = {
            "crawl_start": "crawl_started",
            "page_fetch": "page_started",
            "page_parsed": "page_fetched",
            "antibot_detected": "antibot_detected",
            "js_detected": "js_detected",
            "upgrade_failed": "upgrade_failed",
            "download_start": "download_start",
            "image_downloaded": "image_downloaded",
            "download_done": "download_done",
            "crawl_done": "crawl_done",
            "gallery_empty": "gallery_empty",
            "next_page": "next_page",
            "proxy_fallback": "proxy_fallback",
            "proxy_success": "proxy_success",
            "local_ip_success": "local_ip_success",
            "all_proxies_failed": "all_proxies_failed",
        }
        
        def on_progress(event: str, event_data: Dict[str, Any]):
            # Place event in queue to be consumed asynchronously
            asyncio.get_event_loop().call_soon_threadsafe(queue.put_nowait, (event, event_data))
            
        # Background task to fetch from the queue and send to WebSocket
        async def event_sender():
            pages_visited = 0
            images_found = 0
            while True:
                event, edata = await queue.get()
                if event is None:
                    queue.task_done()
                    break

                # Translate event name for frontend
                fe_event = _EVENT_MAP.get(event, event)

                # Enrich page_fetched with running stats
                if event == "page_parsed":
                    pages_visited += 1
                    images_found += edata.get("images", 0)
                    edata["pages_visited"] = pages_visited
                    edata["images_found"] = images_found
                    
                # Format CrawlResult for JSON serialization
                if event == "crawl_done" and "result" in edata:
                    r = edata["result"]
                    edata = {
                        "result": {
                            "start_url": r.start_url,
                            "pages_visited": r.pages_visited,
                            "images_found": r.images_found,
                            "images_downloaded": r.images_downloaded,
                            "images_failed": r.images_failed,
                            "total_bytes": r.total_bytes,
                            "elapsed_seconds": r.elapsed_seconds,
                            "errors": r.errors,
                            "summary": r.summary(),
                        }
                    }
                    
                try:
                    await websocket.send_json({"event": fe_event, "data": edata})
                except Exception:
                    # Connection closed or error sending
                    break
                finally:
                    queue.task_done()
                    
        sender_task = asyncio.create_task(event_sender())
        
        # 3. Instantiate and run pipeline (with backup proxies for fallback)
        pipeline = CrawlPipeline(config, on_progress=on_progress, backup_proxies=backup_proxies)
        try:
            await pipeline.run()
        except Exception as e:
            logger.error("Crawl pipeline error: %s", e)
            await websocket.send_json({"event": "error", "data": {"message": str(e)}})
        finally:
            # Signal sender task to exit
            await queue.put((None, None))
            await sender_task
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket server error: %s", e)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(e)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/products")
async def get_products(output_dir: str = Query("./output")):
    """Load extracted product data from local products.json file."""
    resolved = Path(output_dir).expanduser().resolve()
    file_path = resolved / "products.json"
    if file_path.exists() and file_path.is_file():
        try:
            return {"ok": True, "products": _json.loads(file_path.read_text(encoding="utf-8"))}
        except Exception as e:
            return {"ok": False, "error": f"Failed to parse products.json: {e}"}
    return {"ok": True, "products": []}


@app.websocket("/api/ws/product-crawl")
async def ws_product_crawl(websocket: WebSocket):
    """WebSocket endpoint for real-time product crawl streaming."""
    await websocket.accept()
    try:
        # 1. Receive crawl config
        data = await websocket.receive_json()
        
        urls = data.get("urls", [])
        if isinstance(urls, str):
            urls = [u.strip() for u in urls.splitlines() if u.strip()]
        
        if not urls:
            await websocket.send_json({"event": "error", "data": {"message": "At least one URL is required"}})
            await websocket.close()
            return
            
        output_dir = data.get("output_dir", "./output").strip()
        max_products = int(data.get("max_products", 50))
        proxy = data.get("proxy", None)
        if proxy and isinstance(proxy, str):
            proxy = proxy.strip() or None
        else:
            proxy = None

        # Load backup proxies
        backup_proxies: list[str] = []
        if proxy:
            backup_proxies.append(proxy)
        _proxies_file = _get_proxies_file_path()
        if _proxies_file and _proxies_file.exists():
            try:
                for line in _proxies_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and line not in backup_proxies:
                        backup_proxies.append(line)
            except Exception:
                pass

        # Queue for WebSocket streaming
        queue = asyncio.Queue()

        def on_progress(event: str, event_data: Dict[str, Any]):
            asyncio.get_event_loop().call_soon_threadsafe(queue.put_nowait, (event, event_data))

        async def event_sender():
            while True:
                event, edata = await queue.get()
                if event is None:
                    queue.task_done()
                    break
                try:
                    await websocket.send_json({"event": event, "data": edata})
                except Exception:
                    break
                finally:
                    queue.task_done()

        sender_task = asyncio.create_task(event_sender())

        pipeline = ProductCrawlPipeline(
            urls=urls,
            output_dir=output_dir,
            max_products=max_products,
            proxies=backup_proxies,
            on_progress=on_progress
        )

        try:
            await pipeline.run()
        except Exception as e:
            logger.error("Product crawl pipeline error: %s", e)
            await websocket.send_json({"event": "error", "data": {"message": str(e)}})
        finally:
            await queue.put((None, None))
            await sender_task

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket server error: %s", e)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(e)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Batch Import Endpoints ─────────────────────────────────────────────

# Max upload size: 10MB
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024


def _parse_result_to_dict(result: ParseResult) -> dict:
    """Convert ParseResult to JSON-serializable dict."""
    return {
        "urls": result.urls,
        "total_rows": result.total_rows,
        "valid_count": result.valid_count,
        "skipped_count": result.skipped_count,
        "duplicate_count": result.duplicate_count,
        "errors": result.errors,
        "source_type": result.source_type,
    }


@app.post("/api/upload-batch")
async def upload_batch(file: UploadFile = File(...)):
    """Upload an Excel or CSV file containing a list of URLs to crawl."""
    if not file.filename:
        return {"ok": False, "error": "Không có file nào được chọn."}

    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv", ".tsv", ".txt"):
        return {
            "ok": False,
            "error": f"Định dạng '{ext}' không hỗ trợ. Dùng .xlsx, .csv, hoặc .txt."
        }

    # Read file content with size limit
    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        return {"ok": False, "error": "File quá lớn (tối đa 10MB)."}

    result = parse_file(content, file.filename)
    return {"ok": True, "data": _parse_result_to_dict(result)}


class SheetRequest(BaseModel):
    url: str


@app.post("/api/parse-sheet")
async def parse_sheet(req: SheetRequest):
    """Parse URLs from a public Google Sheets link."""
    sheet_url = req.url.strip()
    if not sheet_url:
        return {"ok": False, "error": "Link Google Sheets trống."}

    result = await parse_google_sheet(sheet_url)
    return {"ok": True, "data": _parse_result_to_dict(result)}


# ── Batch Crawl WebSocket ──────────────────────────────────────────────

def _sanitize_domain(url: str) -> str:
    """Extract and sanitize domain from URL for folder name."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or "unknown"
        # Replace dots and special chars with underscores
        return domain.replace(".", "_").replace(":", "_")[:60]
    except Exception:
        return "unknown"


def _check_disk_space(path: str, min_gb: float = 2.0) -> tuple[bool, float]:
    """Check if disk has enough free space."""
    try:
        usage = shutil.disk_usage(Path(path).resolve().anchor)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= min_gb, free_gb
    except Exception:
        return True, 0.0  # If we can't check, proceed anyway


@app.websocket("/api/ws/batch-crawl")
async def ws_batch_crawl(websocket: WebSocket):
    """WebSocket endpoint for batch crawling multiple URLs.

    Protocol:
      Client sends: {
        "urls": ["https://...", ...],
        "output_dir": "./output",
        "depth": 0,
        "max_pages": 20,
        "fetcher": "auto",
        "min_file_size": 10240,
        "allowed_formats": ["jpg", "png", ...],
        "proxy": "http://..." | null,
        "max_concurrent_domains": 3
      }

      Server sends events:
        batch_start      → {total_urls, batch_folder}
        batch_url_start  → {index, url, domain_folder}
        page_started     → {url, batch_index}
        page_fetched     → {url, images, batch_index, ...}
        image_downloaded → {url, path, size, batch_index}
        batch_url_done   → {index, url, result}
        batch_url_error  → {index, url, error}
        batch_done       → {total, success, failed, results}
    """
    await websocket.accept()

    try:
        data = await websocket.receive_json()

        urls = data.get("urls", [])
        if not urls or not isinstance(urls, list):
            await websocket.send_json({"event": "error", "data": {"message": "Danh sách URL trống."}})
            await websocket.close()
            return

        output_dir = data.get("output_dir", "./output").strip()
        depth = int(data.get("depth", 0))
        max_pages = int(data.get("max_pages", 20))
        fetcher_str = data.get("fetcher", "auto")
        min_file_size = int(data.get("min_file_size", 0))
        allowed_formats = set(data.get("allowed_formats", ["jpg", "jpeg", "png", "gif", "webp"]))
        max_concurrent = int(data.get("max_concurrent_domains", 3))

        try:
            fetcher = FetcherType(fetcher_str.lower())
        except ValueError:
            fetcher = FetcherType.AUTO

        # Parse proxy
        proxy = data.get("proxy", None)
        if proxy and isinstance(proxy, str):
            proxy = proxy.strip() or None
        else:
            proxy = None

        # Load backup proxies
        backup_proxies: list[str] = []
        if proxy:
            backup_proxies.append(proxy)
        _proxies_file = _get_proxies_file_path()
        if _proxies_file and _proxies_file.exists():
            try:
                for line in _proxies_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and line not in backup_proxies:
                        backup_proxies.append(line)
            except Exception:
                pass

        # Check disk space
        ok_disk, free_gb = _check_disk_space(output_dir)
        if not ok_disk:
            await websocket.send_json({
                "event": "error",
                "data": {
                    "message": f"Dung lượng ổ đĩa còn {free_gb:.1f}GB, cần tối thiểu 2GB. "
                               f"Vui lòng giải phóng dung lượng trước khi batch crawl."
                }
            })
            await websocket.close()
            return

        # Create batch folder
        timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
        batch_folder_name = f"batch_{timestamp}"
        batch_dir = Path(output_dir).expanduser().resolve() / batch_folder_name
        batch_dir.mkdir(parents=True, exist_ok=True)

        # Group URLs by domain for rate limiting
        domain_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for idx, url in enumerate(urls):
            domain = _sanitize_domain(url)
            domain_groups[domain].append((idx, url))

        total_urls = len(urls)
        results: list[dict] = [None] * total_urls  # type: ignore[list-item]
        success_count = 0
        failed_count = 0

        await websocket.send_json({
            "event": "batch_start",
            "data": {
                "total_urls": total_urls,
                "batch_folder": str(batch_dir),
                "domain_groups": len(domain_groups),
            }
        })

        # Semaphore for domain concurrency
        domain_sem = asyncio.Semaphore(max_concurrent)

        async def crawl_domain_group(domain: str, url_list: list[tuple[int, str]]):
            """Crawl all URLs for one domain sequentially."""
            nonlocal success_count, failed_count

            async with domain_sem:
                for idx, url in url_list:
                    # Check if WebSocket is still connected
                    try:
                        await websocket.send_json({
                            "event": "batch_url_start",
                            "data": {"index": idx, "url": url, "domain": domain}
                        })
                    except Exception:
                        return  # WebSocket disconnected

                    domain_folder = batch_dir / domain
                    domain_folder.mkdir(parents=True, exist_ok=True)

                    # Auto-detect stealth domains
                    url_fetcher = fetcher
                    _STEALTH_DOMAINS = ["etsy.com", "pinterest.com", "instagram.com", "tiktok.com"]
                    _domain = urlparse(url).netloc.lower()
                    if url_fetcher == FetcherType.AUTO and any(d in _domain for d in _STEALTH_DOMAINS):
                        url_fetcher = FetcherType.STEALTH

                    config = CrawlConfig(
                        url=url,
                        output_dir=str(domain_folder),
                        depth=depth,
                        max_pages=max_pages,
                        fetcher=url_fetcher,
                        min_file_size=min_file_size,
                        allowed_formats=allowed_formats,
                        create_dirs=True,
                        overwrite=False,
                        proxy=proxy,
                    )

                    # Event queue for this URL's crawl
                    queue: asyncio.Queue = asyncio.Queue()

                    _EVENT_MAP = {
                        "crawl_start": "crawl_started",
                        "page_fetch": "page_started",
                        "page_parsed": "page_fetched",
                        "antibot_detected": "antibot_detected",
                        "js_detected": "js_detected",
                        "upgrade_failed": "upgrade_failed",
                        "download_start": "download_start",
                        "image_downloaded": "image_downloaded",
                        "download_done": "download_done",
                        "crawl_done": "crawl_done",
                        "gallery_empty": "gallery_empty",
                        "next_page": "next_page",
                        "proxy_fallback": "proxy_fallback",
                        "proxy_success": "proxy_success",
                        "local_ip_success": "local_ip_success",
                        "all_proxies_failed": "all_proxies_failed",
                    }

                    def on_progress(event: str, event_data: Dict[str, Any]):
                        asyncio.get_event_loop().call_soon_threadsafe(
                            queue.put_nowait, (event, event_data)
                        )

                    # Background sender for this URL
                    async def url_event_sender():
                        pages_visited = 0
                        images_found = 0
                        while True:
                            event, edata = await queue.get()
                            if event is None:
                                queue.task_done()
                                break

                            fe_event = _EVENT_MAP.get(event, event)

                            if event == "page_parsed":
                                pages_visited += 1
                                images_found += edata.get("images", 0)
                                edata["pages_visited"] = pages_visited
                                edata["images_found"] = images_found

                            if event == "crawl_done" and "result" in edata:
                                r = edata["result"]
                                edata = {
                                    "result": {
                                        "start_url": r.start_url,
                                        "pages_visited": r.pages_visited,
                                        "images_found": r.images_found,
                                        "images_downloaded": r.images_downloaded,
                                        "images_failed": r.images_failed,
                                        "total_bytes": r.total_bytes,
                                        "elapsed_seconds": r.elapsed_seconds,
                                        "errors": r.errors,
                                        "summary": r.summary(),
                                    }
                                }

                            # Add batch context
                            edata["batch_index"] = idx
                            edata["batch_url"] = url

                            try:
                                await websocket.send_json({"event": fe_event, "data": edata})
                            except Exception:
                                break
                            finally:
                                queue.task_done()

                    sender_task = asyncio.create_task(url_event_sender())

                    # Run the crawl with per-URL timeout (120s)
                    try:
                        pipeline = CrawlPipeline(config, on_progress=on_progress, backup_proxies=backup_proxies)
                        crawl_result = await asyncio.wait_for(pipeline.run(), timeout=120.0)

                        url_result = {
                            "url": url,
                            "status": "success",
                            "pages_visited": crawl_result.pages_visited,
                            "images_found": crawl_result.images_found,
                            "images_downloaded": crawl_result.images_downloaded,
                            "images_failed": crawl_result.images_failed,
                            "total_bytes": crawl_result.total_bytes,
                            "elapsed_seconds": crawl_result.elapsed_seconds,
                            "output_folder": str(domain_folder),
                        }
                        results[idx] = url_result
                        success_count += 1

                        try:
                            await websocket.send_json({
                                "event": "batch_url_done",
                                "data": {"index": idx, "url": url, "result": url_result}
                            })
                        except Exception:
                            pass

                    except asyncio.TimeoutError:
                        err_msg = f"Timeout (120s) khi crawl {url}"
                        logger.warning(err_msg)
                        results[idx] = {"url": url, "status": "timeout", "error": err_msg}
                        failed_count += 1
                        try:
                            await websocket.send_json({
                                "event": "batch_url_error",
                                "data": {"index": idx, "url": url, "error": err_msg}
                            })
                        except Exception:
                            pass

                    except Exception as e:
                        err_msg = f"Lỗi crawl {url}: {e}"
                        logger.error(err_msg)
                        results[idx] = {"url": url, "status": "error", "error": str(e)}
                        failed_count += 1
                        try:
                            await websocket.send_json({
                                "event": "batch_url_error",
                                "data": {"index": idx, "url": url, "error": str(e)}
                            })
                        except Exception:
                            pass

                    finally:
                        # Signal sender to exit
                        await queue.put((None, None))
                        await sender_task

                    # Delay between URLs in same domain (politeness)
                    if url_list[-1] != (idx, url):  # not last URL
                        await asyncio.sleep(2.0)

        # Launch all domain groups concurrently (limited by semaphore)
        domain_tasks = [
            asyncio.create_task(crawl_domain_group(domain, url_list))
            for domain, url_list in domain_groups.items()
        ]
        await asyncio.gather(*domain_tasks, return_exceptions=True)

        # Write batch report
        report = {
            "batch_folder": str(batch_dir),
            "timestamp": datetime.now().isoformat(),
            "total_urls": total_urls,
            "success": success_count,
            "failed": failed_count,
            "results": [r for r in results if r is not None],
        }
        try:
            report_path = batch_dir / "batch_report.json"
            report_path.write_text(
                _json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to write batch report: %s", e)

        # Send final batch_done event
        try:
            await websocket.send_json({
                "event": "batch_done",
                "data": report
            })
        except Exception:
            pass

    except WebSocketDisconnect:
        logger.info("Batch WebSocket client disconnected")
    except Exception as e:
        logger.error("Batch WebSocket error: %s", e)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(e)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# Mount static files directory at /static
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
