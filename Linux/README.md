# ClipMaker v1.2 for Linux

## Requirements

- Python 3.10+
- `pip`
- `python3-venv` on Debian/Ubuntu/WSL
- Internet access for first-time installs and Playwright Chromium download

## Quick Start

1. Open a terminal in this folder.
2. Run the launcher:

```bash
bash Launch_ClipMaker.sh
```

If you are on a normal Linux filesystem and want to make it executable first, you can also do:

```bash
chmod +x Launch_ClipMaker.sh
./Launch_ClipMaker.sh
```

The app should open in your browser at [http://localhost:8501](http://localhost:8501).
If port `8501` is busy, the launcher will automatically use the next free port up to `8510`.

## What the launcher does

`Launch_ClipMaker.sh` will:

- detect `python3` or `python`
- create and use a local `.venv` automatically when needed
- install missing Python packages
- install the Playwright Chromium browser if needed
- download `plotly-2.27.0.min.js` into `smp_component/frontend/`
- apply the Streamlit theme patch once
- start Streamlit on the first free port from `8501` to `8510`

## Manual Setup

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

If `python3 -m venv .venv` fails on Debian/Ubuntu/WSL, install:

```bash
sudo apt install python3-venv
```

## Recommended Virtual Environment Setup

This is effectively what the launcher now does automatically:

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
  - Debian/Ubuntu: `sudo apt install python3-tk python3-venv`
  - Fedora: `sudo dnf install python3-tkinter`
  - Arch: `sudo pacman -S tk`
- On WSL, test from the Linux filesystem such as `~/clipmaker-test/`, not directly from `/mnt/c/...`, because virtual environment creation is more reliable there.
- On `/mnt/c/...` under WSL, `chmod +x` may fail with `Operation not permitted`; in that case just run `bash Launch_ClipMaker.sh`.

If the browser does not open automatically, visit the `http://localhost:<port>` URL shown in the terminal manually.
