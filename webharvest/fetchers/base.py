"""
Base fetcher with rate limiting, user-agent rotation, proxy rotation,
retry logic, session management, and headers randomization.

Uses requests for standard HTTP and curl_cffi for TLS fingerprint impersonation.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import requests
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("webharvest.fetchers.base")

# ---------------------------------------------------------------------------
# TLS fingerprint impersonation via curl_cffi (optional dependency)
# ---------------------------------------------------------------------------
try:
    from curl_cffi import requests as curl_requests

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    logger.debug("curl_cffi not installed; TLS fingerprint impersonation unavailable")

# ---------------------------------------------------------------------------
# Default user-agent pool (desktop Chrome / Firefox / Safari / Edge variants)
# ---------------------------------------------------------------------------
DEFAULT_USER_AGENTS: List[str] = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    # Firefox macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Firefox Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Chrome Android (mobile)
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.71 Mobile Safari/537.36",
]

# curl_cffi impersonation targets (TLS fingerprint profiles)
CURL_IMPERSONATE_TARGETS: List[str] = [
    "chrome124",
    "chrome120",
    "chrome116",
    "safari17_0",
    "safari15_5",
    "edge101",
    "firefox120",
]


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------
@dataclass
class FetchResponse:
    """Unified response object returned by all fetcher types."""

    html: str
    status_code: int
    headers: Dict[str, str]
    url: str  # final URL (after redirects)
    content: bytes = b""
    encoding: Optional[str] = None
    elapsed: float = 0.0  # seconds
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        """Alias for html."""
        return self.html

    def json(self) -> Any:
        """Parse response body as JSON."""
        import json as _json

        return _json.loads(self.html)

    def __repr__(self) -> str:
        return (
            f"FetchResponse(status={self.status_code}, url={self.url!r}, "
            f"len(html)={len(self.html)})"
        )


# ---------------------------------------------------------------------------
# Rate limiter (token-bucket, thread-safe)
# ---------------------------------------------------------------------------
class _TokenBucketRateLimiter:
    """Simple token-bucket rate limiter.

    Parameters
    ----------
    rate : float
        Maximum requests per second.
    burst : int
        Maximum burst size (tokens that can accumulate).
    """

    def __init__(self, rate: float = 2.0, burst: int = 5) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Proxy rotator
# ---------------------------------------------------------------------------
class _ProxyRotator:
    """Round-robin proxy selector with optional per-request rotation."""

    def __init__(self, proxies: Optional[Sequence[str]] = None) -> None:
        # Each proxy is a URL like "http://user:pass@host:port" or "socks5://..."
        self._proxies: List[str] = list(proxies) if proxies else []
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> Optional[Dict[str, str]]:
        """Return a requests-compatible proxies dict, or None."""
        if not self._proxies:
            return None
        with self._lock:
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
        return {"http": proxy, "https": proxy}

    def reset(self, proxies: Sequence[str]) -> None:
        with self._lock:
            self._proxies = list(proxies)
            self._index = 0


# ---------------------------------------------------------------------------
# BaseFetcher
# ---------------------------------------------------------------------------
class BaseFetcher:
    """Base class for all web fetchers.

    Provides:
    - Automatic user-agent rotation from a pool of realistic browser UAs.
    - Proxy rotation (round-robin).
    - Rate limiting (token bucket).
    - Retry with exponential back-off via *tenacity*.
    - Session management with persistent cookies (``requests.Session``).
    - Optional TLS fingerprint impersonation via ``curl_cffi``.
    - Randomised request headers (Accept, Accept-Language, etc.).

    Subclasses override :meth:`get` / :meth:`post` to implement specific
    fetching strategies (static HTML, headless browser, stealth, etc.).

    Parameters
    ----------
    user_agents : list[str] | None
        Custom UA pool. Falls back to :data:`DEFAULT_USER_AGENTS`.
    proxies : list[str] | None
        Proxy URLs for round-robin rotation.
    rate_limit : float
        Max requests per second (default 2.0).
    rate_burst : int
        Token-bucket burst size (default 5).
    max_retries : int
        Maximum retry attempts for transient failures (default 3).
    timeout : int
        Default request timeout in seconds (default 30).
    impersonate : bool
        Use curl_cffi TLS fingerprint impersonation when available.
    impersonate_target : str | None
        Specific curl_cffi target (e.g. ``"chrome124"``). Random if *None*.
    extra_headers : dict | None
        Additional headers merged into every request.
    """

    def __init__(
        self,
        *,
        user_agents: Optional[List[str]] = None,
        proxies: Optional[List[str]] = None,
        rate_limit: float = 2.0,
        rate_burst: int = 5,
        max_retries: int = 3,
        timeout: int = 30,
        impersonate: bool = False,
        impersonate_target: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._user_agents: List[str] = user_agents or list(DEFAULT_USER_AGENTS)
        self._proxies = _ProxyRotator(proxies)
        self._rate_limiter = _TokenBucketRateLimiter(rate=rate_limit, burst=rate_burst)
        self._max_retries = max_retries
        self._timeout = timeout
        self._impersonate = impersonate and HAS_CURL_CFFI
        self._impersonate_target = impersonate_target
        self._extra_headers = extra_headers or {}
        self._lock = threading.Lock()

        # Standard requests session (cookies persist across calls)
        self._session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=0,  # we handle retries via tenacity
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        logger.debug(
            "BaseFetcher initialised: impersonate=%s, rate=%.1f/s, proxies=%d, uas=%d",
            self._impersonate,
            rate_limit,
            len(self._proxies._proxies),
            len(self._user_agents),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _pick_user_agent(self) -> str:
        return random.choice(self._user_agents)

    def _pick_impersonate_target(self) -> str:
        if self._impersonate_target:
            return self._impersonate_target
        return random.choice(CURL_IMPERSONATE_TARGETS)

    def _randomise_headers(self) -> Dict[str, str]:
        """Return a dict of realistic, randomised browser headers."""
        ua = self._pick_user_agent()
        # Randomly pick an Accept-Language
        languages = [
            "en-US,en;q=0.9",
            "en-GB,en;q=0.9",
            "en-US,en;q=0.9,fr;q=0.8",
            "en-US,en;q=0.9,de;q=0.8",
            "en-US,en;q=0.9,es;q=0.8",
            "en-US,en;q=0.9,ja;q=0.8",
            "en-US,en;q=0.9,zh-CN;q=0.8",
        ]
        # Vary Accept slightly
        accepts = [
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        ]
        encodings = ["gzip, deflate, br", "gzip, deflate"]

        headers: Dict[str, str] = {
            "User-Agent": ua,
            "Accept": random.choice(accepts),
            "Accept-Language": random.choice(languages),
            "Accept-Encoding": random.choice(encodings),
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        headers.update(self._extra_headers)
        return headers

    # ------------------------------------------------------------------
    # HTTP verbs (subclasses should call these or override)
    # ------------------------------------------------------------------
    def _do_request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        params: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        timeout: Optional[int] = None,
    ) -> FetchResponse:
        """Execute an HTTP request with rate-limiting, UA rotation, proxy rotation, retries.

        This is the core request method that subclasses can call or override.
        """
        timeout = timeout or self._timeout
        merged_headers = self._randomise_headers()
        if headers:
            merged_headers.update(headers)

        # Build a retry-decorated callable
        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(
                (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
            ),
            reraise=True,
        )
        def _send() -> requests.Response:
            self._rate_limiter.acquire()
            proxy_map = self._proxies.next()
            kwargs: Dict[str, Any] = {
                "method": method,
                "url": url,
                "headers": merged_headers,
                "timeout": timeout,
                "allow_redirects": follow_redirects,
            }
            if data is not None:
                kwargs["data"] = data
            if json is not None:
                kwargs["json"] = json
            if params is not None:
                kwargs["params"] = params
            if proxy_map:
                kwargs["proxies"] = proxy_map

            resp = self._session.request(**kwargs)
            # Return response regardless of status code so callers can
            # inspect resp.ok / resp.status_code and decide on fallback
            # strategies (e.g. upgrading to StealthFetcher on 403).
            return resp

        t0 = time.monotonic()
        resp = _send()
        elapsed = time.monotonic() - t0

        return FetchResponse(
            html=resp.text,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            url=resp.url,
            content=resp.content,
            encoding=resp.encoding,
            elapsed=elapsed,
        )

    def _do_curl_request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        follow_redirects: bool = True,
    ) -> FetchResponse:
        """Execute via curl_cffi with TLS fingerprint impersonation."""
        if not HAS_CURL_CFFI:
            raise RuntimeError("curl_cffi is not installed – cannot impersonate TLS fingerprint")

        timeout = timeout or self._timeout
        merged_headers = self._randomise_headers()
        if headers:
            merged_headers.update(headers)

        target = self._pick_impersonate_target()
        proxy_map = self._proxies.next()

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError)),
            reraise=True,
        )
        def _send() -> Any:
            self._rate_limiter.acquire()
            kwargs: Dict[str, Any] = {
                "method": method,
                "url": url,
                "headers": merged_headers,
                "timeout": timeout,
                "allow_redirects": follow_redirects,
                "impersonate": target,
            }
            if data is not None:
                kwargs["data"] = data
            if json is not None:
                kwargs["json"] = json
            if params is not None:
                kwargs["params"] = params
            if proxy_map:
                kwargs["proxies"] = proxy_map
            return curl_requests.request(**kwargs)

        t0 = time.monotonic()
        resp = _send()
        elapsed = time.monotonic() - t0

        return FetchResponse(
            html=resp.text,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            url=str(resp.url),
            content=resp.content,
            encoding=resp.encoding,
            elapsed=elapsed,
        )

    # ------------------------------------------------------------------
    # Public API (to be overridden by subclasses)
    # ------------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        timeout: Optional[int] = None,
    ) -> FetchResponse:
        """Fetch a URL via GET. Override in subclasses."""
        method_fn = self._do_curl_request if self._impersonate else self._do_request
        return method_fn(
            "GET", url, headers=headers, params=params,
            follow_redirects=follow_redirects, timeout=timeout,
        )

    def post(
        self,
        url: str,
        *,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        timeout: Optional[int] = None,
    ) -> FetchResponse:
        """Fetch a URL via POST. Override in subclasses."""
        method_fn = self._do_curl_request if self._impersonate else self._do_request
        return method_fn(
            "POST", url, headers=headers, data=data, json=json,
            follow_redirects=follow_redirects, timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    def clear_cookies(self) -> None:
        """Clear all cookies from the underlying session."""
        self._session.cookies.clear()
        logger.debug("Cookies cleared")

    def set_cookies(self, cookies: Dict[str, str], domain: str = "") -> None:
        """Inject cookies into the session."""
        for name, value in cookies.items():
            self._session.cookies.set(name, value, domain=domain)
        logger.debug("Set %d cookies for domain %r", len(cookies), domain)

    def get_cookies(self) -> Dict[str, str]:
        """Return current session cookies as a plain dict."""
        return {c.name: c.value for c in self._session.cookies}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Close the underlying session / release resources."""
        self._session.close()
        logger.debug("BaseFetcher session closed")

    def __enter__(self) -> "BaseFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(impersonate={self._impersonate}, "
            f"retries={self._max_retries}, timeout={self._timeout})"
        )
