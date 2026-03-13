#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "==============================================="
echo "  ClipMaker v1.2 by B4L1 - Starting up..."
echo "==============================================="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] python3 is not installed."
  echo "Install Python from https://www.python.org/downloads/ and run this launcher again."
  read -n 1 -s -r -p "Press any key to exit..."
  echo ""
  exit 1
fi

echo "[..] Checking required packages..."
python3 -m pip install --user --upgrade pip >/dev/null 2>&1 || true
python3 -m pip install --user streamlit moviepy pandas curl_cffi opencv-python scenedetect numpy >/dev/null 2>&1 || true

echo "[OK] Launching ClipMaker in your browser..."
python3 -m streamlit run "$SCRIPT_DIR/ClipMaker.py" --server.headless false --browser.gatherUsageStats false
