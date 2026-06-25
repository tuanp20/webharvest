"""
WebHarvest Desktop — Native desktop wrapper for the WebHarvest web scraper.

Launches an embedded FastAPI server and opens a native OS window (pywebview)
pointing to the local server. Fully portable — no Python installation needed
when bundled via PyInstaller.
"""

from __future__ import annotations

import json as _json
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Safe standard streams for --noconsole mode on Windows
# ---------------------------------------------------------------------------
class NullWriter:
    def write(self, text: str) -> int:
        return len(text)
    def flush(self) -> None:
        pass
    def isatty(self) -> bool:
        return False
    def fileno(self) -> int:
        return -1

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()

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
# Multi-instance prevention — platform-aware file lock
# ---------------------------------------------------------------------------
_lock_fd = None

if sys.platform == 'win32':
    import msvcrt
    def _acquire_instance_lock() -> bool:
        """Prevent multiple instances from running simultaneously (Windows)."""
        global _lock_fd
        lock_path = Path.home() / ".webharvest" / "webharvest.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _lock_fd = open(lock_path, 'w')
            msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, IOError):
            return False
else:
    import fcntl
    def _acquire_instance_lock() -> bool:
        """Prevent multiple instances from running simultaneously (POSIX)."""
        global _lock_fd
        lock_path = Path.home() / ".webharvest" / "webharvest.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _lock_fd = open(lock_path, 'w')
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_fd.write(str(os.getpid()))
            _lock_fd.flush()
            return True
        except (BlockingIOError, OSError):
            return False

# ---------------------------------------------------------------------------
# Logging — write to both console and a rotating log file in ~/.webharvest/
# ---------------------------------------------------------------------------
log_dir = Path.home() / ".webharvest" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
LOG_FILE = log_dir / "WebHarvest.log"

handlers: list[logging.Handler] = [
    RotatingFileHandler(
        str(LOG_FILE), maxBytes=5*1024*1024,  # 5MB per file
        backupCount=3, encoding='utf-8'
    )
]
# Only log to stdout/console if running with an active terminal console
if sys.__stdout__ is not None:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=handlers,
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
    import subprocess

    logger.error("%s: %s", title, message)
    system = platform.system()

    # Sanitize inputs — remove any shell-dangerous characters
    safe_title = title.replace('"', '').replace("'", "").replace('\\', '')
    safe_message = message.replace('"', '').replace("'", "").replace('\\', '')

    try:
        if system == "Windows":
            # Use ctypes MessageBox — no shell involved
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, safe_message, safe_title, 0x10  # MB_ICONERROR
            )
        elif system == "Darwin":
            subprocess.run([
                "osascript", "-e",
                f'display dialog "{safe_message}" with title "{safe_title}" buttons {{"OK"}} default button "OK"'
            ], capture_output=True)
        else:
            # Linux — try zenity, then print
            subprocess.run([
                "zenity", "--error",
                f"--title={safe_title}",
                f"--text={safe_message}"
            ], capture_output=True)
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
# Auto-update check (background, non-blocking)
# ---------------------------------------------------------------------------
def _check_for_updates_sync() -> dict:
    """Check for app updates (synchronous, called in background thread)."""
    from webharvest import __version__
    try:
        req = urllib.request.Request(
            'https://api.webharvest.twentypi.com/api/version/latest',
            headers={'User-Agent': f'WebHarvest/{__version__}'}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
            latest = data.get('version', '')
            if latest and latest != __version__:
                return {
                    'update_available': True,
                    'latest_version': latest,
                    'download_url': data.get('download_url', 'https://webharvest.twentypi.com/#download'),
                }
    except Exception:
        pass
    return {'update_available': False}


def _notify_update() -> None:
    """Background task: check for updates and log if available."""
    result = _check_for_updates_sync()
    if result.get('update_available'):
        logger.info("Update available: %s (download: %s)",
                    result['latest_version'], result.get('download_url', ''))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if not _acquire_instance_lock():
        _show_error_dialog("WebHarvest", "WebHarvest is already running!")
        sys.exit(1)

    try:
        port = _find_free_port()
        logger.info("Selected port: %d", port)

        # Create proxies.txt template if it doesn't exist
        proxies_file = APP_DIR / "proxies.txt"
        if not proxies_file.exists():
            proxies_file.write_text(
                "# WebHarvest - Danh sach proxy du phong\n"
                "# Moi dong la 1 proxy URL, vi du:\n"
                "#   http://user:pass@host:port\n"
                "#   socks5://host:port\n"
                "#   http://host:port\n"
                "#\n"
                "# WebHarvest se uu tien IP may local truoc.\n"
                "# Neu bi chan, se tu dong thu cac proxy ben duoi.\n"
                "#\n",
                encoding="utf-8",
            )
            logger.info("Created proxies.txt template at %s", proxies_file)

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

        # 2b. Check for updates in background (non-blocking)
        threading.Thread(target=_notify_update, daemon=True).start()

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
