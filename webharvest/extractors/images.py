"""Comprehensive image extractor – finds ALL image sources on a page.

Extraction sources (in order):
  1. <img> tags: src, srcset, data-src, data-lazy-src, data-original, data-full, etc.
  2. <picture> / <source srcset>
  3. CSS background-image in inline styles
  4. <meta> og:image / twitter:image
  5. JSON-LD structured data (image field)
  6. <a href> links to image files
  7. CSS <style> / <link rel="stylesheet"> background-image (in-page <style> blocks)
"""

from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from webharvest.models import ImageInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp",
    ".ico", ".tiff", ".tif", ".avif", ".jfif",
})

# data-* attributes commonly used for lazy-loading
LAZY_DATA_ATTRS = (
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-full",
    "data-hi-res-src",
    "data-image",
    "data-img",
    "data-bg",
    "data-background",
    "data-background-image",
    "data-thumb",
    "data-large_image",
    "data-large-file",
    "data-medium-file",
    "data-huge",
    "data-retina",
    "data-srcset",
    "data-lazy-srcset",
)

# Regex to pull url(...) from CSS values
_CSS_URL_RE = re.compile(r"""url\(\s*['"]?(.+?)['"]?\s*\)""", re.IGNORECASE)

# Regex to pull URLs from srcset attribute values
_SRCSET_RE = re.compile(r"""([^\s,]+)""")

# Allowed image mime-type prefix (for link detection)
_IMG_MIME_RE = re.compile(r"^image/", re.IGNORECASE)


