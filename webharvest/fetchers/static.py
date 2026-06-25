"""
StaticFetcher – HTTP-based fetcher for static (server-rendered) pages.

Thin wrapper around :class:`BaseFetcher` that adds:
- Convenience methods :meth:`get` and :meth:`post` with clean signatures.
- Optional auto-detection of pages that need JavaScript rendering
  (returns a response whose ``html`` is empty or suspiciously short).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import BaseFetcher, FetchResponse

logger = logging.getLogger("webharvest.fetchers.static")

# Pages with body shorter than this (after stripping whitespace) are
# considered *empty* – a signal that JS rendering may be needed.
_EMPTY_BODY_THRESHOLD = 200

# Common indicators that the page requires JS execution
_JS_REQUIRED_INDICATORS = [
    "<noscript",
    "enable javascript",
    "javascript is required",
    "please enable js",
]


class StaticFetcher(BaseFetcher):
    """Fetch static HTML pages with plain HTTP requests.

    Inherits rate-limiting, UA rotation, proxy rotation, retry logic,
    and session management from :class:`BaseFetcher`.

    Parameters
    ----------
    **kwargs
        All keyword arguments are forwarded to :class:`BaseFetcher`.
    """

    def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        timeout: Optional[int] = None,
    ) -> FetchResponse:
        """GET-request *url* and return a :class:`FetchResponse`.

        Parameters
        ----------
        url : str
            Target URL.
        headers : dict, optional
            Extra headers merged on top of the randomised defaults.
        params : dict, optional
            Query-string parameters.
        follow_redirects : bool
            Whether to follow HTTP redirects (default ``True``).
        timeout : int, optional
            Per-request timeout in seconds.  Falls back to the
            fetcher-level default.

        Returns
        -------
        FetchResponse
            Response with ``html``, ``status_code``, ``headers``, ``url``.
        """
        logger.info("GET %s", url)
        resp = self._do_request(
            "GET",
            url,
            headers=headers,
            params=params,
            follow_redirects=follow_redirects,
            timeout=timeout,
        )
        if self._looks_empty(resp):
            logger.warning(
                "Response from %s looks empty (%d bytes) – "
                "consider using DynamicFetcher for JS-rendered content",
                url,
                len(resp.html),
            )
        return resp

    def post(
        self,
        url: str,
        *,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        timeout: Optional[int] = None,
    ) -> FetchResponse:
        """POST to *url* and return a :class:`FetchResponse`.

        Parameters
        ----------
        url : str
            Target URL.
        data : Any, optional
            Form-encoded body (string, bytes, or dict).
        json : Any, optional
            JSON body (sets Content-Type automatically).
        headers : dict, optional
            Extra headers.
        params : dict, optional
            Query-string parameters.
        follow_redirects : bool
            Whether to follow HTTP redirects (default ``True``).
        timeout : int, optional
            Per-request timeout in seconds.

        Returns
        -------
        FetchResponse
        """
        logger.info("POST %s", url)
        return self._do_request(
            "POST",
            url,
            headers=headers,
            data=data,
            json=json,
            params=params,
            follow_redirects=follow_redirects,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_empty(resp: FetchResponse) -> bool:
        """Heuristic: does the response suggest JS rendering is needed?"""
        if resp.status_code != 200:
            return False
        body = resp.html.strip()
        if len(body) < _EMPTY_BODY_THRESHOLD:
            return True
        lower = body.lower()
        for indicator in _JS_REQUIRED_INDICATORS:
            if indicator in lower:
                return True
        return False

    def fetch_or_none(
        self,
        url: str,
        *,
        min_length: int = _EMPTY_BODY_THRESHOLD,
        **kwargs: Any,
    ) -> Optional[FetchResponse]:
        """Return the response only if it has substantial content, else ``None``.

        Useful in auto-detection pipelines: try static first, fall back to
        dynamic if the result is too thin.
        """
        resp = self.get(url, **kwargs)
        if len(resp.html.strip()) >= min_length and not self._looks_empty(resp):
            return resp
        logger.debug("Static fetch insufficient for %s – returning None", url)
        return None
