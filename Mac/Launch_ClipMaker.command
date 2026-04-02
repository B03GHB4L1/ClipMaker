#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

clear
echo ""
echo " ================================================"
echo "   ClipMaker v1.2 by B4L1 - Starting up..."
echo " ================================================"
echo ""

PYTHON=""
PIP=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
    PIP="pip3"
elif command -v python &>/dev/null; then
    PYTHON="python"
    PIP="pip"
else
    echo " [!] Python is not installed."
    echo " Go to https://www.python.org/downloads"
    echo " and install Python, then open this app again."
    read -p " Press Enter to close..."
    exit 1
fi

echo " [OK] Python found."
echo " [..] Checking required packages..."
echo ""

for PACKAGE in streamlit pandas moviepy plotly curl-cffi playwright numpy; do
    if ! "$PYTHON" -m pip show "$PACKAGE" &>/dev/null; then
        echo " [..] Installing $PACKAGE..."
        "$PIP" install "$PACKAGE" --quiet
    fi
done

if ! "$PYTHON" -c "from playwright.sync_api import sync_playwright; import os; p=sync_playwright().start(); b=p.chromium.executable_path; p.stop(); exit(0 if os.path.exists(b) else 1)" &>/dev/null; then
    echo " [..] Downloading Chromium browser for supplementary data (one-time)..."
    "$PYTHON" -m playwright install chromium
    echo ""
fi

PLOTLY_JS="$SCRIPT_DIR/smp_component/frontend/plotly-2.27.0.min.js"
if [ ! -f "$PLOTLY_JS" ]; then
    echo " [..] Downloading Plotly.js for Analyst Room maps (one-time)..."
    curl -sL -o "$PLOTLY_JS" "https://cdn.plot.ly/plotly-2.27.0.min.js" || true
    echo ""
fi

echo " [OK] All packages ready."
echo ""

STREAMLIT_INDEX=$("$PYTHON" -c "import streamlit, os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static', 'index.html'))" 2>/dev/null)
if [ -n "$STREAMLIT_INDEX" ] && [ -f "$STREAMLIT_INDEX" ]; then
    if ! grep -q "CLIPMAKER_THEME_START" "$STREAMLIT_INDEX" 2>/dev/null; then
        echo " [..] Applying ClipMaker theme patch to Streamlit (one-time)..."
        "$PYTHON" "$SCRIPT_DIR/patch_streamlit.py" &>/dev/null || true
        echo " [OK] Theme patch applied."
        echo ""
    fi
fi

mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

mkdir -p "$SCRIPT_DIR/.streamlit"
printf '[server]\nmaxUploadSize = 0\n' > "$SCRIPT_DIR/.streamlit/config.toml"

echo " [..] Opening ClipMaker v1.2 in your browser..."
echo ""
echo " Keep this window open while using the app."
echo " Close this window when you are done."
echo ""
echo " ================================================"
echo ""

find_free_port() {
    for port in $(seq 8501 8510); do
        if "$PYTHON" -c "import socket, sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ok=0
try:
    s.bind(('127.0.0.1', $port))
    ok=1
except OSError:
    ok=0
finally:
    s.close()
sys.exit(0 if ok else 1)" &>/dev/null; then
            echo "$port"
            return 0
        fi
    done
    return 1
}

PORT="$(find_free_port)"
if [ -z "$PORT" ]; then
    echo " [!] Could not find a free local port between 8501 and 8510."
    echo "     Please close other local web apps and try again."
    read -p " Press Enter to close..."
    exit 1
fi

if [ "$PORT" = "8501" ]; then
    echo " [..] Launching ClipMaker on http://localhost:$PORT ..."
else
    echo " [!] Port 8501 is busy."
    echo " [..] Launching ClipMaker on http://localhost:$PORT instead ..."
fi

"$PYTHON" -m streamlit run "$SCRIPT_DIR/ClipMaker.py" --server.port "$PORT" --server.headless false --browser.gatherUsageStats false

read -p " Press Enter to close..."
