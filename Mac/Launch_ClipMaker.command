#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install streamlit pandas moviepy plotly curl-cffi playwright numpy
python -m playwright install chromium
bash download_plotly.sh
python download_fonts.py
python patch_streamlit.py

find_free_port() {
    for port in $(seq 8501 8510); do
        if python -c "import socket, sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ok=0
try:
    s.bind(('127.0.0.1', $port))
    ok=1
except OSError:
    ok=0
finally:
    s.close()
sys.exit(0 if ok else 1)" >/dev/null 2>&1; then
            echo "$port"
            return 0
        fi
    done
    return 1
}

PORT="$(find_free_port)"
if [ -z "$PORT" ]; then
    echo "Could not find a free local port between 8501 and 8510."
    read -p "Press Enter to close..."
    exit 1
fi

python -m streamlit run ClipMaker.py --server.port "$PORT" --server.headless false --browser.gatherUsageStats false

read -p "Press Enter to close..."
