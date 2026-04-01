# Contributing to ClipMaker

Thanks for your interest in contributing to ClipMaker. This guide explains how the current `v1.2` app is structured, how to run it locally, and what to keep in mind when making changes.

---

## Project Structure

The current packaged builds are platform-specific, but the Windows package is the best reference implementation when working on features:

| Path | Purpose |
|------|---------|
| `ClipMaker_v1.2_Windows/ClipMaker.py` | Home page, file loading, kickoff setup, WhoScored scraping workflow |
| `ClipMaker_v1.2_Windows/pages/1_Filtering_Output.py` | Manual filtering, AI filtering, snapshots, clip generation/output |
| `ClipMaker_v1.2_Windows/pages/2_The_Analysts_Room.py` | Analyst Room views and interactive analysis workflows |
| `ClipMaker_v1.2_Windows/clipmaker_core.py` | Shared filtering logic, clip pipeline, AI query parsing, computed flags, utility functions |
| `ClipMaker_v1.2_Windows/smp_component/` | Custom Streamlit component for the interactive maps |
| `ClipMaker_v1.2_Windows/theme.py` | Shared UI theme and branding helpers |
| `ClipMaker_v1.2_Windows/whoscored_scraper.py` | Match scraping and data ingestion logic |
| `ClipMaker_v1.2_Windows/config/` | Football glossary, inference flags, xT grid, other app config data |

Equivalent packaged copies also exist for:

- `ClipMaker_v1.2_Mac`
- `ClipMaker_v1.2_Linux`

When you change shared product behavior, keep the packaged platform copies aligned unless there is a platform-specific reason not to.

---

## Running Locally

### Recommended target during development

Use the Windows package folder as the source of truth for app behavior unless you are explicitly working on Mac/Linux packaging.

### Requirements

- Python 3.10+
- FFmpeg available on your system PATH
- Internet access for first-run dependency installs and Playwright Chromium setup

### Install dependencies

```bash
pip install streamlit pandas moviepy plotly curl_cffi playwright numpy
python -m playwright install chromium
```

### Run the app

From inside the platform folder you are working on:

```bash
python -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

For most development work, that means:

```bash
cd ClipMaker_v1.2_Windows
python -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

---

## How the Current App Works

ClipMaker now has three main layers:

### 1. Home and data setup

`ClipMaker.py` handles:

- WhoScored URL scraping
- file selection for CSV and video(s)
- split-video setup
- kickoff timestamps
- shared session state initialization

### 2. Filtering and export

`pages/1_Filtering_Output.py` handles:

- manual filters
- quick presets
- filter snapshots
- AI-assisted querying and filter generation
- dry runs
- clip rendering
- reel assembly
- downloadable AI-generated outputs

### 3. Analyst Room

`pages/2_The_Analysts_Room.py` handles:

- Shot Map
- Pass Map
- Defensive Actions
- Dribbles & Carries
- Goalkeeper views
- Build-Up sequences
- Player Comparison
- penalty shootout inspection

### Shared core logic

`clipmaker_core.py` contains the main reusable logic, including:

- CSV validation and period assignment
- computed event flags
- filtering engine
- clip window generation and merging
- FFmpeg-based clip rendering
- AI prompt parsing
- deterministic + LLM hybrid event querying
- football glossary / alias support

---

## Filtering and AI

One of the biggest differences from earlier ClipMaker versions is that filtering is no longer just a few simple checkboxes.

The app now supports:

- manual filters by event type, half, xT, Top N, progressive actions, pitch zone, depth zone, and many boolean event flags
- quick preset filters
- saved filter snapshots
- AI-assisted prompt parsing into filter configs
- AI query answering over event data

When working in this area:

- prefer extending shared logic in `clipmaker_core.py`
- keep manual and AI flows consistent
- avoid adding UI-only logic that duplicates the underlying filter rules

---

## Analyst Room Principles

The Analyst Room is not cosmetic. It is a major product surface.

Changes here should preserve:

- fast interaction
- clear event ordering
- correct football geometry
- correct mapping of event coordinates
- clip selection workflows from map interactions

Recent examples of sensitive logic include:

- goalframe scaling
- adaptive goalframe bounds
- penalty shootout ordering
- wrapped penalty grids
- chronological shot/pass selection lists

If you touch these views, verify behavior visually, not just syntactically.

---

## Launchers

The launchers are still a critical part of the product because many users are non-technical.

Current launcher surfaces include:

| File | Platform | Purpose |
|------|----------|---------|
| `ClipMaker_v1.2_Windows/Launch_ClipMaker.bat` | Windows | Dependency install, one-time setup, app launch |
| `ClipMaker_v1.2_Linux/Launch_ClipMaker.sh` | Linux | Dependency install, one-time setup, app launch |
| `ClipMaker_v1.2_Mac/ClipMakerApp_1.2.zip` | macOS | Bundled app launcher that opens Terminal and starts ClipMaker |

### Launcher expectations

- use the correct Python executable consistently
- install only dependencies the app actually needs
- install Playwright Chromium when required
- keep `--browser.gatherUsageStats false` on Streamlit launch
- show users clear errors instead of failing silently
- preserve first-run setup steps like Plotly download and theme patching where applicable

### Launcher testing

Test launcher changes on a near-clean environment whenever possible:

- no preinstalled Streamlit
- no preinstalled Playwright browser
- missing Plotly bundle
- missing Streamlit credentials/config files

---

## Data Expectations

ClipMaker works best with event CSVs that include at minimum:

| Column | Required | Description |
|--------|----------|-------------|
| `minute` | Yes | Match clock minute |
| `second` | Yes | Match clock second |
| `type` | Yes | Event type |
| `period` | Yes | Half / period identifier |

Important optional fields include:

- `xT`
- `prog_pass`
- `prog_carry`
- `team`
- `playerName`
- `goal_mouth_y`
- `goal_mouth_z`
- computed `is_*` event flags

If you change filter logic, test against real match data, not just toy rows.

---

## Contributions Welcome

- bug fixes
- CSV compatibility fixes
- launcher reliability improvements
- new event filters or computed flags
- Analyst Room improvements
- AI prompt understanding improvements
- performance improvements in filtering or rendering
- UI and usability improvements
- cross-platform packaging fixes

---

## Please Avoid

- reverting the app back toward the old single-file architecture
- introducing heavy dependencies without a strong product reason
- breaking launcher-based setup for non-technical users
- adding features only in one platform package when they are meant to be shared
- changing football visual geometry without checking the actual rendered result

---

## Submitting a Pull Request

1. Fork the repo.
2. Create a descriptive branch.
3. Make your changes.
4. Test with a real match CSV and video where possible.
5. Verify platform sync if your change affects packaged app behavior.
6. Open a pull request with:
   - what changed
   - why it changed
   - what you tested
   - whether the change is Windows-only or synced across platforms

---

*ClipMaker by B4L1 — [@B03GHB4L1](https://x.com/B03GHB4L1)*
