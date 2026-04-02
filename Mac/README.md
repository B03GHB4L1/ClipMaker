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
- run the packaged `Launch_ClipMaker.command` script in Terminal
- launch ClipMaker with Streamlit in your browser on the first free port from `8501` to `8510`

In other words: yes, the bundled macOS app is intended to act as the launcher.

## Recommended Setup Steps

1. Extract `ClipMakerApp_1.2.zip`.
2. Keep `ClipMaker.app` inside the extracted `ClipMakerApp_1.2` folder. Do not move the app bundle away from the rest of the files.
3. If the extracted `ClipMakerApp_1.2` folder is still in `Downloads`, move the entire `ClipMakerApp_1.2` folder to a normal location like `Desktop` or `Documents`.
4. Open `ClipMaker.app` from inside the `ClipMakerApp_1.2` folder.
5. If macOS warns about security or quarantine, right-click the app and choose `Open`.
6. Keep the Terminal window open while using ClipMaker.

The app should launch the project in your browser.

## Important macOS Note

The launcher script checks for macOS app translocation/quarantine behavior.
If you open it directly from a quarantined temp location, it may ask you to move the entire `ClipMakerApp_1.2` folder first.

## Manual Terminal Setup

If you prefer not to use the bundled app, you can still run it manually:

```bash
cd "/path/to/ClipMaker_v1.2_Mac"
chmod +x ./Launch_ClipMaker.command
./Launch_ClipMaker.command
```

Or, if you want to do the setup yourself:

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
python -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

If the browser does not open automatically, use the `http://localhost:<port>` URL shown in Terminal.

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

## Common Issues

### The app closes immediately

Make sure you replaced any older copy of `ClipMakerApp_1.2.zip` with the latest one, then open `ClipMaker.app` again from inside the extracted `ClipMakerApp_1.2` folder.

### Finder says the app cannot be opened

Right-click `ClipMaker.app` and choose `Open`. If needed, remove quarantine manually:

```bash
xattr -dr com.apple.quarantine "ClipMaker.app"
```

### Browser does not open automatically

Use the `http://localhost:<port>` URL shown in Terminal manually.
