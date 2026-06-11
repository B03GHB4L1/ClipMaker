# Contributing to ClipMaker

Thanks for your interest in contributing to ClipMaker. This guide explains how the current `v1.2.3` app is structured, how to run it locally, and what to keep in mind when making changes.

---

## Project Structure

The current repo keeps separate platform folders. The Windows package is the best reference implementation when working on shared product behavior:

| Path | Purpose |
|------|---------|
| `Windows/ClipMaker.py` | Home page, file loading, kickoff setup, WhoScored/Scoresway scraping workflow |
| `Windows/pages/1_Filtering_Output.py` | Manual filtering, AI filtering, snapshots, clip generation/output |
| `Windows/pages/2_The_Analysts_Room.py` | Analyst Room views, interactive maps, chart exports, and analysis workflows |
| `Windows/pages/3_Tactical_Lab.py` | Tactical Lab, transition analysis, style profiles, restart analysis, and tactical video playlists |
| `Windows/clipmaker_core.py` | Shared filtering logic, clip pipeline, AI query parsing, computed flags, timestamp mapping, utility functions |
| `Windows/whoscored_scraper.py` | WhoScored match scraping and event normalization |
| `Windows/scoresway_scraper.py` | Scoresway/PerformFeeds scraping and event normalization |
| `Windows/smp_component/` | Custom Streamlit component for interactive maps, PNG export, and GIF export |
| `Windows/theme.py` | Shared UI theme and branding helpers |
| `Windows/config/` | Football glossary, inference flags, Opta event reference, xT grid, and app config data |

Equivalent packaged copies also exist for:

- `Mac`
- `Linux`

When you change shared product behavior, keep the packaged platform copies aligned unless there is a platform-specific reason not to.

---

## Running Locally

### Recommended target during development

Use the `Windows` folder as the source of truth for app behavior unless you are explicitly working on Mac/Linux packaging.

### Requirements

- Python 3.10+
- FFmpeg available on your system PATH
- Internet access for first-run dependency installs and Playwright Chromium setup

### Install dependencies

```bash
pip install streamlit pandas moviepy plotly curl_cffi playwright numpy
python -m playwright install chromium
```

Some map/export workflows also rely on local frontend assets in `smp_component/frontend/`. The packaged launchers handle this setup automatically.

### Run the app

From inside the platform folder you are working on:

