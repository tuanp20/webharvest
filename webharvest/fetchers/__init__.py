"""
webharvest.fetchers – pluggable web-content fetching layer.

Provides three fetcher classes with increasing capabilities:

- :class:`StaticFetcher` – plain HTTP requests (fast, lightweight).
- :class:`DynamicFetcher` – headless-browser rendering for JS-heavy pages.
- :class:`StealthFetcher` – anti-bot stealth mode with fingerprint spoofing.

Usage::

    from webharvest.fetchers import Fetcher, DynamicFetcher, StealthFetcher

    # Quick static fetch
    with Fetcher() as f:
        resp = f.get("https://example.com")
        print(resp.html)

    # JS-rendered page
    with DynamicFetcher() as df:
        resp = df.get("https://spa-site.com", wait_for_selector="#content")
        print(resp.html)

    # Anti-bot stealth
    with StealthFetcher() as sf:
        resp = sf.get("https://protected-site.com")
        print(resp.html)
"""

from .base import BaseFetcher, FetchResponse
from .dynamic import DynamicFetcher
from .static import StaticFetcher
from .stealth import StealthFetcher

# Convenient alias – StaticFetcher is the "default" fetcher
Fetcher = StaticFetcher

__all__ = [
    "BaseFetcher",
    "FetchResponse",
    "Fetcher",
    "StaticFetcher",
    "DynamicFetcher",
    "StealthFetcher",
]
