"""
CrawlPipeline — async BFS crawler with automatic fetcher selection.

Orchestrates:  fetch → parse → extract images → download images

Auto-fetcher selection (inspired by crawl4ai):
  1. Start with StaticFetcher (fastest, httpx)
  2. If content is empty or has JS indicators → upgrade to DynamicFetcher
  3. If anti-bot patterns detected → upgrade to StealthFetcher

BFS crawling (inspired by gallery-dl):
  - Breadth-first with depth limit and max_pages cap
  - Deduplicates URLs
  - Respects same_domain_only and excluded_patterns

Fetcher factory (inspired by scrapling):
  - FetcherType.AUTO selects the best fetcher per-page
  - Falls back gracefully on errors
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from webharvest.config import CrawlConfig, FetcherType

logger = logging.getLogger("webharvest.pipeline")

# ---------------------------------------------------------------------------
# JS / anti-bot indicators
# ---------------------------------------------------------------------------
_JS_INDICATORS = [
    'id="react-root"', 'id="__next"', 'id="__nuxt"',
    'id="vue-app"', 'data-reactroot', 'data-vue-root',
    'window.__INITIAL_STATE__', 'window.__data',
    'single-spa-application', 'class="ember-view"',
]

_ANTIBOT_INDICATORS = [
    "cf-browser-verification", "cf_chl_opt",
    "please verify you are a human",
    "incapsula", "distil", "datadome",
    "perimeterx", "kasada",
    "challenge-platform",
    # Only match actual challenge pages, not config references
    "hcaptcha.com/api.js", "hcaptcha.com/1/api.js",
    "challenges.cloudflare.com/turnstile",
    "google.com/recaptcha/api.js",
    "grecaptcha.execute",
]

_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "tiff", "avif"}
_IMAGE_URL_RE = re.compile(
    r'\bhttps?://[^\s\'"<>]+\.(?:' + "|".join(_IMAGE_EXTENSIONS) + r')\b',
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")\s]+)['"]?\s*\)""", re.IGNORECASE)
_SRCSET_RE = re.compile(r"""([^\s,]+)""")

