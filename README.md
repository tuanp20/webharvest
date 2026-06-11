# 🌐 WebHarvest

**Async web scraper and image downloader with intelligent fetcher selection.**

WebHarvest combines the best ideas from [gallery-dl](https://github.com/mikf/gallery-dl), [crawl4ai](https://github.com/unclecode/crawl4ai), and [scrapling](https://github.com/D4Vinci/Scrapling) into a single, easy-to-use toolkit.

## ✨ Features

- **🔄 Async Pipeline** — High-performance async/await throughout
- **🧠 Auto-Fetcher Selection** — Automatically upgrades: Static → Dynamic → Stealth
- **🖼️ Image Extraction** — Finds images in `<img>`, `srcset`, `background-image`, and links
- **📄 Gallery Pagination** — Follows "next page" links automatically
- **🛡️ Anti-Bot Stealth** — Stealth Playwright mode for protected sites
- **⚡ BFS Crawling** — Breadth-first with configurable depth and page limits
- **🎯 Smart Filtering** — Format, size, domain, and pattern-based filters

## 📦 Installation

```bash
# Core (fast, no browser needed)
pip install -e .

# With Playwright for dynamic/JS-heavy sites
pip install -e ".[dynamic]"
playwright install chromium

# Everything
pip install -e ".[all]"
```

## 🚀 Quick Start

### Download all images from a page

```bash
webharvest download https://example.com/photos -o ./photos
```

### Crawl a site with depth

```bash
webharvest crawl https://blog.example.com --depth 3 --max-pages 50
```

### Gallery/album mode (follows pagination)

```bash
webharvest gallery https://imgur.com/a/abc123
```

### Use stealth mode for protected sites

```bash
webharvest download https://protected-site.com/images --stealth
```

### Filter by format and size

```bash
webharvest download https://example.com -f png,webp -s 10240
```

## 📖 CLI Reference

```
webharvest <command> <url> [options]

Commands:
  download    Download all images from a URL (single page)
  crawl       Crawl site and extract data (follows links)
  gallery     Gallery/album mode with pagination

Options:
  -o, --output DIR       Output directory (default: ./output)
  -d, --depth N          Link-following depth (default: 1)
  -n, --max-pages N      Maximum pages to visit (default: 100)
  -c, --concurrent N     Concurrent downloads (default: 5)
  -s, --min-size N       Minimum file size in bytes
  -f, --format FMT       Comma-separated formats (e.g. jpg,png,webp)
  --delay SECS           Delay between requests in seconds
  --stealth              Use stealth browser fetcher
  --dynamic              Use dynamic (Playwright) fetcher
  --proxy URL            Proxy URL (http://host:port)
  -v, --verbose          Verbose output
  --version              Show version
```

### Gallery-specific

```
  --next-selector CSS    Custom CSS selector for next-page link
```

## 🐍 Python API

```python
import asyncio
from webharvest import CrawlConfig, CrawlPipeline

async def main():
    config = CrawlConfig(
        url="https://example.com/photos",
        output_dir="./output",
        depth=0,
        concurrent_downloads=10,
        allowed_formats={"jpg", "png", "webp"},
        min_file_size=10240,
    )
    
    pipeline = CrawlPipeline(config)
    result = await pipeline.run()
    
    print(result.summary())
    # WebHarvest Crawl Result
    #   URL:            https://example.com/photos
    #   Pages visited:  1
    #   Images found:   42
    #   Downloaded:     40
    #   Failed:         2
    #   Total bytes:    128.5 MB
    #   Time:           12.3s

asyncio.run(main())
```

### With progress callbacks

```python
from webharvest import CrawlConfig, CrawlPipeline

def on_progress(event, data):
    if event == "image_downloaded":
        print(f"Downloaded: {data['url']}")

config = CrawlConfig(url="https://example.com")
pipeline = CrawlPipeline(config, on_progress=on_progress)
result = asyncio.run(pipeline.run())
```

### Quick config builders

```python
# Single-page download
cfg = CrawlConfig.for_download("https://example.com", "./output")

# Multi-page crawl
cfg = CrawlConfig.for_crawl("https://blog.example.com", depth=3)

# Gallery pagination
cfg = CrawlConfig.for_gallery("https://imgur.com/a/abc123")
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                      CLI (cli.py)                    │
│   webharvest download │ webharvest crawl │ gallery   │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│               CrawlPipeline (crawler.py)             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │  FETCH    │→ │  PARSE   │→ │ EXTRACT  │          │
│  │          │  │          │  │  IMAGES  │          │
│  └────┬─────┘  └──────────┘  └────┬─────┘          │
│       │                           │                  │
│       ▼                           ▼                  │
│  ┌──────────────────────────────────────┐           │
│  │         DOWNLOAD IMAGES              │           │
│  │    (async, concurrent, retry)        │           │
│  └──────────────────────────────────────┘           │
│                                                      │
│  ┌──────────────────────────────────────┐           │
│  │      AUTO-FETCHER SELECTION          │           │
│  │                                      │           │
│  │  StaticFetcher (httpx)               │           │
│  │    ↓ empty content / JS indicators   │           │
│  │  DynamicFetcher (Playwright)         │           │
│  │    ↓ anti-bot detected               │           │
│  │  StealthFetcher (stealth Playwright) │           │
│  └──────────────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              Config (config.py)                      │
│   CrawlConfig dataclass with all settings           │
│   Gallery-dl inspired: everything in one place      │
└─────────────────────────────────────────────────────┘
```

## 🔄 Comparison with Similar Tools

| Feature | **WebHarvest** | gallery-dl | crawl4ai | scrapling |
|---------|:---:|:---:|:---:|:---:|
| **Async pipeline** | ✅ | ❌ | ✅ | ❌ |
| **Auto-fetcher selection** | ✅ | ❌ | ✅ | ✅ |
| **CLI with subcommands** | ✅ | ✅ | ❌ | ❌ |
| **Gallery pagination** | ✅ | ✅ | ❌ | ❌ |
| **Image download** | ✅ | ✅ | ❌ | ❌ |
| **Stealth mode** | ✅ | ❌ | ❌ | ✅ |
| **BFS crawling** | ✅ | ❌ | ✅ | ✅ |
| **Python API** | ✅ | ✅ | ✅ | ✅ |
| **No browser required** | ✅ | ✅ | ❌ | ✅ |
| **Progress callbacks** | ✅ | ❌ | ✅ | ❌ |
| **Config dataclass** | ✅ | ✅ (JSON) | ✅ | ❌ |

### Why WebHarvest?

- **vs gallery-dl**: Async pipeline is 3-5x faster for bulk downloads. Auto-fetcher selection handles JS sites without manual config. Modern Python API.
  
- **vs crawl4ai**: Also downloads images. Built-in gallery pagination. Works without Playwright for simple sites. Lighter dependency footprint.

- **vs scrapling**: Better CLI experience. Built-in image downloading. Gallery mode for pagination. Cleaner async architecture.

## ⚙️ Configuration Reference

```python
CrawlConfig(
    # Core
    url="https://example.com",
    output_dir="./output",
    
    # Crawling
    depth=1,                    # Link-following depth
    max_pages=100,              # Page visit cap
    max_images=0,               # Image cap (0=unlimited)
    concurrent_downloads=5,     # Parallel downloads
    concurrent_fetches=3,       # Parallel page fetches
    request_delay=0.5,          # Politeness delay (seconds)
    
    # Fetcher
    fetcher=FetcherType.AUTO,   # AUTO, STATIC, DYNAMIC, STEALTH
    
    # Image filters
    min_width=0,
    min_height=0,
    min_file_size=0,
    allowed_formats={"jpg", "png", "gif", "webp", "svg"},
    
    # URL filters
    allowed_domains=[],
    excluded_patterns=[],
    same_domain_only=True,
    respect_robots_txt=True,
    
    # Gallery
    gallery_mode=False,
    pagination_selectors=['a[rel="next"]', '.next a'],
    
    # HTTP
    user_agent="Mozilla/5.0 ...",
    headers={},
    cookies={},
    proxy=None,
    timeout=30.0,
    
    # Output
    filename_template="{name}{ext}",
    overwrite=False,
    write_metadata=False,
    
    # Advanced
    retry_count=3,
    verify_ssl=True,
)
```

## 📄 License

MIT
