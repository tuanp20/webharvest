"""
DynamicFetcher – Playwright-based fetcher for JavaScript-rendered pages.

Features:
- Full Chromium / Firefox / WebKit headless browser rendering.
- ``wait_for_selector`` – wait until a specific CSS selector appears.
- ``scroll_to_load`` – trigger infinite-scroll content loading.
- ``execute_js`` – run arbitrary JavaScript in page context.
- Auto-detect when to use: if a static fetch returns empty / JS-gated
  content, switch to this fetcher automatically.

Dependencies: playwright (``pip install playwright && playwright install``)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from .base import BaseFetcher, FetchResponse

logger = logging.getLogger("webharvest.fetchers.dynamic")

# Lazy import so the module can be loaded even without playwright installed.
_PLAYWRIGHT = None  # module-level cache


def _import_playwright():
    global _PLAYWRIGHT
    if _PLAYWRIGHT is None:
        try:
            import playwright as pw
            _PLAYWRIGHT = pw
        except ImportError as exc:
            raise ImportError(
                "playwright is required for DynamicFetcher. "
                "Install it:  pip install playwright && playwright install"
            ) from exc
    return _PLAYWRIGHT


class DynamicFetcher(BaseFetcher):
    """Fetch JavaScript-rendered pages via a real browser (Playwright).

    Each call to :meth:`get` spins up a browser context, navigates to the
    URL, optionally waits for a selector / scrolls, then extracts the
    rendered HTML and returns it wrapped in a :class:`FetchResponse`.

    The browser is launched once and reused across calls.  Call :meth:`close`
    (or exit the context manager) to shut it down.

    Parameters
    ----------
    browser_type : str
        ``"chromium"``, ``"firefox"``, or ``"webkit"`` (default ``"chromium"``).
    headless : bool
        Run headless (default ``True``).
    **kwargs
        Forwarded to :class:`BaseFetcher` (rate-limit, proxies, retries, etc.).
    """

    def __init__(
        self,
        *,
        browser_type: str = "chromium",
        headless: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._browser_type_name = browser_type
        self._headless = headless

        # Playwright objects – lazily initialised
        self._pw: Any = None  # playwright module
        self._browser: Any = None  # Browser instance
        self._browser_context: Any = None  # BrowserContext (reused)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Browser lifecycle (async internals, sync public API)
    # ------------------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create an event loop for async Playwright calls."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def _run(self, coro):
        """Run an async coroutine from sync context."""
        loop = self._ensure_loop()
        return loop.run_until_complete(coro)

    def _ensure_browser(self) -> None:
        """Lazily launch the browser and create a reusable context."""
        if self._browser is not None:
            return

        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright()
        playwright = self._pw.__enter__()

        launcher = getattr(playwright, self._browser_type_name)
        self._browser = launcher.launch(headless=self._headless)
        self._browser_context = self._browser.new_context(
            user_agent=self._pick_user_agent(),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        # Block unnecessary resources for speed
        self._browser_context.route(
            "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,otf}",
            lambda route: route.abort(),
        )
        logger.info(
            "DynamicFetcher: %s browser launched (headless=%s)",
            self._browser_type_name,
            self._headless,
        )

    def get(
        self,
        url: str,
        *,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: Optional[int] = None,
        scroll_to_load: bool = False,
        max_scrolls: int = 20,
        scroll_delay: float = 1.5,
        execute_js: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        cookies: Optional[List[Dict[str, Any]]] = None,
    ) -> FetchResponse:
        """Navigate to *url* in a headless browser and return the rendered HTML.

        Parameters
        ----------
        url : str
            Target URL.
        wait_for_selector : str, optional
            CSS selector to wait for before extracting content.
        wait_for_timeout : int, optional
            Milliseconds to wait after navigation (absolute wait).
        scroll_to_load : bool
            If ``True``, repeatedly scroll to the bottom to trigger
            infinite-scroll loading.
        max_scrolls : int
            Maximum scroll iterations (only when *scroll_to_load* is True).
        scroll_delay : float
            Seconds to pause between scroll attempts.
        execute_js : str, optional
            JavaScript code to execute after the page is ready.  The
            return value is stored in ``response.extra["js_result"]``.
        headers : dict, optional
            Extra HTTP headers (set via Playwright's context).
        timeout : int, optional
            Navigation timeout in milliseconds (default: 60 000).
        cookies : list[dict], optional
            Cookies to inject before navigation.  Each dict should have
            at least ``name``, ``value``, and ``url`` (or ``domain``).

        Returns
        -------
        FetchResponse
            Rendered HTML, final URL, status code, headers, elapsed time.
        """
        self._ensure_browser()
        timeout_ms = (timeout or 60) * 1000

        logger.info("DynamicFetcher GET %s", url)

        # Inject cookies if provided
        if cookies:
            self._browser_context.add_cookies(cookies)

        page = self._browser_context.new_page()
        try:
            # Extra headers
            if headers:
                page.set_extra_http_headers(headers)

            # Navigate
            resp = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            # Wait for a specific selector
            if wait_for_selector:
                page.wait_for_selector(
                    wait_for_selector,
                    timeout=timeout_ms,
                    state="attached",
                )

            # Absolute wait
            if wait_for_timeout:
                page.wait_for_timeout(wait_for_timeout)

            # Infinite scroll
            if scroll_to_load:
                self._scroll_page(page, max_scrolls=max_scrolls, delay=scroll_delay)

            # Execute custom JS
            js_result: Any = None
            if execute_js:
                js_result = page.evaluate(execute_js)

            # Extract content
            html = page.content()
            final_url = page.url
            status = resp.status if resp else 200
            resp_headers: Dict[str, str] = dict(resp.headers) if resp else {}

            extra: Dict[str, Any] = {}
            if js_result is not None:
                extra["js_result"] = js_result

            return FetchResponse(
                html=html,
                status_code=status,
                headers=resp_headers,
                url=final_url,
                content=html.encode("utf-8"),
                encoding="utf-8",
                extra=extra,
            )
        finally:
            page.close()

    def post(
        self,
        url: str,
        *,
        data: Optional[Dict[str, str]] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> FetchResponse:
        """Submit a POST via the browser using ``fetch()`` in page context.

        Navigates to *about:blank*, runs a ``fetch`` call, and returns
        the result as a :class:`FetchResponse`.
        """
        self._ensure_browser()
        timeout_ms = (timeout or 60) * 1000

        page = self._browser_context.new_page()
        try:
            if headers:
                page.set_extra_http_headers(headers)
            page.goto("about:blank", timeout=5000)

            import json as _json

            fetch_opts: Dict[str, Any] = {
                "method": "POST",
                "headers": {"Content-Type": "application/json"}
                if json is not None
                else {"Content-Type": "application/x-www-form-urlencoded"},
            }
            if json is not None:
                fetch_opts["body"] = _json.dumps(json)
            elif data is not None:
                from urllib.parse import urlencode

                fetch_opts["body"] = urlencode(data)

            result = page.evaluate(
                """async (url, opts) => {
                    const resp = await fetch(url, opts);
                    const text = await resp.text();
                    const headers = {};
                    resp.headers.forEach((v, k) => { headers[k] = v; });
                    return { status: resp.status, url: resp.url, headers, text };
                }""",
                url,
                fetch_opts,
            )

            return FetchResponse(
                html=result["text"],
                status_code=result["status"],
                headers=result["headers"],
                url=result["url"],
                content=result["text"].encode("utf-8"),
                encoding="utf-8",
            )
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------
    @staticmethod
    def _scroll_page(page: Any, *, max_scrolls: int = 20, delay: float = 1.5) -> int:
        """Scroll to the bottom of the page repeatedly to trigger lazy loading.

        Returns the number of scrolls performed.
        """
        import time

        previous_height = 0
        scrolls = 0

        for _ in range(max_scrolls):
            current_height = page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(delay)
            previous_height = current_height
            scrolls += 1

        logger.debug("Scrolled %d times, final height=%d", scrolls, previous_height)
        return scrolls

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def execute_js(self, url: str, script: str, **kwargs: Any) -> FetchResponse:
        """Convenience: navigate to *url*, execute *script*, return response."""
        return self.get(url, execute_js=script, **kwargs)

    def screenshot(
        self, url: str, *, path: str = "screenshot.png", full_page: bool = True, **kwargs: Any
    ) -> FetchResponse:
        """Navigate, take a screenshot, then return the rendered HTML."""
        self._ensure_browser()
        page = self._browser_context.new_page()
        try:
            timeout_ms = (kwargs.get("timeout", 60)) * 1000
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if kwargs.get("wait_for_selector"):
                page.wait_for_selector(kwargs["wait_for_selector"], timeout=timeout_ms)
            if kwargs.get("scroll_to_load"):
                self._scroll_page(page, max_scrolls=kwargs.get("max_scrolls", 20))
            page.screenshot(path=path, full_page=full_page)
            html = page.content()
            return FetchResponse(
                html=html,
                status_code=resp.status if resp else 200,
                headers=dict(resp.headers) if resp else {},
                url=page.url,
                content=html.encode("utf-8"),
                encoding="utf-8",
                extra={"screenshot": path},
            )
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Shut down the browser and release resources."""
        if self._browser_context:
            try:
                self._browser_context.close()
            except Exception:
                pass
            self._browser_context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                self._pw.__exit__(None, None, None)
            except Exception:
                pass
            self._pw = None
        super().close()
        logger.info("DynamicFetcher closed")

    def __enter__(self) -> "DynamicFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