# Pagination selectors default
_PAGINATION_SELECTORS = [
    'a[rel="next"]',
    '.next a',
    '.pagination .next a',
    'a.next',
    'a.pagination-next',
    'li.next a',
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ImageInfo:
    """Metadata for a single discovered image."""
    url: str
    page_url: str = ""
    width: int = 0
    height: int = 0
    file_size: int = 0
    format: str = ""
    alt_text: str = ""
    local_path: str = ""

    @property
    def extension(self) -> str:
        """Infer file extension from URL or format."""
        if self.format:
            return f".{self.format.lower()}"
        path = urlparse(self.url).path
        ext = Path(path).suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"):
            return ext
        return ".jpg"  # fallback


@dataclass
class PageData:
    """Extracted data from a single page."""
    url: str
    title: str = ""
    html: str = ""
    images: List[ImageInfo] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    next_page_url: Optional[str] = None
    fetcher_used: str = ""
    status_code: int = 0
    error: Optional[str] = None


@dataclass
class CrawlResult:
    """Aggregate result of a full crawl/download session."""
    start_url: str = ""
    pages_visited: int = 0
    images_found: int = 0
    images_downloaded: int = 0
    images_failed: int = 0
    total_bytes: int = 0
    elapsed_seconds: float = 0.0
    pages: List[PageData] = field(default_factory=list)
    downloaded_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "WebHarvest Crawl Result",
            f"  URL:            {self.start_url}",
            f"  Pages visited:  {self.pages_visited}",
            f"  Images found:   {self.images_found}",
            f"  Downloaded:     {self.images_downloaded}",
            f"  Failed:         {self.images_failed}",
            f"  Total bytes:    {self._human_bytes(self.total_bytes)}",
            f"  Time:           {self.elapsed_seconds:.1f}s",
        ]
        return "\n".join(lines)

    @staticmethod
    def _human_bytes(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if abs(n) < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# Fetcher abstractions
# ---------------------------------------------------------------------------
class BaseFetcher:
    """Abstract base for page fetchers."""

    name: str = "base"

    async def fetch(self, url: str, config: CrawlConfig) -> Tuple[str, int]:
        """Return (html_content, status_code)."""
        raise NotImplementedError

    async def close(self):
        pass


class StaticFetcher(BaseFetcher):
    """Fast httpx-based fetcher for static sites."""

    name = "static"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, config: CrawlConfig) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": config.user_agent, **config.headers}
            self._client = httpx.AsyncClient(
                headers=headers,
                cookies=config.cookies,
                proxy=config.proxy,
                timeout=config.timeout,
                follow_redirects=config.follow_redirects,
                verify=config.verify_ssl,
            )
        return self._client

    async def fetch(self, url: str, config: CrawlConfig) -> Tuple[str, int]:
        client = await self._get_client(config)
        for attempt in range(config.retry_count):
            try:
                resp = await client.get(url)
                if resp.status_code == 429:
                    if attempt < config.retry_count - 1:
                        backoff = 2 ** (attempt + 1)
                        logger.warning("StaticFetcher: rate limited (429) for %s. Retrying in %ds (attempt %d/%d)...",
                                       url, backoff, attempt + 1, config.retry_count)
                        await asyncio.sleep(backoff)
                        continue
                # Retry on 5xx server errors with exponential backoff
                if resp.status_code >= 500 and attempt < config.retry_count - 1:
                    wait = min(2 ** attempt, 10)  # 1s, 2s, 4s max 10s
                    logger.warning("StaticFetcher: server error %d for %s, retrying in %ds (attempt %d/%d)...",
                                   resp.status_code, url, wait, attempt + 1, config.retry_count)
                    await asyncio.sleep(wait)
                    continue
                return resp.text, resp.status_code
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                if attempt == config.retry_count - 1:
                    logger.warning("StaticFetcher failed for %s: %s", url, exc)
                    return "", 0
                backoff = 1 * (attempt + 1)
                await asyncio.sleep(backoff)
        return "", 0

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class DynamicFetcher(BaseFetcher):
    """Playwright-based fetcher for JavaScript-heavy sites.

    Falls back to httpx when Playwright is not installed.
    """

    name = "dynamic"

    def __init__(self):
        self._static = StaticFetcher()

    async def fetch(self, url: str, config: CrawlConfig) -> Tuple[str, int]:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError:
            logger.info("Playwright not installed — falling back to static fetcher")
            return await self._static.fetch(url, config)

        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=config.user_agent,
                    proxy={"server": config.proxy} if config.proxy else None,
                )
                page = await ctx.new_page()
                resp = await page.goto(url, wait_until="networkidle", timeout=int(config.timeout * 1000))
                status = resp.status if resp else 0
                html = await page.content()
                await browser.close()
                return html, status
        except Exception as exc:
            logger.warning("DynamicFetcher failed for %s: %s — falling back to static", url, exc)
            return await self._static.fetch(url, config)

    async def close(self):
        await self._static.close()


