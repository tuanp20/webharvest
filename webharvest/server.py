from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from webharvest.config import CrawlConfig, FetcherType
from webharvest.pipeline.crawler import CrawlPipeline

# Configure logging
logger = logging.getLogger("webharvest.server")

app = FastAPI(
    title="WebHarvest API",
    description="Backend API for WebHarvest scraper & image downloader UI",
    version="1.0.0",
)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)

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
            
        # Build CrawlConfig
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
        )
        
        # 2. Set up thread-safe event queue for the websocket stream
        queue = asyncio.Queue()
        
        def on_progress(event: str, event_data: Dict[str, Any]):
            # Place event in queue to be consumed asynchronously
            asyncio.get_event_loop().call_soon_threadsafe(queue.put_nowait, (event, event_data))
            
        # Background task to fetch from the queue and send to WebSocket
        async def event_sender():
            while True:
                event, edata = await queue.get()
                if event is None:
                    queue.task_done()
                    break
                    
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
                    await websocket.send_json({"event": event, "data": edata})
                except Exception:
                    # Connection closed or error sending
                    break
                finally:
                    queue.task_done()
                    
        sender_task = asyncio.create_task(event_sender())
        
        # 3. Instantiate and run pipeline
        pipeline = CrawlPipeline(config, on_progress=on_progress)
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
