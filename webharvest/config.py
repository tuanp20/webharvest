"""
CrawlConfig — central configuration dataclass for WebHarvest.

Inspired by gallery-dl's config system: everything tuneable in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set


class FetcherType(Enum):
    """Fetcher strategy selection."""
    AUTO = "auto"        # Let CrawlPipeline decide
    STATIC = "static"    # httpx-based, fastest
    DYNAMIC = "dynamic"  # Playwright-based, for JS-heavy sites
    STEALTH = "stealth"  # Stealth Playwright, for anti-bot sites


@dataclass
class CrawlConfig:
    """All settings for a crawl/download session.

    Examples
    --------
    >>> cfg = CrawlConfig(url="https://example.com", output_dir="./out")
    >>> cfg = CrawlConfig(url="https://example.com", depth=2, max_pages=50)
    """

    # --- Core ---
    url: str = ""
    output_dir: str = "./output"

    # --- Crawl behaviour ---
    depth: int = 1                      # Link-following depth (0 = single page)
    max_pages: int = 100                # Hard cap on pages visited
    max_images: int = 0                 # 0 = unlimited
    concurrent_downloads: int = 5       # Parallel image downloads
    concurrent_fetches: int = 3         # Parallel page fetches
    request_delay: float = 0.5          # Seconds between requests (politeness)

    # --- Fetcher selection ---
    fetcher: FetcherType = FetcherType.AUTO

    # --- Image filtering ---
    min_width: int = 0                  # Minimum image width in px
    min_height: int = 0                 # Minimum image height in px
    min_file_size: int = 0              # Minimum file size in bytes
    allowed_formats: Set[str] = field(
        default_factory=lambda: {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"}
    )

    # --- URL filtering ---
    allowed_domains: List[str] = field(default_factory=list)
    excluded_patterns: List[str] = field(default_factory=list)
    same_domain_only: bool = True       # Stay on starting domain
    respect_robots_txt: bool = True

    # --- Gallery / pagination ---
    gallery_mode: bool = False          # Follow "next page" links
    pagination_selectors: List[str] = field(
        default_factory=lambda: [
            'a[rel="next"]',
            '.next a', '.pagination .next a',
            'a.next', 'a.pagination-next',
            'li.next a',
        ]
    )

    # --- HTTP settings ---
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    headers: dict = field(default_factory=dict)
    cookies: dict = field(default_factory=dict)
    proxy: Optional[str] = None
    timeout: float = 30.0

    # --- Output ---
    filename_template: str = "{name}{ext}"  # gallery-dl style
    directory_template: str = "{domain}/{subcategory}"
    overwrite: bool = False
    create_dirs: bool = True
    write_metadata: bool = False        # Sidecar JSON files

    # --- Advanced ---
    retry_count: int = 3
    verify_ssl: bool = True
    follow_redirects: bool = True

    def __post_init__(self):
        """Validate and normalise configuration."""
        if self.allowed_domains and not isinstance(self.allowed_domains, list):
            self.allowed_domains = [self.allowed_domains]
        if self.excluded_patterns and not isinstance(self.excluded_patterns, list):
            self.excluded_patterns = [self.excluded_patterns]

        # Normalise format strings to lowercase without dots
        self.allowed_formats = {
            f.lstrip(".").lower() for f in self.allowed_formats
        }

        # Ensure output_dir is absolute
        self.output_dir = str(Path(self.output_dir).expanduser().resolve())

    # ------------------------------------------------------------------
    # Convenience builders
    # ------------------------------------------------------------------
    @classmethod
    def for_download(cls, url: str, output_dir: str = "./output", **kwargs) -> "CrawlConfig":
        """Quick config for single-page image download."""
        return cls(url=url, output_dir=output_dir, depth=0, **kwargs)

    @classmethod
    def for_crawl(cls, url: str, depth: int = 2, **kwargs) -> "CrawlConfig":
        """Quick config for multi-page crawling."""
        return cls(url=url, depth=depth, **kwargs)

    @classmethod
    def for_gallery(cls, url: str, **kwargs) -> "CrawlConfig":
        """Quick config for gallery/album pagination."""
        return cls(url=url, gallery_mode=True, depth=0, **kwargs)