class StealthFetcher(BaseFetcher):
    """Stealth fetcher using curl_cffi TLS impersonation to bypass anti-bot.

    Strategy:
      1. Try curl_cffi with multiple real-browser TLS fingerprints in priority
         order (Safari profiles work best against DataDome/Cloudflare).
      2. Each target is tried independently — if one gets a challenge page,
         the next target is attempted.
      3. Final fallback: StaticFetcher (Playwright is skipped on Windows
         because asyncio subprocess_exec fails inside uvicorn's event loop).
    """

    name = "stealth"

    # Ordered by bypass success rate (safari first, then chrome, then edge)
    _IMPERSONATE_TARGETS = [
        "safari17_0", "safari15_5",
        "chrome124", "chrome120", "chrome116",
        "edge101",
    ]

    # Indicators that the response is a bot-challenge page
    _CHALLENGE_INDICATORS = [
        "captcha-delivery.com", "geo.captcha-delivery.com",
        "challenges.cloudflare.com", "cf-browser-verification",
        "just a moment", "cf_chl_opt", "datadome",
        "perimeterx", "px-captcha",
    ]

    def __init__(self):
        self._static_fallback = StaticFetcher()

    def _is_challenge_page(self, html: str) -> bool:
        """Detect if the response is a bot-challenge / captcha page."""
        if not html or len(html.strip()) < 500:
            lower = (html or "").lower()
            return any(ind in lower for ind in self._CHALLENGE_INDICATORS)
        lower = html[:5000].lower()
        return any(ind in lower for ind in self._CHALLENGE_INDICATORS)

    async def _fetch_with_target(self, url: str, config: CrawlConfig, target: str) -> Tuple[str, int]:
        """Fetch using curl_cffi with a specific TLS impersonation target."""
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            logger.warning("curl_cffi not installed — cannot use TLS impersonation")
            return "", 0

        # Don't override User-Agent when using impersonation — curl_cffi sets its own
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        # Run synchronous curl_cffi in a thread to avoid blocking the event loop
        def _sync_fetch():
            import traceback
            import time
            for attempt in range(config.retry_count):
                try:
                    logger.warning("[curl_cffi] Attempting %s with target=%s (attempt %d/%d)", url, target, attempt + 1, config.retry_count)
                    resp = curl_requests.get(
                        url,
                        headers=headers,
                        impersonate=target,
                        timeout=config.timeout,
                        allow_redirects=True,
                        verify=config.verify_ssl,
                        proxies={"https": config.proxy, "http": config.proxy} if config.proxy else None,
                    )
                    logger.warning("[curl_cffi] %s → status=%d, len=%d", target, resp.status_code, len(resp.text))
                    if resp.status_code == 429:
                        if attempt < config.retry_count - 1:
                            backoff = 2 ** (attempt + 1)
                            logger.warning("[curl_cffi] Rate limited (429) for %s. Retrying in %ds...", url, backoff)
                            time.sleep(backoff)
                            continue
                    return resp.text, resp.status_code
                except Exception as exc:
                    logger.warning("[curl_cffi] %s EXCEPTION for %s: %s\n%s", target, url, exc, traceback.format_exc())
                    if attempt < config.retry_count - 1:
                        backoff = 2 ** (attempt + 1)
                        time.sleep(backoff)
                        continue
                    return "", 0
            return "", 0

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_fetch)

    async def fetch(self, url: str, config: CrawlConfig) -> Tuple[str, int]:
        logger.warning("StealthFetcher: starting multi-target TLS bypass for %s", url)
        # Try each impersonation target in priority order
        for target in self._IMPERSONATE_TARGETS:
            logger.warning("StealthFetcher: trying curl_cffi [%s] for %s", target, url)
            html, status = await self._fetch_with_target(url, config, target)

            if html and status and 200 <= status < 400 and not self._is_challenge_page(html):
                logger.warning(
                    "StealthFetcher: curl_cffi [%s] SUCCEEDED (status=%d, len=%d)",
                    target, status, len(html),
                )
                return html, status

            if html and self._is_challenge_page(html):
                logger.warning("StealthFetcher: curl_cffi [%s] got challenge page (status=%d), trying next", target, status)
            elif not html:
                logger.warning("StealthFetcher: curl_cffi [%s] returned empty/error, trying next", target)
            else:
                logger.warning("StealthFetcher: curl_cffi [%s] got status %d, trying next", target, status)

        # All curl_cffi targets exhausted — fall back to static fetcher
        logger.warning("StealthFetcher: all TLS impersonation targets failed, falling back to static fetcher")
        return await self._static_fallback.fetch(url, config)

    async def close(self):
        await self._static_fallback.close()


# ---------------------------------------------------------------------------
# Fetcher factory
# ---------------------------------------------------------------------------
def _create_fetcher(fetcher_type: FetcherType) -> BaseFetcher:
    """Instantiate the appropriate fetcher (scrapling factory pattern)."""
    mapping = {
        FetcherType.STATIC: StaticFetcher,
        FetcherType.DYNAMIC: DynamicFetcher,
        FetcherType.STEALTH: StealthFetcher,
        FetcherType.AUTO: StaticFetcher,  # Start with static; upgrade per-page
    }
    cls = mapping.get(fetcher_type, StaticFetcher)
    return cls()


def _needs_dynamic(html: str) -> bool:
    """Detect if page content indicates a JS-rendered SPA."""
    if not html or len(html.strip()) < 200:
        return True
    lower = html.lower()
    return any(ind in lower for ind in _JS_INDICATORS)


