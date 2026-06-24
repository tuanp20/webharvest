"""Data models for WebHarvest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ImageInfo:
    """Information about a single image found on a page."""

    url: str
    source_type: str  # e.g. "img_src", "srcset", "og:image", "background", "link", "json-ld", etc.
    width: Optional[int] = None
    height: Optional[int] = None
    alt: Optional[str] = None
    title: Optional[str] = None
    content_hash: Optional[str] = None  # sha256 of content after download

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ImageInfo):
            return self.url == other.url
        return NotImplemented


@dataclass
class PageData:
    """Extracted data from a single page."""

    url: str
    title: Optional[str] = None
    html: Optional[str] = None
    text: Optional[str] = None
    headings: dict[str, list[str]] = field(default_factory=dict)  # {"h1": [...], "h2": [...]}
    links: list[dict[str, str]] = field(default_factory=list)  # [{"url": ..., "text": ...}]
    images: list[ImageInfo] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)  # list of tables, each table is list of rows
    metadata: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict] = field(default_factory=list)
    status_code: Optional[int] = None
    content_type: Optional[str] = None


@dataclass
class DownloadResult:
    """Result of an image download operation."""

    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    output_dir: Path = field(default_factory=lambda: Path("."))
    errors: list[str] = field(default_factory=list)
    downloaded_paths: list[Path] = field(default_factory=list)
    content_hashes: set[str] = field(default_factory=set)


@dataclass
class CrawlConfig:
    """Configuration for a crawl operation."""

    max_concurrent: int = 10
    min_image_size: int = 0  # bytes; skip images smaller than this
    image_formats: Optional[set[str]] = None  # e.g. {"jpg", "png", "webp"}; None = all
    output_dir: Path = field(default_factory=lambda: Path("downloads"))
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    user_agent: str = "WebHarvest/1.0"
    follow_redirects: bool = True
    max_pages: int = 100
    max_depth: int = 3
    dedup_by_hash: bool = True
    skip_existing: bool = True
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class CrawlResult:
    """Result of a crawl operation."""

    pages: list[PageData] = field(default_factory=list)
    all_images: list[ImageInfo] = field(default_factory=list)
    download_result: Optional[DownloadResult] = None
    total_pages: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ProductVariant:
    """A variation of a product (e.g. combination of color and size)."""

    color: Optional[str] = None
    size: Optional[str] = None
    price: Optional[float] = None
    sku: Optional[str] = None
    in_stock: bool = True
    image_url: Optional[str] = None
    local_image_path: Optional[str] = None


@dataclass
class ProductData:
    """Extracted catalog product information."""

    title: str
    url: str
    source_site: str
    main_image_url: Optional[str] = None
    local_image_path: Optional[str] = None
    price: Optional[float] = None
    currency: str = "USD"
    description: Optional[str] = None
    category: Optional[str] = None
    variants: list[ProductVariant] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)
    brand: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    tags: list[str] = field(default_factory=list)
    additional_images: list[str] = field(default_factory=list)
    local_additional_images: list[str] = field(default_factory=list)
    crawled_at: Optional[str] = None
    raw_json: Optional[dict] = None

