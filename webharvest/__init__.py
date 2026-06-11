"""
WebHarvest - A powerful, async web scraping and image downloading framework.

Combines the best ideas from gallery-dl (CLI design), crawl4ai (async pipeline),
and scrapling (fetcher factory pattern) into a unified toolkit.
"""

__version__ = "1.0.0"
__author__ = "WebHarvest Contributors"

# Existing models (from other modules)
from webharvest.models import (
    CrawlResult,
    DownloadResult,
    ImageInfo,
    PageData,
)

# Pipeline orchestrator
from webharvest.config import CrawlConfig as PipelineConfig, FetcherType
from webharvest.pipeline.crawler import CrawlPipeline, CrawlResult as PipelineResult

# Alias for convenience
CrawlConfig = PipelineConfig

__all__ = [
    "__version__",
    # Models
    "CrawlConfig",
    "CrawlResult",
    "DownloadResult",
    "ImageInfo",
    "PageData",
    # Pipeline
    "CrawlPipeline",
    "PipelineConfig",
    "PipelineResult",
    "FetcherType",
]
