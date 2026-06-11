"""Content extractor – pull structured data from HTML pages.

Uses BeautifulSoup + lxml for reliable, fast parsing.  No AI/LLM involved.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from webharvest.models import ImageInfo, PageData

from .images import ImageExtractor


class ContentExtractor:
    """Extract structured content from an HTML page."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._img_extractor = ImageExtractor(base_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, html: str, url: str | None = None, *,
                status_code: int | None = None,
                content_type: str | None = None) -> PageData:
        """Parse *html* and return a fully populated :class:`PageData`.

        Note: JSON-LD, metadata, and title are extracted *before*
        ``_extract_text`` because that method decomposes ``<script>``
        tags which would destroy the JSON-LD data.
        """
        soup = BeautifulSoup(html, "lxml")
        page_url = url or self.base_url

        # Extract script/meta-dependent fields first
        json_ld = self._extract_json_ld(soup)
        metadata = self._extract_metadata(soup)
        title = self._extract_title(soup)

        # _extract_text decomposes <script>/<style>, mutating soup
        text = self._extract_text(soup)

        return PageData(
            url=page_url,
            title=title,
            html=html,
            text=text,
            headings=self._extract_headings(soup),
            links=self._extract_links(soup),
            images=self._img_extractor.extract(html),
            tables=self._extract_tables(soup),
            metadata=metadata,
            json_ld=json_ld,
            status_code=status_code,
            content_type=content_type,
        )

    # ------------------------------------------------------------------
    # Title
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> Optional[str]:
        tag = soup.find("title")
        if tag and tag.string:
            return tag.string.strip()
        # Fallback: og:title
        meta = soup.find("meta", property="og:title")
        if meta and meta.get("content"):
            return meta["content"].strip()
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return None

    # ------------------------------------------------------------------
    # Plain text
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(soup: BeautifulSoup) -> str:
        # Remove script and style elements
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse blank lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Headings
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_headings(soup: BeautifulSoup) -> dict[str, list[str]]:
        headings: dict[str, list[str]] = {}
        for level in range(1, 7):
            tag_name = f"h{level}"
            found = [tag.get_text(strip=True) for tag in soup.find_all(tag_name)]
            if found:
                headings[tag_name] = found
        return headings

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def _extract_links(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            resolved = urljoin(self.base_url, href)
            if resolved in seen:
                continue
            seen.add(resolved)
            text = a.get_text(strip=True)
            links.append({"url": resolved, "text": text})
        return links

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
        tables: list[list[list[str]]] = []
        for table in soup.find_all("table"):
            rows: list[list[str]] = []
            for tr in table.find_all("tr"):
                cells = []
                for cell in tr.find_all(["td", "th"]):
                    cells.append(cell.get_text(strip=True))
                rows.append(cells)
            if rows:
                tables.append(rows)
        return tables

    # ------------------------------------------------------------------
    # Metadata (<meta> tags)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup) -> dict[str, str]:
        meta: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or tag.get("itemprop")
            content = tag.get("content")
            if name and content:
                key = name.lower().strip()
                if key not in meta:
                    meta[key] = content.strip()
        return meta

    # ------------------------------------------------------------------
    # JSON-LD
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
        results: list[dict] = []
        for script in soup.find_all("script", type="application/ld+json"):
            text = script.string or script.get_text()
            if not text:
                continue
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, list):
                results.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                results.append(data)
        return results
