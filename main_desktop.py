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
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# PyInstaller compatibility: resolve the correct base path for bundled assets
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Running inside a PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(sys.executable).parent  # folder containing the .exe
else:
    BASE_DIR = Path(__file__).parent
    APP_DIR = BASE_DIR

# Ensure the webharvest package is importable when running from source
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(BASE_DIR))

# ---------------------------------------------------------------------------
# Logging — write to both console and a log file next to the .exe
# ---------------------------------------------------------------------------
LOG_FILE = APP_DIR / "WebHarvest.log"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="w"),
    ],
)
logger = logging.getLogger("webharvest.desktop")
logger.info("WebHarvest Desktop starting...")
logger.info("  Platform: %s", platform.platform())
logger.info("  Python:   %s", sys.version)
logger.info("  Frozen:   %s", getattr(sys, "frozen", False))
logger.info("  BASE_DIR: %s", BASE_DIR)
logger.info("  APP_DIR:  %s", APP_DIR)
logger.info("  LOG_FILE: %s", LOG_FILE)


def _show_error_dialog(title: str, message: str) -> None:
    """Show a native error dialog. Works even when pywebview is broken."""
    logger.error("%s: %s", title, message)
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, message, title, 0x10  # MB_ICONERROR
            )
        elif system == "Darwin":
            os.system(
                f'osascript -e \'display dialog "{message}" with title "{title}" buttons {{"OK"}} default button "OK" with icon stop\''
            )
        else:
            # Linux — try zenity, then kdialog, then print
            if os.system(f'zenity --error --title="{title}" --text="{message}" 2>/dev/null') != 0:
                if os.system(f'kdialog --error "{message}" --title "{title}" 2>/dev/null') != 0:
                    print(f"\n{'='*50}\n{title}\n{'='*50}\n{message}\n", file=sys.stderr)
    except Exception:
        print(f"\n{'='*50}\n{title}\n{'='*50}\n{message}\n", file=sys.stderr)


def _find_free_port() -> int:
    """Find a random available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
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
    """Open a native OS window using pywebview, with browser fallback."""
    url = f"http://127.0.0.1:{port}"

    try:
        import webview
        logger.info("pywebview imported successfully")
    except ImportError as e:
        logger.warning("pywebview not available: %s — opening in browser", e)
        _open_in_browser(url)
        return

    # Create the window
    window = webview.create_window(
        title="WebHarvest -- Image Scraper & Downloader",
        url=url,
        width=1280,
        height=800,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    def on_closed():
        logger.info("Window closed -- shutting down server")
        _stop_server()

    window.events.closed += on_closed

    # Let pywebview pick the best backend automatically.
    # Do NOT force edgechromium — it may not be available.
    try:
        logger.info("Starting pywebview GUI...")
        webview.start(debug=False)
        logger.info("pywebview exited normally")
    except Exception as e:
        logger.warning("pywebview failed (%s) — falling back to browser", e)
        logger.warning("Traceback: %s", traceback.format_exc())
        _open_in_browser(url)


def _open_in_browser(url: str) -> None:
    """Fallback: open in the system default browser."""
    import webbrowser
    logger.info("Opening in default browser: %s", url)
    webbrowser.open(url)
    print()
    print("=" * 55)
    print("  WebHarvest is running in your browser!")
    print(f"  URL: {url}")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 55)
    print()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        port = _find_free_port()
        logger.info("Selected port: %d", port)

        # 1. Start the embedded server
        _start_server(port)

        # 2. Wait for server readiness
        logger.info("Waiting for server to be ready...")
        if not _wait_for_server(port, timeout=25.0):
            _show_error_dialog(
                "WebHarvest - Server Error",
                "Server khong the khoi dong sau 25 giay.\n\n"
                f"Xem log chi tiet tai:\n{LOG_FILE}"
            )
            sys.exit(1)
        logger.info("Server is ready!")

        # 3. Open the native window (or browser fallback)
        _open_window(port)

        # 4. Cleanup
        _stop_server()
        logger.info("WebHarvest Desktop exited cleanly.")

    except Exception as e:
        error_msg = (
            f"Loi khong mong muon: {e}\n\n"
            f"Chi tiet:\n{traceback.format_exc()}\n\n"
            f"Xem log tai:\n{LOG_FILE}"
        )
        _show_error_dialog("WebHarvest - Error", error_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
