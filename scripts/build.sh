#!/usr/bin/env bash
set -e

echo "========================================"
echo " WebHarvest Desktop - macOS/Linux Build"
echo "========================================"
echo

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.9+ first."
    exit 1
fi

echo "[1/3] Installing dependencies..."
pip3 install -r requirements.txt --quiet
pip3 install pyinstaller --quiet

echo "[2/3] Building desktop app..."
python3 build_desktop.py

echo "[3/3] Done!"
echo
echo "Output: dist/WebHarvest/WebHarvest"
echo
