"""
Build script for WebHarvest Desktop — cross-platform.

Usage:
    python build_desktop.py          # Build for current platform
    python build_desktop.py --onefile # Single-file exe (larger, slower startup)

Output:
    dist/WebHarvest/     (one-folder mode, default)
    dist/WebHarvest.exe  (one-file mode)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Fix Windows console encoding
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _run(cmd: list[str], **kw) -> None:
    print(f">> {' '.join(cmd)}")
    subprocess.check_call(cmd, **kw)


def _ensure_deps() -> None:
    """Install build-time dependencies."""
    deps = ["pyinstaller", "pywebview", "fastapi", "uvicorn[standard]", "curl_cffi"]
    _run([sys.executable, "-m", "pip", "install", "--quiet", *deps])


def _get_icon_path() -> str | None:
    """Return the path to the app icon, or None if not present."""
    system = platform.system()
    if system == "Windows":
        preferred_exts = (".ico", ".png")
    elif system == "Darwin":
        preferred_exts = (".icns", ".png")
    else:
        preferred_exts = (".png", ".ico")

    # Check logo_assets first (preferred location)
    for ext in preferred_exts:
        p = ROOT / "logo_assets" / f"icon{ext}"
        if p.exists():
            return str(p)
    # Fallback to static directory
    for ext in preferred_exts:
        p = ROOT / "webharvest" / "static" / f"icon{ext}"
        if p.exists():
            return str(p)
    return None


def build(onefile: bool = False) -> None:
    system = platform.system()
    print(f"[BUILD] Building WebHarvest Desktop for {system} ...")

    _ensure_deps()

    # Clean previous builds
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d)

    # --- Collect hidden imports ---
    # PyInstaller misses many dynamically-imported packages.
    # This list was verified by auditing dist/_internal after build.
    hidden_imports = [
        # --- WebHarvest core ---
        "webharvest",
        "webharvest.server",
        "webharvest.config",
        "webharvest.models",
        "webharvest.pipeline",
        "webharvest.pipeline.crawler",
        "webharvest.fetchers",
        "webharvest.downloader",
        "webharvest.extractors",
        "webharvest.cli",
        # --- Uvicorn ---
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        # --- FastAPI / Starlette ---
        "fastapi",
        "starlette",
        "starlette.routing",
        "starlette.middleware",
        "starlette.responses",
        "starlette.staticfiles",
        "starlette.websockets",
        # --- HTTP clients (critical for crawling!) ---
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "httpcore",
        "httpcore._async",
        "httpcore._sync",
        "httpcore._backends",
        "httpcore._backends.auto",
        "httpcore._backends.anyio",
        "h11",
        "h2",
        "hpack",
        "hyperframe",
        # --- Stealth fetcher ---
        "curl_cffi",
        "curl_cffi.requests",
        "cffi",
        "pycparser",
        # --- HTML parser ---
        "selectolax",
        "selectolax.parser",
        # --- HTML / XML parsers ---
        "bs4",
        "lxml",
        # --- Excel ---
        "openpyxl",
        "et_xmlfile",
        # --- Environment ---
        "dotenv",
        # --- Playwright ---
        "playwright",
        "playwright.sync_api",
        "playwright._impl",
        "pyee",
        # --- Async frameworks ---
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        "sniffio",
        # --- Network / encoding ---
        "idna",
        "charset_normalizer",
        "certifi",
        "socksio",
        # --- Starlette extras ---
        "wsproto",
        "multipart",
        # --- CLI / Utilities ---
        "click",
        "rich",
        "rich.console",
        "rich.progress",
        "typing_extensions",
        # --- UI framework & .NET bridge ---
        "webview",
        "clr",
        "pythonnet",
    ]

    # --- Collect-all: ensures ALL submodules + data files are bundled ---
    collect_all_packages = [
        "httpx",
        "httpcore",
        "curl_cffi",
        "anyio",
        "certifi",
        "h11",
        "sniffio",
        "idna",
        "charset_normalizer",
        "click",
        "rich",
        "h2",
        "hpack",
        "hyperframe",
        "wsproto",
        "socksio",
        "webview",
        "clr",
        "pythonnet",
        "playwright",
        "pyee",
        "openpyxl",
        "lxml",
        "bs4",
    ]

    # --- Collect data files ---
    static_dir = ROOT / "webharvest" / "static"
    datas = [
        (str(static_dir), "webharvest/static"),
    ]

    # --- Build PyInstaller command ---
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "WebHarvest",
        "--noconfirm",
        "--clean",
    ]

    # One-file vs one-folder
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    # Console mode — run without console window to hide the command prompt (cmd)
    cmd.append("--noconsole")

    # Icon
    icon = _get_icon_path()
    if icon:
        cmd.extend(["--icon", icon])

    # Hidden imports
    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    # Collect-all: bundle ALL submodules + data files for critical packages
    for pkg in collect_all_packages:
        cmd.extend(["--collect-all", pkg])

    # Data files
    sep = ";" if system == "Windows" else ":"
    for src, dest in datas:
        cmd.extend(["--add-data", f"{src}{sep}{dest}"])

    # Entry point
    cmd.append(str(ROOT / "main_desktop.py"))

    _run(cmd, cwd=str(ROOT))

    # --- Post-build summary ---
    if onefile:
        exe_name = "WebHarvest.exe" if system == "Windows" else "WebHarvest"
        output = DIST / exe_name
    else:
        output = DIST / "WebHarvest"

    if output.exists():
        if output.is_file():
            size_mb = output.stat().st_size / (1024 * 1024)
            print(f"\n[OK] Build successful! Output: {output} ({size_mb:.1f} MB)")
        else:
            total = sum(f.stat().st_size for f in output.rglob("*") if f.is_file())
            size_mb = total / (1024 * 1024)
            print(f"\n[OK] Build successful! Output folder: {output} ({size_mb:.1f} MB total)")
        print(f"   Run with: {output / 'WebHarvest.exe' if not onefile else output}")
    else:
        print("\n[FAIL] Build may have failed -- output not found.")
        sys.exit(1)


if __name__ == "__main__":
    onefile = "--onefile" in sys.argv
    build(onefile=onefile)