```bash
python -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

For most development work, that means:

```bash
cd Windows
python -m streamlit run ClipMaker.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
```

---

## How the Current App Works

ClipMaker has four main product layers:

### 1. Home and Data Setup

`ClipMaker.py` handles:

- WhoScored and Scoresway URL scraping
- automatic source detection for pasted match URLs
- saved scraped-match selection
- file selection for CSV and video files
- single-file, split-half, extra-time, and penalty-shootout video setup
- kickoff timestamps and first-penalty timestamp setup
- shared session state initialization

### 2. Filtering and Export

`pages/1_Filtering_Output.py` handles:

- manual filters
- quick presets
- filter snapshots
- AI-assisted querying and filter generation
- dry runs
- clip rendering
- reel assembly
- downloadable AI-generated outputs
- extra-time and shootout video routing during clip generation

### 3. Analyst Room

`pages/2_The_Analysts_Room.py` handles:

- Shot Map and goalframe views
- penalty shootout inspection
- Pass Map and pass networks
- Defensive Actions
- Dribbles & Carries
- Goalkeeper views
- Build-Up sequences
- Pressing Map
- Player Comparison
- Top 5 Moments widgets
- presentation-ready chart/map export context

### 4. Tactical Lab

`pages/3_Tactical_Lab.py` handles:

- multi-match team analysis
- defensive and attacking transition profiles
- style profile radar
- progression funnel
- territory heatmap
- restart and set-piece profiles
- tactical video playlists and reel building

### Shared Core Logic

`clipmaker_core.py` contains the main reusable logic, including:

- CSV validation and period assignment
- computed event flags
- filtering engine
- clip window generation and merging
- match-clock to video-time conversion
- extra-time and penalty-shootout timestamp handling
- FFmpeg-based clip rendering
- AI prompt parsing
- safe AI data-expression execution
- deterministic + LLM hybrid event querying
- football glossary / alias support

---

## Scrapers and Data Sources

ClipMaker now supports both WhoScored and Scoresway.

When changing scraper behavior:

- keep output columns compatible with the filtering, Analyst Room, and Tactical Lab workflows
- preserve `minute`, `second`, `type`, `period`, `team`, and `playerName` wherever possible
- preserve computed flags such as `xT`, `prog_pass`, `prog_carry`, and `is_*` qualifiers when available
- remember that WhoScored and Scoresway data are not identical, so small analytical differences are expected
- test downstream pages with real scraped files, not only the scraper output

---

## Filtering and AI

One of the biggest differences from early ClipMaker versions is that filtering is no longer just a few simple checkboxes.

The app now supports:

- manual filters by event type, half, xT, Top N, progressive actions, pitch zone, depth zone, and many boolean event flags
- quick preset filters
- saved filter snapshots
- AI-assisted prompt parsing into filter configs
- AI query answering over event data
- natural-language support for switches, diagonals, box entries, final-third entries, penalties, touch-in-box actions, and successful take-ons in the box

When working in this area:

- prefer extending shared logic in `clipmaker_core.py`
- keep manual and AI flows consistent
- avoid adding UI-only logic that duplicates the underlying filter rules
- test mixed reels where xT/progressive filters are combined with non-pass/carry actions

---

## Analyst Room Principles

The Analyst Room is not cosmetic. It is a major product surface.

Changes here should preserve:

- fast interaction
- clear event ordering
- correct football geometry
- correct mapping of event coordinates
- clip selection workflows from map interactions
- export-ready chart context, filenames, and branding

Sensitive logic includes:

- goalframe scaling
- adaptive goalframe bounds
- penalty shootout ordering
- wrapped penalty grids
- chronological shot/pass/action selection lists
- PNG and animated GIF export controls

If you touch these views, verify behavior visually, not just syntactically.

---

## Tactical Lab Principles

The Tactical Lab is used for team-level interpretation, so changes should preserve analytical consistency.

When working here, check:

- transition windows and outcome labels
- xT aggregation for passes, carries, transitions, and restarts
- multi-match selection behavior
- per-match normalization where used
- restart categorization
- chart labels and export context
- video playlist timestamp mapping

---

## Launchers

The launchers are still a critical part of the product because many users are non-technical.

Current launcher surfaces include:

| File | Platform | Purpose |
|------|----------|---------|
| `Windows/Launch_ClipMaker.bat` | Windows | Dependency install, one-time setup, app launch |
| `Linux/Launch_ClipMaker.sh` | Linux | Dependency install, local virtual environment setup, app launch |
| `Mac/Launch_ClipMaker.command` | macOS | Local virtual environment setup, dependency install, app launch |

### Launcher Expectations

- use the correct Python executable consistently
- install only dependencies the app actually needs
- install Playwright Chromium when required
- keep `--browser.gatherUsageStats false` on Streamlit launch
- download required local frontend assets when needed
- apply the Streamlit theme patch when needed
- choose a free local port from `8501` to `8510`
- show users clear errors instead of failing silently

### Launcher Testing

Test launcher changes on a near-clean environment whenever possible:

- no preinstalled Streamlit
- no preinstalled Playwright browser
- missing Plotly bundle
- missing local map/export frontend assets
- missing Streamlit credentials/config files
- missing `tkinter`, especially on Linux

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
- `homeTeam`
- `awayTeam`
- `matchName`
- `matchDate`
- computed `is_*` event flags

If you change filter logic, test against real match data, not just toy rows.

---

## Contributions Welcome

- bug fixes
- CSV compatibility fixes
- scraper reliability improvements
- launcher reliability improvements
- new event filters or computed flags
- Analyst Room improvements
- Tactical Lab improvements
- AI prompt understanding improvements
- map, PNG, or GIF export improvements
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
- assuming WhoScored and Scoresway will expose exactly the same tags or qualifiers

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
