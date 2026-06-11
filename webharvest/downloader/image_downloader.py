"""Async image downloader with dedup, progress tracking, and filtering.

Pipeline inspired by gallery-dl:
  1. Filter by format / min-size headers
  2. Dedup by content hash
  3. Retry with exponential back-off
  4. Smart file naming (hash + original extension)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, unquote

import aiohttp

from webharvest.models import CrawlConfig, DownloadResult, ImageInfo

logger = logging.getLogger(__name__)

# Allowed content-type → extension mapping
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/avif": ".avif",
    "image/x-icon": ".ico",
}

_EXT_TO_MIME: dict[str, str] = {v: k for k, v in _MIME_TO_EXT.items()}


class ImageDownloader:
    """Download images concurrently with dedup and filtering.

    Parameters
    ----------
    config : CrawlConfig
        Download configuration.
    on_progress : optional callback
        Called with ``(downloaded_count, total_count)`` after each image.
    """

    def __init__(
        self,
        config: CrawlConfig | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.config = config or CrawlConfig()
        self._on_progress = on_progress
        self._seen_hashes: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download_all(self, images: list[ImageInfo]) -> DownloadResult:
        """Download all *images* and return a :class:`DownloadResult`."""
        output_dir = self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        result = DownloadResult(total=len(images), output_dir=output_dir)
        sem = asyncio.Semaphore(self.config.max_concurrent)

        connector = aiohttp.TCPConnector(limit=self.config.max_concurrent)
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        headers = {"User-Agent": self.config.user_agent, **self.config.headers}

        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, headers=headers
        ) as session:
            tasks = [
                self._download_one(session, sem, img, result)
                for img in images
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        return result

    async def _download_one(
        self,
        session: aiohttp.ClientSession,
        sem: asyncio.Semaphore,
        img: ImageInfo,
        result: DownloadResult,
    ) -> None:
        """Download a single image (with retries)."""
        async with sem:
            for attempt in range(1, self.config.max_retries + 1):
                try:
                    await self._try_download(session, img, result)
                    return
                except Exception as exc:
                    if attempt == self.config.max_retries:
                        msg = f"{img.url} — {exc}"
                        result.failed += 1
                        result.errors.append(msg)
                        logger.warning("Failed: %s", msg)
                    else:
                        await asyncio.sleep(self.config.retry_delay * attempt)

    async def _try_download(
        self,
        session: aiohttp.ClientSession,
        img: ImageInfo,
        result: DownloadResult,
    ) -> None:
        """Single download attempt."""
        async with session.get(
            img.url,
            allow_redirects=self.config.follow_redirects,
        ) as resp:
            resp.raise_for_status()

            # --- Format filter ---
            content_type = resp.headers.get("Content-Type", "")
            ext = self._extension_from_response(img.url, content_type)
            if self.config.image_formats:
                ext_clean = ext.lstrip(".")
                if ext_clean.lower() not in self.config.image_formats:
                    result.skipped += 1
                    return

            # --- Download body ---
            data = await resp.read()

            # --- Min-size filter ---
            if self.config.min_image_size and len(data) < self.config.min_image_size:
                result.skipped += 1
                return

            # --- Hash dedup ---
            content_hash = hashlib.sha256(data).hexdigest()
            if self.config.dedup_by_hash and content_hash in self._seen_hashes:
                result.skipped += 1
                return
            self._seen_hashes.add(content_hash)

            # --- Skip existing ---
            filename = self._make_filename(img.url, ext, content_hash)
            dest = self.config.output_dir / filename
            if self.config.skip_existing and dest.exists():
                result.skipped += 1
                return

            # --- Write ---
            dest.write_bytes(data)
            result.downloaded += 1
            result.downloaded_paths.append(dest)
            result.content_hashes.add(content_hash)
            img.content_hash = content_hash

            logger.debug("Saved %s (%d bytes)", dest.name, len(data))
            if self._on_progress:
                self._on_progress(result.downloaded, result.total)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_filename(url: str, ext: str, content_hash: str) -> str:
        """Build a safe, unique filename."""
        # Try to keep the original basename for readability
        parsed = urlparse(url)
        raw_name = Path(unquote(parsed.path)).stem
        # Sanitise
        safe = "".join(c for c in raw_name if c.isalnum() or c in "-_ ")[:80].strip()
        if not safe:
            safe = "image"
        # Append short hash to avoid collisions
        short_hash = content_hash[:12]
        return f"{safe}_{short_hash}{ext}"

    @staticmethod
    def _extension_from_response(url: str, content_type: str) -> str:
        """Determine file extension from content-type or URL."""
        # Try content-type first
        ct = content_type.split(";")[0].strip().lower()
        if ct in _MIME_TO_EXT:
            return _MIME_TO_EXT[ct]
        # Fall back to URL extension
        path = urlparse(url).path
        dot_idx = path.rfind(".")
        if dot_idx != -1:
            ext = path[dot_idx:].lower()
            # Normalise .jpeg → .jpg
            if ext == ".jpeg":
                return ".jpg"
            return ext
        return ".jpg"  # safe default
