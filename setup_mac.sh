#!/usr/bin/env bash
#
# setup_mac.sh — One-click setup for WebHarvest on macOS
#
# Usage:
#   chmod +x setup_mac.sh && ./setup_mac.sh
#
# What it does:
#   1. Check Python 3.9+ (Homebrew python@3.11+ preferred)
#   2. Create virtual environment (.venv)
#   3. Install all dependencies
#   4. Install Playwright Chromium (optional, for JS-heavy sites)
#   5. Register `webharvest` CLI command
#   6. Verify installation
#
set -e

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "\n${CYAN}${BOLD}[$1/$TOTAL_STEPS]${NC} ${BOLD}$*${NC}"; }

TOTAL_STEPS=6
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════╗"
echo "║        🌐 WebHarvest — macOS Setup           ║"
echo "║   Async web scraper & image downloader       ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Check Python ────────────────────────────────────────────────────
step 1 "Checking Python installation..."

PYTHON_CMD=""

# Try python3 from Homebrew first (most up-to-date)
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [[ "$major" -eq 3 && "$minor" -ge 9 ]]; then
            PYTHON_CMD="$cmd"
            ok "Found $cmd (Python $version)"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    error "Python 3.9+ not found!"
    echo ""
    echo "  Install via Homebrew:"
    echo "    brew install python@3.13"
    echo ""
    echo "  Or download from:"
    echo "    https://www.python.org/downloads/"
    exit 1
fi

# ── Step 2: Check Homebrew (optional) ───────────────────────────────────────
step 2 "Checking Homebrew (optional)..."

if command -v brew &>/dev/null; then
    ok "Homebrew found: $(brew --version | head -1)"
else
    warn "Homebrew not found (not required, but recommended)"
    echo "  Install: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
fi

# ── Step 3: Create virtual environment ──────────────────────────────────────
step 3 "Creating virtual environment..."

cd "$PROJECT_DIR"

if [[ -d ".venv" ]]; then
    warn ".venv already exists, skipping creation"
else
    $PYTHON_CMD -m venv .venv
    ok "Created .venv with $PYTHON_CMD"
fi

# Activate venv
source .venv/bin/activate
ok "Activated .venv (Python $(python3 --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+'))"

# ── Step 4: Install dependencies ────────────────────────────────────────────
step 4 "Installing dependencies..."

pip install --upgrade pip setuptools wheel --quiet 2>/dev/null
ok "pip upgraded"

info "Installing WebHarvest + dependencies..."
pip install -e "." --quiet 2>&1 | tail -3
ok "WebHarvest installed"

# ── Step 5: Install Playwright (optional) ───────────────────────────────────
step 5 "Installing Playwright (for JS-heavy sites)..."

echo ""
echo -e "  ${YELLOW}Playwright enables Dynamic & Stealth fetchers${NC}"
echo -e "  ${YELLOW}for JavaScript-rendered pages (SPAs, infinite scroll, etc.)${NC}"
echo ""
read -p "  Install Playwright? [Y/n] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Nn]$ ]]; then
    warn "Skipping Playwright — Static fetcher only"
    warn "To install later: pip install playwright && playwright install chromium"
else
    pip install playwright --quiet 2>&1 | tail -1
    info "Downloading Chromium browser (~150MB)..."
    playwright install chromium 2>&1 | tail -3
    ok "Playwright + Chromium installed"
fi

# ── Step 6: Verify installation ─────────────────────────────────────────────
step 6 "Verifying installation..."

echo ""

# Check CLI
if python -m webharvest --version &>/dev/null; then
    ok "CLI works: $(python -m webharvest --version)"
else
    error "CLI verification failed"
    exit 1
fi

# Check imports
python3 -c "
import webharvest
from webharvest.config import CrawlConfig
from webharvest.pipeline.crawler import CrawlPipeline, StaticFetcher
ok = True
" 2>/dev/null && ok "Core imports OK" || error "Import check failed"

# Check Playwright
if python3 -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    ok "Playwright available (Dynamic + Stealth fetchers enabled)"
else
    warn "Playwright not available (Static fetcher only)"
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════╗"
echo "║          ✅ Setup Complete!                  ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BOLD}Quick Start:${NC}"
echo ""
echo "  # Activate virtual environment"
echo "  ${CYAN}cd $PROJECT_DIR && source .venv/bin/activate${NC}"
echo ""
echo "  # Download images from any URL"
echo "  ${CYAN}webharvest download \"https://en.wikipedia.org/wiki/Vietnam\" -o ./output${NC}"
echo ""
echo "  # Crawl multiple pages"
echo "  ${CYAN}webharvest crawl \"https://books.toscrape.com/\" --depth 2 --max-pages 20${NC}"
echo ""
echo "  # Gallery mode (follows pagination)"
echo "  ${CYAN}webharvest gallery \"https://example.com/gallery\" --next-selector \".next a\"${NC}"
echo ""
echo "  # Launch web UI"
echo "  ${CYAN}python -m webharvest.server${NC}"
echo ""
echo "  # Launch desktop app"
echo "  ${CYAN}python main_desktop.py${NC}"
echo ""
echo -e "${BOLD}More info:${NC}"
echo "  📖 README:     https://github.com/tuanp20/webharvest"
echo "  🐛 Issues:     https://github.com/tuanp20/webharvest/issues"
echo ""