def _detect_antibot(html: str) -> bool:
    """Detect anti-bot / CAPTCHA indicators."""
    lower = html.lower()
    return any(ind in lower for ind in _ANTIBOT_INDICATORS)


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------
def _extract_title(html: str) -> str:
    tree = HTMLParser(html)
    node = tree.css_first("title")
    return node.text(strip=True) if node else ""


def _extract_images(html: str, page_url: str) -> List[ImageInfo]:
    """Extract all <img> elements, srcset, background-image, og:image, and links."""
    tree = HTMLParser(html)
    images: List[ImageInfo] = []
    seen: Set[str] = set()

    def _add(url: str, **kw):
        if url and url not in seen:
            seen.add(url)
            images.append(ImageInfo(url=url, page_url=page_url, **kw))

    # 1. <img> tags — src + all lazy-data attrs
    _lazy_attrs = ("data-src", "data-lazy-src", "data-original", "data-full",
                   "data-hi-res-src", "data-image", "data-bg", "data-large_image")
    for img in tree.css("img"):
        src = img.attributes.get("src", "")
        if not src or src.startswith("data:"):
            for attr in _lazy_attrs:
                src = img.attributes.get(attr, "")
                if src:
                    break
        if not src:
            continue
        abs_url = urljoin(page_url, src)
        w = img.attributes.get("width", "")
        h = img.attributes.get("height", "")
        alt = img.attributes.get("alt", "")
        _add(abs_url, width=int(w) if w and w.isdigit() else 0,
             height=int(h) if h and h.isdigit() else 0, alt_text=alt)

    # 2. srcset on any element (img, source, etc.)
    for el in tree.css("[srcset]"):
        srcset = el.attributes.get("srcset", "")
        for part in srcset.split(","):
            url_part = part.strip().split()[0] if part.strip() else ""
            if url_part:
                _add(urljoin(page_url, url_part))

    # 3. data-srcset
    for el in tree.css("[data-srcset]"):
        srcset = el.attributes.get("data-srcset", "")
        for part in srcset.split(","):
            url_part = part.strip().split()[0] if part.strip() else ""
            if url_part:
                _add(urljoin(page_url, url_part))

    # 4. background-image in style attributes
    for el in tree.css("[style]"):
        style = el.attributes.get("style", "") or ""
        for match in _CSS_URL_RE.finditer(style):
            _add(urljoin(page_url, match.group(1)))

    # 5. <a> links to image files
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if not href:
            continue
        abs_url = urljoin(page_url, href)
        ext = Path(urlparse(abs_url).path).suffix.lstrip(".").lower()
        if ext in _IMAGE_EXTENSIONS:
            _add(abs_url)

    # 6. <meta og:image> / twitter:image
    for meta in tree.css('meta[property="og:image"], meta[property="twitter:image"], meta[name="twitter:image"]'):
        content = meta.attributes.get("content", "")
        if content:
            _add(urljoin(page_url, content))

    # 7. CSS background-image in <style> blocks
    for style_tag in tree.css("style"):
        text = style_tag.text() or ""
        for match in _CSS_URL_RE.finditer(text):
            _add(urljoin(page_url, match.group(1)))

    return images


def _extract_links(html: str, page_url: str, config: CrawlConfig) -> List[str]:
    """Extract and filter page links."""
    tree = HTMLParser(html)
    links: Set[str] = set()
    base_domain = urlparse(page_url).netloc

    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        # Normalize: resolve relative URL, strip fragment only, keep query params
        abs_url = _normalize_url(href, page_url)
        parsed = urlparse(abs_url)

        if not parsed.scheme.startswith("http"):
            continue

        # Domain filtering
        if config.same_domain_only and parsed.netloc != base_domain:
            continue
        if config.allowed_domains and parsed.netloc not in config.allowed_domains:
            continue

        # Excluded patterns
        if any(pat in abs_url for pat in config.excluded_patterns):
            continue

        # Skip common non-page URLs
        ext = Path(parsed.path).suffix.lstrip(".").lower()
        if ext in _IMAGE_EXTENSIONS | {"css", "js", "json", "xml", "pdf", "zip", "mp4", "mp3"}:
            continue

        links.add(abs_url)

    return list(links)


