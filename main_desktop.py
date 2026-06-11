"""
WebHarvest Desktop — Native desktop wrapper for the WebHarvest web scraper.

Launches an embedded FastAPI server and opens a native OS window (pywebview)
pointing to the local server. Fully portable — no Python installation needed
when bundled via PyInstaller.
"""

from __future__ import annotations

import logging
import os
import platform
import signal
import socket
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# PyInstaller compatibility: resolve the correct base path for bundled assets
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Running inside a PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

# Ensure the webharvest package is importable when running from source
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(BASE_DIR))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("webharvest.desktop")


def _find_free_port() -> int:
    """Find a random available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Block until the HTTP server responds on *port* or *timeout* elapses."""
    import urllib.request
    import urllib.error

    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ConnectionRefusedError):
            pass
        time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------
# Server thread
# ---------------------------------------------------------------------------
_server_thread: threading.Thread | None = None
_uvicorn_server = None


def _run_server(port: int) -> None:
    """Start uvicorn in the current thread (blocking)."""
    global _uvicorn_server

    import uvicorn

    config = uvicorn.Config(
        "webharvest.server:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        # Disable reload in production bundle
        reload=False,
    )
    _uvicorn_server = uvicorn.Server(config)
    _uvicorn_server.run()


def _start_server(port: int) -> None:
    """Launch the server on a background daemon thread."""
    global _server_thread
    _server_thread = threading.Thread(
        target=_run_server,
        args=(port,),
        daemon=True,
        name="uvicorn-server",
    )
    _server_thread.start()


def _stop_server() -> None:
    """Gracefully shut down the uvicorn server."""
    global _uvicorn_server
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
        logger.info("Server shutdown signal sent")


# ---------------------------------------------------------------------------
# Desktop window
# ---------------------------------------------------------------------------
def _open_window(port: int) -> None:
    """Open a native OS window using pywebview."""
    import webview

    url = f"http://127.0.0.1:{port}"

    # Window settings
    window = webview.create_window(
        title="WebHarvest — Image Scraper & Downloader",
        url=url,
        width=1280,
        height=800,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    def on_closed():
        logger.info("Window closed — shutting down server…")
        _stop_server()

    window.events.closed += on_closed

    # Start the webview event loop (blocks until window is closed)
    # Use default renderer on each platform
    gui_backend = None
    system = platform.system()
    if system == "Windows":
        # Use EdgeChromium (mshtml fallback)
        gui_backend = "edgechromium"
    elif system == "Darwin":
        gui_backend = "cocoa"
    # Linux defaults to GTK or QT depending on what's available

    try:
        webview.start(gui=gui_backend, debug=False)
    except Exception:
        # Fallback: if pywebview fails, open in default browser
        logger.warning("pywebview failed — falling back to system browser")
        import webbrowser
        webbrowser.open(url)
        # Keep the process alive until Ctrl+C
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    port = _find_free_port()
    logger.info("Starting WebHarvest Desktop on port %d …", port)

    # 1. Start the embedded server
    _start_server(port)

    # 2. Wait for server readiness
    logger.info("Waiting for server to be ready …")
    if not _wait_for_server(port, timeout=20.0):
        logger.error("Server failed to start within 20 seconds!")
        sys.exit(1)
    logger.info("Server is ready!")

    # 3. Open the native window
    _open_window(port)

    # 4. Cleanup
    _stop_server()
    logger.info("WebHarvest Desktop exited cleanly.")


if __name__ == "__main__":
    main()
