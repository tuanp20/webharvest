#!/usr/bin/env bash
#
# start_mac.sh — Launch WebHarvest on macOS
#
# Usage:
#   ./start_mac.sh              → Web UI (browser)
#   ./start_mac.sh desktop      → Desktop app (PyWebView)
#   ./start_mac.sh cli <args>   → CLI mode
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Check venv
if [[ ! -d ".venv" ]]; then
    echo -e "${RED}[ERROR]${NC} Virtual environment not found!"
    echo "  Run: ${CYAN}./setup_mac.sh${NC} first"
    exit 1
fi

# Activate venv
source .venv/bin/activate

MODE="${1:-web}"

case "$MODE" in
    web|server|ui)
        echo -e "${GREEN}${BOLD}🌐 Starting WebHarvest Web UI...${NC}"
        echo -e "  Opening http://localhost:8000 in browser"
        echo ""
        python -m webharvest.server
        ;;
    desktop|app)
        echo -e "${GREEN}${BOLD}🖥️  Starting WebHarvest Desktop App...${NC}"
        echo ""
        python main_desktop.py
        ;;
    cli)
        shift
        python -m webharvest "$@"
        ;;
    download|crawl|gallery)
        python -m webharvest "$@"
        ;;
    help|--help|-h)
        echo -e "${BOLD}WebHarvest Launcher${NC}"
        echo ""
        echo "Usage:"
        echo "  ./start_mac.sh                Start web UI"
        echo "  ./start_mac.sh desktop        Start desktop app"
        echo "  ./start_mac.sh cli <args>     Run CLI command"
        echo "  ./start_mac.sh download URL   Download images"
        echo "  ./start_mac.sh help           Show this help"
        echo ""
        echo "CLI Examples:"
        echo "  ./start_mac.sh download \"https://example.com\" -o ./output"
        echo "  ./start_mac.sh crawl \"https://blog.example.com\" --depth 3"
        echo "  ./start_mac.sh gallery \"https://example.com/page1\" --next-selector \".next a\""
        ;;
    *)
        echo -e "${RED}Unknown mode: $MODE${NC}"
        echo "  Run: ${CYAN}./start_mac.sh help${NC}"
        exit 1
        ;;
esac
