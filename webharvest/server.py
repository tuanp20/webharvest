from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from webharvest.config import CrawlConfig, FetcherType
from webharvest.pipeline.crawler import CrawlPipeline

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


# Health check for desktop app readiness probe
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


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
            proxy=None,  # Start with local IP
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

# Mount static files directory at /static
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
