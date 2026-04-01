# ClipMaker v1.2 for Windows

## Requirements

- Windows 10 or newer
- Python 3.10+ installed and available on `PATH`
- Internet access for first-time package installs and Playwright Chromium download

## Quick Start

1. Open this folder in File Explorer.
2. Double-click `Launch_ClipMaker.bat`.
3. Wait for the setup checks to finish.
4. Your browser should open `http://localhost:8501`.

Keep the launcher window open while you use the app.

## What the launcher does

`Launch_ClipMaker.bat` will:

- verify Python is installed
- install missing Python packages with `python -m pip install --user`
- install the Playwright Chromium browser if needed
- download `plotly-2.27.0.min.js` into `smp_component/frontend/`
- apply the Streamlit theme patch once
- start the app with Streamlit on port `8501`

## Manual Setup

If you want to set it up yourself in PowerShell:

```powershell
cd "C:\path\to\ClipMaker_v1.2_Windows"
python -m pip install --user streamlit moviepy pandas plotly curl_cffi playwright numpy
python -m playwright install chromium
python download_fonts.py
python patch_streamlit.py
```

Then launch:

```powershell
python -m streamlit run .\ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

## Optional Helper Scripts

- `download_plotly.bat`: downloads the local Plotly bundle used by the Analyst Room maps
- `download_fonts.py`: downloads local font files into `static/fonts/`

## Common Issues

### Python is not found

Install Python from [python.org](https://www.python.org/downloads/) and make sure `Add Python to PATH` is checked during setup.

### Browser does not open automatically

Open [http://localhost:8501](http://localhost:8501) manually.

### Browse buttons do not work

Your Python install may be missing `tkinter`. Reinstall Python with the default Windows options.

