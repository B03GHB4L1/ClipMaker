# ClipMaker v1.2 for macOS

## Recommended Option: Use the bundled app launcher

This package includes a bundled macOS app launcher inside:

- `ClipMakerApp_1.2.zip`

After unzipping it, open:

- `ClipMakerApp_1.2/ClipMaker.app`

## What the bundled app does

The app launcher opens Terminal and will try to:

- detect `python3` or `python`
- install missing Python packages
- install the Playwright Chromium browser if needed
- download the local Plotly bundle if it is missing
- apply the Streamlit theme patch if needed
- create the needed Streamlit config files
- launch ClipMaker with Streamlit in your browser

In other words: yes, the bundled macOS app is intended to act as the launcher.

## Recommended Setup Steps

1. Extract `ClipMakerApp_1.2.zip`.
2. Move the extracted `ClipMakerApp_1.2` folder somewhere normal like `Desktop` or `Documents`.
3. Open `ClipMaker.app`.
4. If macOS warns about security or quarantine, right-click the app and choose `Open`.
5. Keep the Terminal window open while using ClipMaker.

The app should launch the project in your browser.

## Important macOS Note

The launcher script checks for macOS app translocation/quarantine behavior.
If you open it directly from a quarantined temp location, it may ask you to move the ClipMaker folder first.

## Manual Terminal Setup

If you prefer not to use the bundled app, you can still run it manually:

```bash
cd "/path/to/ClipMaker_v1.2_Mac"
python3 -m pip install streamlit pandas moviepy plotly curl-cffi playwright numpy
python3 -m playwright install chromium
bash download_plotly.sh
python3 download_fonts.py
python3 patch_streamlit.py
python3 -m streamlit run ClipMaker.py --server.headless false --browser.gatherUsageStats false
```

Then open [http://localhost:8501](http://localhost:8501) if it does not open automatically.

## Optional Virtual Environment Setup

```bash
cd "/path/to/ClipMaker_v1.2_Mac"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install streamlit pandas moviepy plotly curl-cffi playwright numpy
python -m playwright install chromium
bash download_plotly.sh
python download_fonts.py
python patch_streamlit.py
python -m streamlit run ClipMaker.py --server.headless false --browser.gatherUsageStats false
```