def _extract_pagination_link(html: str, page_url: str, selectors: List[str]) -> Optional[str]:
    """Find next-page URL for gallery pagination."""
    tree = HTMLParser(html)
    for sel in selectors:
        node = tree.css_first(sel)
        if node:
            href = node.attributes.get("href", "")
            if href:
                return urljoin(page_url, href)
    return None


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------
def _normalize_url(url: str, page_url: str = '') -> str:
    """Normalize URL: resolve relative, remove fragment, keep query params."""
    if page_url:
        url = urljoin(page_url, url)
    parsed = urlparse(url)
    # Only strip fragment (#), keep query (?key=value)
    normalized = urlunparse(parsed._replace(fragment=''))
    return normalized


# ---------------------------------------------------------------------------
# robots.txt checker
# ---------------------------------------------------------------------------
class RobotsChecker:
    """Cache and check robots.txt for multiple domains."""

    def __init__(self):
        self._cache: dict[str, Optional[RobotFileParser]] = {}

    def can_fetch(self, url: str, user_agent: str = '*') -> bool:
        """Check if *url* is allowed by the domain's robots.txt.

        This is a synchronous method — call via ``asyncio.to_thread`` from
        async code so the blocking ``rp.read()`` doesn't stall the loop.
        """
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        if domain not in self._cache:
            rp = RobotFileParser()
            rp.set_url(f"{domain}/robots.txt")
            try:
                rp.read()
            except Exception:
                # If robots.txt can't be read, allow access
                self._cache[domain] = None
                return True
            self._cache[domain] = rp

        checker = self._cache.get(domain)
        if checker is None:
            return True
        return checker.can_fetch(user_agent, url)


# ---------------------------------------------------------------------------
# Progress callback type
# ---------------------------------------------------------------------------
ProgressCallback = Callable[[str, Dict[str, Any]], None]