class ImageExtractor:
    """Extract every discoverable image URL from an HTML page."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, html: str) -> list[ImageInfo]:
        """Parse *html* and return a deduplicated list of :class:`ImageInfo`."""
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[ImageInfo] = []

        def _add(url: str, source_type: str, *, width: int | None = None,
                 height: int | None = None, alt: str | None = None,
                 title: str | None = None) -> None:
            url = self._resolve(url)
            if not url or url in seen:
                return
            seen.add(url)
            results.append(ImageInfo(
                url=url,
                source_type=source_type,
                width=width,
                height=height,
                alt=alt,
                title=title,
            ))

        # 1. <img> tags
        for img in soup.find_all("img"):
            self._extract_img(img, _add)

        # 2. <picture> / <source srcset>
        for source in soup.find_all("source"):
            self._extract_source(source, _add)

        # 3. Inline style background-image
        for tag in soup.find_all(style=True):
            self._extract_inline_style(tag, _add)

        # 4. <style> blocks (in-page CSS)
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                self._extract_css_text(style_tag.string, _add)

        # 5. <meta> og:image / twitter:image
        self._extract_meta_images(soup, _add)

        # 6. JSON-LD structured data
        self._extract_json_ld(soup, _add)

        # 7. <a href> links to image files
        self._extract_image_links(soup, _add)

        return results

    # ------------------------------------------------------------------
    # <img> tag
    # ------------------------------------------------------------------

    def _extract_img(self, img: Tag, _add) -> None:  # type: ignore[no-untyped-def]
        alt = img.get("alt")
        title = img.get("title")
        width = _int_or_none(img.get("width"))
        height = _int_or_none(img.get("height"))

        # Standard src
        src = img.get("src")
        if src and not _is_data_uri(src):
            _add(src, "img_src", width=width, height=height, alt=alt, title=title)

        # srcset (may contain multiple URLs)
        srcset = img.get("srcset")
        if srcset:
            for url in self._parse_srcset(srcset):
                _add(url, "img_srcset", width=width, height=height, alt=alt, title=title)

        # data-* lazy-load attributes
        for attr in LAZY_DATA_ATTRS:
            val = img.get(attr)
            if val and not _is_data_uri(val):
                if "srcset" in attr:
                    for url in self._parse_srcset(val):
                        _add(url, f"img_{attr}")
                else:
                    _add(val, f"img_{attr}", alt=alt)

    # ------------------------------------------------------------------
    # <picture> / <source srcset>
    # ------------------------------------------------------------------

    def _extract_source(self, source: Tag, _add) -> None:  # type: ignore[no-untyped-def]
        srcset = source.get("srcset")
        if srcset:
            for url in self._parse_srcset(srcset):
                _add(url, "picture_srcset")

    # ------------------------------------------------------------------
    # Inline style background-image
    # ------------------------------------------------------------------

    def _extract_inline_style(self, tag: Tag, _add) -> None:  # type: ignore[no-untyped-def]
        style = tag.get("style", "")
        for match in _CSS_URL_RE.finditer(style):
            url = match.group(1)
            if not _is_data_uri(url):
                _add(url, "inline_style_bg")

    # ------------------------------------------------------------------
    # <style> blocks
    # ------------------------------------------------------------------

    def _extract_css_text(self, css_text: str, _add) -> None:  # type: ignore[no-untyped-def]
        for match in _CSS_URL_RE.finditer(css_text):
            url = match.group(1)
            if not _is_data_uri(url):
                _add(url, "css_background")

    # ------------------------------------------------------------------
    # <meta> og:image / twitter:image
    # ------------------------------------------------------------------

    def _extract_meta_images(self, soup: BeautifulSoup, _add) -> None:  # type: ignore[no-untyped-def]
        for meta in soup.find_all("meta"):
            prop = (meta.get("property") or meta.get("name") or "").lower()
            content = meta.get("content")
            if not content:
                continue
            if prop in ("og:image", "og:image:url", "og:image:secure_url"):
                _add(content, "og:image")
            elif prop in ("twitter:image", "twitter:image:src"):
                _add(content, "twitter:image")

    # ------------------------------------------------------------------
    # JSON-LD structured data
    # ------------------------------------------------------------------

    def _extract_json_ld(self, soup: BeautifulSoup, _add) -> None:  # type: ignore[no-untyped-def]
        for script in soup.find_all("script", type="application/ld+json"):
            text = script.string or script.get_text()
            if not text:
                continue
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            self._walk_json_for_images(data, _add)

    def _walk_json_for_images(self, obj, _add) -> None:  # type: ignore[no-untyped-def,override]
        if isinstance(obj, str):
            # Could be a direct image URL
            ext = _url_extension(obj)
            if ext in IMAGE_EXTENSIONS:
                _add(obj, "json-ld")
        elif isinstance(obj, dict):
            for key, val in obj.items():
                lk = key.lower()
                if lk in ("image", "thumbnailurl", "logo", "thumbnail"):
                    self._collect_image_value(val, _add)
                else:
                    self._walk_json_for_images(val, _add)
        elif isinstance(obj, list):
            for item in obj:
                self._walk_json_for_images(item, _add)

    def _collect_image_value(self, val, _add) -> None:  # type: ignore[no-untyped-def,override]
        if isinstance(val, str):
            _add(val, "json-ld")
        elif isinstance(val, dict):
            url = val.get("url") or val.get("contentUrl")
            if url:
                _add(url, "json-ld")
        elif isinstance(val, list):
            for item in val:
                self._collect_image_value(item, _add)

    # ------------------------------------------------------------------
    # <a href> image links
    # ------------------------------------------------------------------

    def _extract_image_links(self, soup: BeautifulSoup, _add) -> None:  # type: ignore[no-untyped-def]
        for a in soup.find_all("a", href=True):
            href = a["href"]
            ext = _url_extension(href)
            if ext in IMAGE_EXTENSIONS:
                _add(href, "link_href")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve(self, url: str) -> Optional[str]:
        """Resolve a (possibly relative) URL against the page base URL."""
        if not url:
            return None
        url = url.strip()
        if url.startswith("data:"):
            return None
        try:
            resolved = urljoin(self.base_url, url)
        except Exception:
            return None
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https"):
            return None
        return resolved

    def _parse_srcset(self, srcset: str) -> list[str]:
        """Parse a srcset attribute value into individual URLs."""
        urls: list[str] = []
        for part in srcset.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if tokens:
                url = tokens[0]
                if url and not _is_data_uri(url):
                    urls.append(url)
        return urls


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_data_uri(val: str) -> bool:
    return val.strip().startswith("data:")


def _int_or_none(val: str | None) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _url_extension(url: str) -> str:
    """Return the lowercase file extension (with dot) from a URL path."""
    path = urlparse(url).path
    # Handle query-string-free path
    dot_idx = path.rfind(".")
    if dot_idx == -1:
        return ""
    return path[dot_idx:].lower()
