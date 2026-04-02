#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo " ================================================"
echo "   ClipMaker v1.2 by B4L1 - Starting up..."
echo " ================================================"
echo ""

# -----------------------------------------------
# STEP 1 - Check Python
# -----------------------------------------------
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
fi

if [ -z "$PYTHON" ]; then
    echo " [!] Python is not installed on this computer."
    echo ""
    echo " To fix this, install Python 3 using your package manager:"
    echo ""
    echo "   Debian/Ubuntu:  sudo apt install python3 python3-pip python3-venv"
    echo "   Fedora:         sudo dnf install python3 python3-pip"
    echo "   Arch:           sudo pacman -S python python-pip"
    echo ""
    echo " Then re-run this script."
    echo ""
    read -p " Press Enter to exit..."
    exit 1
fi

echo " [OK] Python is installed ($($PYTHON --version 2>&1))."

# -----------------------------------------------
# STEP 2 - Create/use local virtual environment
# Avoid Linux/WSL PEP 668 "externally managed" pip errors
# -----------------------------------------------
if [ -z "$VIRTUAL_ENV" ] && [ -z "$CONDA_PREFIX" ] && ! $PYTHON -c "import sys; exit(0 if sys.prefix != sys.base_prefix else 1)" &>/dev/null; then
    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        echo " [..] Creating local Python environment in .venv ..."
        if ! $PYTHON -m venv "$VENV_DIR" &>/dev/null; then
            echo " [!] Could not create a virtual environment."
            echo ""
            echo " On Debian/Ubuntu/WSL, install the venv package first:"
            echo "   sudo apt install python3-venv"
            echo ""
            echo " Then run this launcher again."
            echo ""
            read -p " Press Enter to exit..."
            exit 1
        fi
        echo " [OK] Local environment created."
        echo ""
    fi

    PYTHON="$VENV_DIR/bin/python"
    export VIRTUAL_ENV="$VENV_DIR"
    export PATH="$VENV_DIR/bin:$PATH"
    echo " [OK] Using local virtual environment: $VENV_DIR"
    echo ""
fi

# -----------------------------------------------
# STEP 3 - Install missing packages
# -----------------------------------------------
echo " [..] Checking required packages..."
echo ""

check_and_install() {
    local module="$1"
    local package="${2:-$1}"
    if ! $PYTHON -c "import $module" &>/dev/null; then
        echo " [..] Installing $package..."
        $PYTHON -m pip install "$package"
        echo ""
    fi
}

check_and_install streamlit
check_and_install moviepy
check_and_install pandas
check_and_install plotly
check_and_install curl_cffi
check_and_install playwright
check_and_install numpy

# Install Playwright Chromium browser (one-time, ~150MB)
if ! $PYTHON -c "
from playwright.sync_api import sync_playwright
import os
p = sync_playwright().start()
b = p.chromium.executable_path
p.stop()
exit(0 if os.path.exists(b) else 1)
" &>/dev/null; then
    echo " [..] Downloading Chromium browser for supplementary data (one-time, ~150MB)..."
    $PYTHON -m playwright install chromium
    echo ""
fi

# Warn if tkinter is missing (Browse buttons won't work)
if ! $PYTHON -c "import tkinter" &>/dev/null; then
    echo ""
    echo " [!] A component called tkinter is missing."
    echo "     The Browse buttons may not work."
    echo "     To fix this, install it with:"
    echo ""
    echo "   Debian/Ubuntu:  sudo apt install python3-tk"
    echo "   Fedora:         sudo dnf install python3-tkinter"
    echo "   Arch:           sudo pacman -S tk"
    echo ""
fi

# Final check - streamlit must be importable
if ! $PYTHON -c "import streamlit" &>/dev/null; then
    echo ""
    echo " [!] Streamlit could not be installed."
    echo ""
    echo " Please take a screenshot of this window and"
    echo " send it to whoever shared this app with you."
    echo ""
    read -p " Press Enter to exit..."
    exit 1
fi