# ---------------------------------------------------------------------------
# CrawlPipeline
# ---------------------------------------------------------------------------
class CrawlPipeline:
    """
    Async BFS crawler that orchestrates the full scrape workflow.

    Usage::

        config = CrawlConfig(url="https://example.com", depth=2)
        pipeline = CrawlPipeline(config)
        result = await pipeline.run()
        print(result.summary())
    """

    def __init__(self, config: CrawlConfig, on_progress: Optional[ProgressCallback] = None, backup_proxies: Optional[List[str]] = None):
        self.config = config
        self.on_progress = on_progress or (lambda event, data: None)
        self._backup_proxies: List[str] = backup_proxies or []
        self._proxy_activated: bool = False  # True once we switched to a working proxy

        # Internal state
        self._fetcher: Optional[BaseFetcher] = None
        self._visited: Set[str] = set()
        self._image_urls_seen: Set[str] = set()
        self._queue: deque = deque()  # (url, depth)
        self._download_semaphore: Optional[asyncio.Semaphore] = None
        self._download_lock: asyncio.Lock = asyncio.Lock()
        self._robots_checker: Optional[RobotsChecker] = (
            RobotsChecker() if config.respect_robots_txt else None
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(self) -> CrawlResult:
        """Execute the full crawl pipeline."""
        result = CrawlResult(start_url=self.config.url)
        t0 = time.monotonic()

        self._download_semaphore = asyncio.Semaphore(self.config.concurrent_downloads)
        self._queue.clear()
        self._visited.clear()
        self._image_urls_seen.clear()

        # Select initial fetcher
        self._fetcher = _create_fetcher(self.config.fetcher)
        self._emit("crawl_start", {"url": self.config.url, "fetcher": self._fetcher.name})

        try:
            if self.config.gallery_mode:
                await self._crawl_gallery(result)
            else:
                await self._crawl_bfs(result)
        finally:
            if self._fetcher:
                await self._fetcher.close()
            result.elapsed_seconds = time.monotonic() - t0

        self._emit("crawl_done", {"result": result})
        return result

    # ------------------------------------------------------------------
    # BFS crawling
    # ------------------------------------------------------------------
    async def _crawl_bfs(self, result: CrawlResult):
        """Breadth-first crawl with depth limit."""
        self._queue.append((self.config.url, 0))

        # Collect all pages first, then batch-download images
        all_images: List[ImageInfo] = []

        while self._queue and result.pages_visited < self.config.max_pages:
            # Process in batches for concurrency
            batch: List[Tuple[str, int]] = []
            while self._queue and len(batch) < self.config.concurrent_fetches:
                url, depth = self._queue.popleft()
                if url in self._visited or depth > self.config.depth:
                    continue
                # Check robots.txt before queueing for fetch
                if self._robots_checker:
                    try:
                        allowed = await asyncio.to_thread(
                            self._robots_checker.can_fetch, url, self.config.user_agent,
                        )
                    except Exception:
                        allowed = True  # fail-open
                    if not allowed:
                        logger.info("Blocked by robots.txt: %s", url)
                        continue
                batch.append((url, depth))
                self._visited.add(url)

            if not batch:
                break

            tasks = [self._process_page(url, depth, result) for url, depth in batch]
            page_results = await asyncio.gather(*tasks, return_exceptions=True)

            for pr in page_results:
                if isinstance(pr, Exception):
                    result.errors.append(str(pr))
                    continue
                if isinstance(pr, PageData):
                    all_images.extend(pr.images)

            # Politeness delay
            if self._queue:
                await asyncio.sleep(self.config.request_delay)

        # Filter and download all collected images
        filtered = self._filter_images(all_images)
        result.images_found = len(filtered)
        await self._download_all(filtered, result)

    # ------------------------------------------------------------------
    # Gallery pagination crawl
    # ------------------------------------------------------------------
    async def _crawl_gallery(self, result: CrawlResult):
        """Follow next-page links for gallery/album sites."""
        current_url: Optional[str] = self.config.url
        all_images: List[ImageInfo] = []
        pages_without_images = 0

        while current_url and result.pages_visited < self.config.max_pages:
            if current_url in self._visited:
                break
            # Check robots.txt before fetching
            if self._robots_checker:
                try:
                    allowed = await asyncio.to_thread(
                        self._robots_checker.can_fetch, current_url, self.config.user_agent,
                    )
                except Exception:
                    allowed = True  # fail-open
                if not allowed:
                    logger.info("Blocked by robots.txt: %s", current_url)
                    break
            self._visited.add(current_url)

            page = await self._fetch_and_parse(current_url, result)
            if page is None:
                break

            all_images.extend(page.images)
            if not page.images:
                pages_without_images += 1
            else:
                pages_without_images = 0

            # Stop if 3 consecutive pages with no images
            if pages_without_images >= 3:
                self._emit("gallery_empty", {"url": current_url})
                break

            # Find next page
            current_url = page.next_page_url

            if current_url:
                self._emit("next_page", {"url": current_url})
                await asyncio.sleep(self.config.request_delay)

        # Download all collected images
        filtered = self._filter_images(all_images)
        result.images_found = len(filtered)
        await self._download_all(filtered, result)

    # ------------------------------------------------------------------
    # Page processing
    # ------------------------------------------------------------------
    async def _process_page(self, url: str, depth: int, result: CrawlResult) -> PageData:
        """Fetch a page, extract images and links, enqueue child links."""
        page = await self._fetch_and_parse(url, result)
        if page is None:
            return PageData(url=url, error="Fetch failed")

        # Enqueue child links for BFS
        if depth < self.config.depth:
            for link in page.links:
                if link not in self._visited:
                    self._queue.append((link, depth + 1))

        return page

    async def _fetch_and_parse(self, url: str, result: CrawlResult) -> Optional[PageData]:
        """Fetch one page, auto-upgrade fetcher if needed, parse content.

        Proxy fallback strategy:
          1. First attempt uses current config.proxy (None = local IP).
          2. If fetch fails or anti-bot is detected, iterate through
             self._backup_proxies, re-create the fetcher with each proxy,
             and retry.
          3. On success, lock that proxy for the rest of the session.
        """
        self._emit("page_fetch", {"url": url})

        html, status = await self._fetcher.fetch(url, self.config)
        is_blocked = self._is_fetch_blocked(html, status)

        # --- Proxy fallback (only if we haven't already activated a proxy) ---
        if is_blocked and not self._proxy_activated and self._backup_proxies:
            logger.warning("Local IP appears blocked for %s — starting proxy fallback", url)

            for proxy_url in self._backup_proxies:
                self._emit("proxy_fallback", {"proxy": proxy_url, "url": url})
                logger.info("Trying backup proxy: %s", proxy_url)

                # Swap proxy in config and rebuild the fetcher
                old_proxy = self.config.proxy
                self.config.proxy = proxy_url
                try:
                    await self._fetcher.close()
                except Exception:
                    pass
                self._fetcher = _create_fetcher(self.config.fetcher)

                retry_html, retry_status = await self._fetcher.fetch(url, self.config)
                retry_blocked = self._is_fetch_blocked(retry_html, retry_status)

                if not retry_blocked and retry_html:
                    # This proxy works — keep it for the session
                    html, status = retry_html, retry_status
                    self._proxy_activated = True
                    self._emit("proxy_success", {"proxy": proxy_url})
                    logger.info("Proxy %s succeeded — locking for session", proxy_url)
                    break
                else:
                    # This proxy also failed — restore and try next
                    self.config.proxy = old_proxy
                    logger.warning("Proxy %s also failed, trying next...", proxy_url)
            else:
                # All proxies exhausted
                self._emit("all_proxies_failed", {
                    "message": "Tất cả proxy đều thất bại — không thể truy cập trang",
                    "url": url,
                })
        elif not is_blocked and not self._proxy_activated and self.config.proxy is None:
            # Local IP worked on the first real page
            self._emit("local_ip_success", {"url": url})

        if not html or status == 0:
            result.errors.append(f"Failed to fetch {url}")
            return None

        result.pages_visited += 1

        # Auto-fetcher upgrade logic (crawl4ai pattern)
        if self.config.fetcher == FetcherType.AUTO:
            if _detect_antibot(html):
                self._emit("antibot_detected", {"url": url, "upgrading_to": "stealth"})
                try:
                    await self._fetcher.close()
                    upgraded = _create_fetcher(FetcherType.STEALTH)
                    new_html, new_status = await upgraded.fetch(url, self.config)
                    if new_html and new_status:
                        self._fetcher = upgraded
                        html, status = new_html, new_status
                    else:
                        self._emit("upgrade_failed", {"url": url, "reason": "empty response"})
                except Exception as e:
                    self._emit("upgrade_failed", {"url": url, "reason": str(e)})
            elif _needs_dynamic(html):
                self._emit("js_detected", {"url": url, "upgrading_to": "dynamic"})
                try:
                    await self._fetcher.close()
                    upgraded = _create_fetcher(FetcherType.DYNAMIC)
                    new_html, new_status = await upgraded.fetch(url, self.config)
                    if new_html and new_status:
                        self._fetcher = upgraded
                        html, status = new_html, new_status
                    else:
                        self._emit("upgrade_failed", {"url": url, "reason": "empty response"})
                except Exception as e:
                    self._emit("upgrade_failed", {"url": url, "reason": str(e)})

        # Parse
        title = _extract_title(html)
        images = _extract_images(html, url)
        links = _extract_links(html, url, self.config)
        next_page = None
        if self.config.gallery_mode:
            selectors = self.config.pagination_selectors or _PAGINATION_SELECTORS
            next_page = _extract_pagination_link(html, url, selectors)

        page = PageData(
            url=url,
            title=title,
            html=html,
            images=images,
            links=links,
            next_page_url=next_page,
            fetcher_used=self._fetcher.name,
            status_code=status,
        )
        self._emit("page_parsed", {
            "url": url, "title": title,
            "images": len(images), "links": len(links),
        })
        return page

    def _is_fetch_blocked(self, html: str, status: int) -> bool:
        """Determine if a fetch result indicates IP blocking or anti-bot."""
        if not html or status == 0:
            return True
        if status in (403, 429, 503):
            return True
        if _detect_antibot(html):
            return True
        # Very short response that looks like a challenge
        if len(html.strip()) < 500:
            lower = html.lower()
            challenge_words = ["captcha", "blocked", "denied", "forbidden", "rate limit"]
            if any(w in lower for w in challenge_words):
                return True
        return False

    # ------------------------------------------------------------------
    # Image filtering
    # ------------------------------------------------------------------
    def _filter_images(self, images: List[ImageInfo]) -> List[ImageInfo]:
        """Apply size and format filters, deduplicate."""
        filtered: List[ImageInfo] = []
        seen: Set[str] = set()

        for img in images:
            if img.url in seen:
                continue
            seen.add(img.url)

            ext = Path(urlparse(img.url).path).suffix.lstrip(".").lower()
            if ext and ext not in self.config.allowed_formats:
                continue

            # Size filter (applied post-download via ImageInfo.file_size)
            filtered.append(img)

        return filtered

    # ------------------------------------------------------------------
    # Image downloading
    # ------------------------------------------------------------------
    async def _download_all(self, images: List[ImageInfo], result: CrawlResult):
        """Download images concurrently."""
        if not images:
            return

        self._emit("download_start", {"count": len(images)})

        async with httpx.AsyncClient(
            headers={"User-Agent": self.config.user_agent},
            proxy=self.config.proxy,
            timeout=self.config.timeout,
            follow_redirects=True,
            verify=self.config.verify_ssl,
        ) as client:
            sem = self._download_semaphore
            tasks = [self._download_one(client, img, sem, result) for img in images]
            await asyncio.gather(*tasks, return_exceptions=True)

        self._emit("download_done", {
            "downloaded": result.images_downloaded,
            "failed": result.images_failed,
        })

    async def _download_one(
        self,
        client: httpx.AsyncClient,
        img: ImageInfo,
        sem: asyncio.Semaphore,
        result: CrawlResult,
    ):
        """Download a single image with semaphore control."""
        async with sem:
            # Atomic check-and-reserve under lock to prevent race conditions
            # when multiple tasks download concurrently.
            async with self._download_lock:
                if self.config.max_images and result.images_downloaded >= self.config.max_images:
                    return
                # Reserve the slot before releasing the lock
                result.images_downloaded += 1

            for attempt in range(self.config.retry_count):
                try:
                    resp = await client.get(img.url)
                    if resp.status_code != 200:
                        if attempt == self.config.retry_count - 1:
                            # Give back the reserved slot on failure
                            async with self._download_lock:
                                result.images_downloaded -= 1
                                result.images_failed += 1
                            result.errors.append(f"HTTP {resp.status_code}: {img.url}")
                        continue

                    data = resp.content
                    file_size = len(data)

                    # Min size filter
                    if self.config.min_file_size and file_size < self.config.min_file_size:
                        # Give back the reserved slot
                        async with self._download_lock:
                            result.images_downloaded -= 1
                        return

                    # Determine output path
                    url_hash = hashlib.md5(img.url.encode()).hexdigest()[:8]
                    ext = img.extension
                    # Try to get extension from content-type if missing
                    ct = resp.headers.get("content-type", "")
                    if "png" in ct:
                        ext = ".png"
                    elif "gif" in ct:
                        ext = ".gif"
                    elif "webp" in ct:
                        ext = ".webp"

                    domain = urlparse(img.page_url or img.url).netloc.replace(".", "_")
                    filename = f"{url_hash}{ext}"
                    outdir = Path(self.config.output_dir) / domain
                    if self.config.create_dirs:
                        outdir.mkdir(parents=True, exist_ok=True)

                    filepath = outdir / filename
                    if filepath.exists() and not self.config.overwrite:
                        # Add unique suffix
                        filepath = outdir / f"{url_hash}_{int(time.time())}{ext}"

                    filepath.write_bytes(data)

                    img.file_size = file_size
                    img.local_path = str(filepath)

                    async with self._download_lock:
                        result.total_bytes += file_size
                    result.downloaded_files.append(str(filepath))

                    self._emit("image_downloaded", {
                        "url": img.url,
                        "path": str(filepath),
                        "size": file_size,
                        "progress": f"{result.images_downloaded}/{result.images_found}",
                    })
                    return

                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    if attempt == self.config.retry_count - 1:
                        # Give back the reserved slot on final failure
                        async with self._download_lock:
                            result.images_downloaded -= 1
                            result.images_failed += 1
                        result.errors.append(f"Download failed {img.url}: {exc}")
                    await asyncio.sleep(1 * (attempt + 1))

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------
    def _emit(self, event: str, data: Dict[str, Any]):
        """Call the progress callback."""
        try:
            self.on_progress(event, data)
        except Exception:
            pass  # Never let callback errors break the pipeline
