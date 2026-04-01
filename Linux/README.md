# ClipMaker v1.2 for Linux

## Requirements

- Python 3.10+
- `pip`
- Internet access for first-time installs and Playwright Chromium download

## Quick Start

1. Open a terminal in this folder.
2. Make the launcher executable if needed:

```bash
chmod +x Launch_ClipMaker.sh
```

3. Run the launcher:

```bash
./Launch_ClipMaker.sh
```

The app should open in your browser at [http://localhost:8501](http://localhost:8501).

## What the launcher does

`Launch_ClipMaker.sh` will:

- detect `python3` or `python`
- install missing Python packages
- install the Playwright Chromium browser if needed
- download `plotly-2.27.0.min.js` into `smp_component/frontend/`
- apply the Streamlit theme patch once
- start Streamlit on port `8501`

## Manual Setup

```bash
cd "/path/to/ClipMaker_v1.2_Linux"
python3 -m pip install --user streamlit moviepy pandas plotly curl_cffi playwright numpy
python3 -m playwright install chromium
bash download_plotly.sh
python3 download_fonts.py
python3 patch_streamlit.py
python3 -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

## Recommended Virtual Environment Setup

```bash
cd "/path/to/ClipMaker_v1.2_Linux"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install streamlit moviepy pandas plotly curl_cffi playwright numpy
python -m playwright install chromium
bash download_plotly.sh
python download_fonts.py
python patch_streamlit.py
python -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

## Linux Notes

- If `tkinter` is missing, Browse buttons may not work.
- Common install commands:
  - Debian/Ubuntu: `sudo apt install python3-tk`
  - Fedora: `sudo dnf install python3-tkinter`
  - Arch: `sudo pacman -S tk`

If the browser does not open automatically, visit [http://localhost:8501](http://localhost:8501) manually.