# -----------------------------------------------
# STEP 3b - Download Plotly.js for Analyst Room maps (one-time)
# -----------------------------------------------
PLOTLY_JS="$SCRIPT_DIR/smp_component/frontend/plotly-2.27.0.min.js"
if [ ! -f "$PLOTLY_JS" ]; then
    echo " [..] Downloading Plotly.js for Analyst Room maps (one-time)..."
    curl -sL -o "$PLOTLY_JS" "https://cdn.plot.ly/plotly-2.27.0.min.js"
    if [ -f "$PLOTLY_JS" ]; then
        echo " [OK] Plotly.js downloaded."
    else
        echo " [!] Could not download Plotly.js - maps may not render."
        echo "     You can download it manually from:"
        echo "     https://cdn.plot.ly/plotly-2.27.0.min.js"
        echo "     and save it to: smp_component/frontend/plotly-2.27.0.min.js"
    fi
    echo ""
fi

echo " [OK] All packages ready."
echo ""

# -----------------------------------------------
# STEP 3c - Patch Streamlit index.html (one-time)
# -----------------------------------------------
STREAMLIT_INDEX=$($PYTHON -c "import streamlit, os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static', 'index.html'))" 2>/dev/null)
if [ -n "$STREAMLIT_INDEX" ] && [ -f "$STREAMLIT_INDEX" ]; then
    if ! grep -q "CLIPMAKER_THEME_START" "$STREAMLIT_INDEX" 2>/dev/null; then
        echo " [..] Applying ClipMaker theme patch to Streamlit (one-time)..."
        $PYTHON "$SCRIPT_DIR/patch_streamlit.py" &>/dev/null
        echo " [OK] Theme patch applied."
        echo ""
    fi
fi

# Ensure Streamlit credentials file exists (suppresses email prompt)
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
    chmod 600 "$HOME/.streamlit/credentials.toml"
fi

# -----------------------------------------------
# STEP 4 - Launch
# -----------------------------------------------
echo " [..] Opening ClipMaker v1.2 in your browser..."
echo ""
echo " Note: A browser tab will open automatically."
echo " Keep this window open while using the app."
echo " Close this window when you are done."
echo ""
echo " ================================================"
echo ""

find_free_port() {
    for port in $(seq 8501 8510); do
        if ! $PYTHON -c "import socket, sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ok=0
try:
    s.bind(('127.0.0.1', $port))
    ok=1
except OSError:
    ok=0
finally:
    s.close()
sys.exit(0 if ok else 1)" &>/dev/null; then
            continue
        fi
        echo "$port"
        return 0
    done
    return 1
}

PORT="$(find_free_port)"
if [ -z "$PORT" ]; then
    echo " [!] Could not find a free local port between 8501 and 8510."
    echo "     Please close other local web apps and try again."
    read -p " Press Enter to exit..."
    exit 1
fi

if [ "$PORT" = "8501" ]; then
    echo " [..] Launching ClipMaker on http://localhost:$PORT ..."
else
    echo " [!] Port 8501 is busy."
    echo " [..] Launching ClipMaker on http://localhost:$PORT instead ..."
fi

_open_browser() {
    sleep 3
    if command -v xdg-open &>/dev/null; then
        xdg-open "http://localhost:$PORT" &>/dev/null
    elif command -v sensible-browser &>/dev/null; then
        sensible-browser "http://localhost:$PORT" &>/dev/null
    elif command -v firefox &>/dev/null; then
        firefox "http://localhost:$PORT" &>/dev/null
    elif command -v google-chrome &>/dev/null; then
        google-chrome "http://localhost:$PORT" &>/dev/null
    elif command -v chromium-browser &>/dev/null; then
        chromium-browser "http://localhost:$PORT" &>/dev/null
    else
        echo " [!] Could not open browser automatically."
        echo "     Please open http://localhost:$PORT in your browser manually."
    fi
}
_open_browser &

$PYTHON -m streamlit run "$SCRIPT_DIR/ClipMaker.py" \
    --server.port "$PORT" \
    --server.headless false \
    --browser.gatherUsageStats false
