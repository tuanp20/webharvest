"""
WebHarvest CLI — intuitive command-line interface.

Inspired by gallery-dl's subcommand design:

    webharvest download <url> -o ./output
    webharvest crawl <url> --depth 3
    webharvest gallery <url> --concurrent 10
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Dict

from webharvest import __version__
from webharvest.config import CrawlConfig, FetcherType
from webharvest.pipeline.crawler import CrawlPipeline, CrawlResult


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------
class ProgressDisplay:
    """Terminal progress callbacks for the CLI."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def __call__(self, event: str, data: Dict[str, Any]):
        if event == "crawl_start":
            print(f"[CRAWL] Starting crawl: {data['url']} (fetcher: {data['fetcher']})")

        elif event == "page_fetch":
            if self.verbose:
                print(f"  [FETCH] Fetching: {data['url']}")

        elif event == "page_parsed":
            if self.verbose:
                print(f"  [OK] Parsed: {data['url']} — {data['images']} images, {data['links']} links")

        elif event == "js_detected":
            print("  [JS] JS content detected, upgrading to dynamic fetcher")

        elif event == "antibot_detected":
            print("  [STEALTH] Anti-bot detected, upgrading to stealth fetcher")

        elif event == "next_page":
            print(f"  [PAGINATION] Following pagination: {data['url']}")

        elif event == "gallery_empty":
            print("  [INFO] No more images found, stopping pagination")

        elif event == "download_start":
            print(f"[DOWNLOAD] Downloading {data['count']} images...")

        elif event == "image_downloaded":
            size_kb = data['size'] / 1024
            print(f"  [+] {data['progress']} — {size_kb:.1f} KB — {data['url'][:80]}")

        elif event == "download_done":
            print(f"\n[DONE] Downloaded: {data['downloaded']}, Failed: {data['failed']}")

        elif event == "crawl_done":
            r = data["result"]
            print("\n" + r.summary())


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _build_config(args: argparse.Namespace, mode: str = "crawl") -> CrawlConfig:
    """Build CrawlConfig from parsed CLI arguments."""
    kwargs = {
        "url": args.url,
        "output_dir": args.output,
        "depth": args.depth,
        "max_pages": args.max_pages,
        "concurrent_downloads": args.concurrent,
        "min_file_size": args.min_size,
    }

    if args.format:
        kwargs["allowed_formats"] = set(args.format.split(","))

    if args.stealth:
        kwargs["fetcher"] = FetcherType.STEALTH
    elif args.dynamic:
        kwargs["fetcher"] = FetcherType.DYNAMIC
    else:
        kwargs["fetcher"] = FetcherType.AUTO

    if mode == "download":
        kwargs["depth"] = 0
    elif mode == "gallery":
        kwargs["gallery_mode"] = True
        kwargs["depth"] = 0
        if args.next_selector:
            kwargs["pagination_selectors"] = [args.next_selector]

    if args.proxy:
        kwargs["proxy"] = args.proxy

    if args.delay is not None:
        kwargs["request_delay"] = args.delay

    return CrawlConfig(**kwargs)


def _run_pipeline(config: CrawlConfig, verbose: bool = False) -> CrawlResult:
    """Run the async pipeline from sync CLI context."""
    display = ProgressDisplay(verbose=verbose)
    pipeline = CrawlPipeline(config, on_progress=display)
    return asyncio.run(pipeline.run())


def cmd_download(args: argparse.Namespace):
    """Handle `webharvest download <url>`."""
    config = _build_config(args, mode="download")
    result = _run_pipeline(config, verbose=args.verbose)
    return 0 if result.images_failed == 0 else 1


def cmd_crawl(args: argparse.Namespace):
    """Handle `webharvest crawl <url>`."""
    config = _build_config(args, mode="crawl")
    result = _run_pipeline(config, verbose=args.verbose)
    return 0 if result.images_failed == 0 else 1


def cmd_gallery(args: argparse.Namespace):
    """Handle `webharvest gallery <url>`."""
    config = _build_config(args, mode="gallery")
    result = _run_pipeline(config, verbose=args.verbose)
    return 0 if result.images_failed == 0 else 1


def cmd_server(args: argparse.Namespace):
    """Handle `webharvest server`."""
    import uvicorn
    print(f"[SERVER] Starting WebHarvest Web UI at http://{args.host}:{args.port}")
    uvicorn.run("webharvest.server:app", host=args.host, port=args.port, log_level="info")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _add_common_args(parser: argparse.ArgumentParser):
    """Add shared CLI options to a subparser."""
    g = parser.add_argument_group("general")
    g.add_argument("url", help="Target URL to scrape")
    g.add_argument("-o", "--output", default="./output", help="Output directory (default: ./output)")
    g.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    g = parser.add_argument_group("crawl settings")
    g.add_argument("-d", "--depth", type=int, default=1, help="Link-following depth (default: 1)")
    g.add_argument("-n", "--max-pages", type=int, default=100, help="Maximum pages to visit (default: 100)")
    g.add_argument("-c", "--concurrent", type=int, default=5, help="Concurrent downloads (default: 5)")
    g.add_argument("--delay", type=float, default=None, help="Delay between requests in seconds")

    g = parser.add_argument_group("image filters")
    g.add_argument("-s", "--min-size", type=int, default=0, help="Minimum file size in bytes")
    g.add_argument("-f", "--format", type=str, default=None,
                   help="Comma-separated image formats (e.g. jpg,png,webp)")

    g = parser.add_argument_group("fetcher options")
    g.add_argument("--stealth", action="store_true", help="Use stealth browser fetcher")
    g.add_argument("--dynamic", action="store_true", help="Use dynamic (Playwright) fetcher")

    g = parser.add_argument_group("network")
    g.add_argument("--proxy", type=str, default=None, help="Proxy URL (http://host:port)")


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser."""
    parser = argparse.ArgumentParser(
        prog="webharvest",
        description="WebHarvest — async web scraper and image downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  webharvest download https://example.com/photos -o ./photos
  webharvest crawl https://blog.example.com --depth 3 --max-pages 50
  webharvest gallery https://imgur.com/a/abc123 --concurrent 10
  webharvest download https://example.com --stealth -f png,webp
  webharvest server --port 8000
        """,
    )
    parser.add_argument("--version", action="version", version=f"webharvest {__version__}")

    sub = parser.add_subparsers(dest="command", help="Command to run")

    # download
    p_dl = sub.add_parser("download", help="Download all images from a URL")
    _add_common_args(p_dl)
    p_dl.set_defaults(func=cmd_download)

    # crawl
    p_crawl = sub.add_parser("crawl", help="Crawl site and extract data")
    _add_common_args(p_crawl)
    p_crawl.set_defaults(func=cmd_crawl)

    # gallery
    p_gal = sub.add_parser("gallery", help="Gallery/album mode with pagination")
    _add_common_args(p_gal)
    p_gal.add_argument("--next-selector", type=str, default=None,
                       help="CSS selector for next-page link")
    p_gal.set_defaults(func=cmd_gallery)

    # server
    p_srv = sub.add_parser("server", help="Start the Web UI server")
    p_srv.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    p_srv.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    p_srv.set_defaults(func=cmd_server)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    # Configure logging
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted.")
        return 130
    except Exception as exc:
        print(f"[ERROR] Error: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
