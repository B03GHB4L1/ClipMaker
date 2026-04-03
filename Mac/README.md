# ClipMaker v1.2 for macOS

ClipMaker is a local football video clipping and analysis app for macOS.

This Mac package uses:

- `Launch_ClipMaker.command` as the main launcher
- `RUN_IN_TERMINAL.txt` as the step-by-step backup guide

## Before You Start

You need:

- macOS
- Python 3.10 or later
- internet access on first launch so ClipMaker can install required packages

If Python is not already installed, download it from [python.org](https://www.python.org/downloads/).

## First Run

1. Extract the Mac package.
2. Move the extracted `ClipMaker_v1.2_Mac` folder to a normal location like `Desktop` or `Documents`.
3. Open `RUN_IN_TERMINAL.txt`.
4. Follow the steps in that file.
5. Keep the Terminal window open while using ClipMaker.

## What the Folder Should Contain

You should see files like:

- `ClipMaker.py`
- `clipmaker_core.py`
- `whoscored_scraper.py`
- `Launch_ClipMaker.command`
- `RUN_IN_TERMINAL.txt`
- `README.md`
- `pages/`
- `static/`
- `smp_component/`

## What the Launch Commands Do

On first run, the commands will:

- create a local Python virtual environment in `.venv`
- install required Python packages
- install the Playwright Chromium browser if needed
- download the local Plotly bundle if needed
- apply the Streamlit theme patch if needed
- launch the app in your browser

The launcher uses the first free local port from `8501` to `8510`.

## If macOS Blocks the Launcher

If macOS refuses to open `Launch_ClipMaker.command`, open Terminal and run:

```bash
xattr -dr com.apple.quarantine "/path/to/ClipMaker_v1.2_Mac"
chmod +x "/path/to/ClipMaker_v1.2_Mac/Launch_ClipMaker.command"
```

Then try `Launch_ClipMaker.command` again.

## Using ClipMaker

On macOS, ClipMaker uses native in-app `Browse` buttons for:

- video files
- second-half video files
- match CSV files

You do not need to upload those files through the browser.

## If the Browser Does Not Open Automatically

Use the `http://localhost:<port>` URL shown in Terminal.

## Manual Terminal Method

If you want the short version instead of reading `RUN_IN_TERMINAL.txt`, use:

```bash
cd "/path/to/ClipMaker_v1.2_Mac"
chmod +x ./Launch_ClipMaker.command
./Launch_ClipMaker.command
```

The launcher will handle dependency installation and will choose the first free local port from `8501` to `8510`.
