# Contributing to ClipMaker

Thanks for your interest in contributing. This document explains how the project is structured, how to run it locally, and what kinds of contributions are welcome.

---

## Project Structure

ClipMaker is intentionally kept as a single file:

| File | Purpose |
|------|---------|
| `app_streamlit.py` | The entire application — UI, filtering logic, FFmpeg integration |

The single-file structure is a deliberate design decision. ClipMaker's users are football analysts, scouts, and comp makers, not developers. They receive the app as a simple download and run it via a launcher. Splitting into modules would complicate distribution without benefiting end users.

---

## Running Locally

**Requirements:**
- Python 3.8+
- FFmpeg installed and on your PATH (or accessible via MoviePy's bundled binary)

**Install dependencies:**
```bash
pip install streamlit pandas moviepy
```

**Run the app:**
```bash
python -m streamlit run app_streamlit.py
```

---

## How the App Works

The core pipeline in `app_streamlit.py`:

1. **CSV loading** — reads event data with `minute`, `second`, `type`, `period` columns
2. **Period assignment** — maps `FirstHalf`/`SecondHalf` text values or 1/2 integers to resolved period numbers
3. **Filtering** — applies action type, progressive, xT, Top N, and half filters in order
4. **Timestamp mapping** — converts each event's match clock time to a video file position using the user-supplied kick-off timestamps
5. **Window merging** — events within `min_gap` seconds of each other are merged into a single clip
6. **FFmpeg cutting** — clips are cut directly via FFmpeg subprocess calls (no MoviePy for rendering)
7. **Assembly** — individual clips are either saved separately or concatenated using FFmpeg's concat demuxer

**Split video mode** — when a match is split into two files, period 1 events are cut from `video1` and period 2+ events from `video2`. Timestamps are relative to each file's own timeline independently.

**Key functions:**
- `apply_filters()` — all filtering logic lives here
- `run_clip_maker()` — the main pipeline, runs in a background thread
- `cut_clip_ffmpeg()` — cuts a single clip using FFmpeg directly
- `cut_and_concat_ffmpeg()` — cuts all clips to temp files then concatenates
- `get_video_duration()` — reads duration from FFmpeg stderr output
- `monitor_file_progress()` — background thread that watches output file size for progress bar

---

## CSV Format Expected

Event CSVs are sourced from [Insight90](https://insight90.streamlit.app) — a match analysis tool that exports player event data in this format. If testing locally, export a CSV from there and use it as your reference.

| Column | Required | Description |
|--------|----------|-------------|
| `minute` | Yes | Match clock minute |
| `second` | Yes | Match clock second |
| `type` | Yes | Action type (Pass, Carry, Shot, etc.) |
| `period` | Yes | FirstHalf / SecondHalf or 1 / 2 |
| `xT` | No | Expected threat value — unlocks xT filters |
| `prog_pass` | No | Progressive pass distance — unlocks progressive filter |
| `prog_carry` | No | Progressive carry distance — unlocks progressive filter |

---

## Launchers

The launchers are as important as the app itself — they are the first thing a non-technical user interacts with. There are two:

| File | Platform | Description |
|------|----------|-------------|
| `Launch_ClipMaker.bat` | Windows | Batch file that checks Python, installs dependencies, and launches Streamlit |
| `ClipMaker.app` | Mac | Double-clickable app bundle that opens Terminal, checks Python, installs dependencies, and launches Streamlit |

**Key principles for launcher changes:**
- Always use `python -m pip install` rather than bare `pip` — ensures the correct Python environment is used
- Check packages with `python -c "import X"` rather than `pip show X` — more reliable across environments
- Show pip output during installs so errors are visible to the user
- Never suppress errors silently — if something fails, tell the user clearly and tell them what to do
- The `--browser.gatherUsageStats false` flag must always be present on the Streamlit launch command to suppress the first-run email prompt
- Mac app bundle must detect App Translocation (when run directly from Downloads) and auto-copy to Desktop before launching

**Testing launchers:**
- Test on a clean Python install with no packages to verify the install flow works end to end
- On Windows, uninstall Streamlit and delete `%USERPROFILE%\.streamlit` to simulate a first-time run
- On Mac, move the folder to Downloads and verify the translocation detection triggers correctly

---



- **Bug fixes** — especially around edge cases in CSV formats, video file types, or timestamp parsing
- **New filter types** — additional ways to slice event data (e.g. outcome filter, player filter if name column exists)
- **Performance improvements** — FFmpeg command optimisation, faster concatenation
- **UI improvements** — layout, usability, accessibility
- **Platform compatibility** — fixes for Mac/Linux edge cases

## Please Avoid

- Breaking the single-file structure — this is intentional (see above)
- Adding dependencies that aren't installable via a simple `pip install`
- Changes that require users to interact with the command line
- Anything that makes the app harder for non-technical users to run

---

## Submitting a Pull Request

1. Fork the repo
2. Create a branch with a descriptive name (e.g. `fix-mkv-audio-streams`, `add-outcome-filter`)
3. Make your changes
4. Test with a real match CSV and video file
5. Open a pull request with a clear description of what changed and why

---

*ClipMaker by B4L1 — [@B03GHB4L1](https://x.com/B03GHB4L1)*
