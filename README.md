# ⚽ ClipMaker
**Football video clipping and analysis workstation built from match event data**

Built by [@B03GHB4L1](https://x.com/B03GHB4L1)

---

## What it does

ClipMaker turns match event data and match video into a local football analysis and clipping workflow.

You can use it to:

- scrape match events from WhoScored
- load your own event CSV and match video files
- explore the match inside an interactive Analyst Room
- filter events manually or with AI-assisted prompts
- generate individual clips or a combined highlight reel automatically

It started as a clip cutter. In `v1.2`, it is much closer to a full analyst toolkit.

---

## Core Features

### Data ingestion

- **WhoScored scraper built in** — load a match directly from a WhoScored URL
- **CSV import workflow** for your own event data
- **Single-file or split-video support** for one full match file or separate half files
- **Kick-off timestamp mapping** for 1st half, 2nd half, extra time, and penalties where needed

### Clipping and output

- **Automatic clip generation** from event timestamps
- **Individual clips or combined reel** output
- **Dry run mode** to preview clip windows before rendering
- **Merge-gap logic** to combine nearby actions into cleaner sequences
- **Live progress feedback** during clip rendering and reel assembly
- **FFmpeg-based cutting and concatenation** for faster and more reliable output handling

### Manual filtering

- **Action type filters** for passes, carries, shots, defensive actions, and more
- **xT threshold filter**
- **Top N by xT**
- **Progressive action filter**
- **Half filter**
- **Pitch zone filter**
- **Depth zone filter**
- **Boolean event filters** such as:
  - key passes
  - crosses
  - long balls
  - switches of play
  - diagonals
  - through balls
  - deep completions
  - box entry passes
  - final third entries
  - big chances created
  - assist sub-types
  - touch in box
  - and other computed football event flags

### AI-assisted filtering

- **ClipMaker AI tab** for natural-language clip requests
- **Deterministic + LLM hybrid query pipeline**
  - first resolves teams, players, halves, event types, and boolean tags using code
  - then uses an LLM layer for interpretation and response generation
- **Natural-language filter parsing** into app filter settings
- **AI-generated clip outputs** with downloadable rendered clips/reels
- **Football glossary and alias system** to improve prompt understanding
- **Proxy-backed model fallback flow** for the AI layer

### Workflow helpers

- **Quick filter presets** like set pieces, ball progression, attacking chaos, and defensive display
- **Filter snapshots** so users can save and reload filter configurations across sessions
- **Browser-based local UI** built in Streamlit
- **Packaged launchers** for Windows, macOS, and Linux

---

## Analyst Room

The Analyst Room is a separate multi-view analysis workspace inside the app.

It includes:

- **Shot Map**
  - normal shot view
  - goalframe view
  - penalty shootout mode
- **Pass Map**
  - player pass view
  - pass network view
- **Defensive Actions Map**
- **Dribbles & Carries Map**
- **Goalkeeper Map**
  - actions view
  - shots faced view
- **Build-Up View**
  - progressive chain detection
  - chain inspection and clip extraction
- **Player Comparison**
  - comparison radar
  - role-aware comparison logic
  - Top 5 Moments widgets

Recent improvements also include:

- professional goalframe proportions
- adaptive goalframe scaling for out-of-frame shots
- dedicated penalty shootout layout
- chronological shootout ordering
- wrapped shootout rows after 5 penalties

---

## Download

Go to the [Releases](../../releases) page and download the package for your platform:

- **Windows**
- **macOS**
- **Linux**

Each package includes platform-specific setup instructions and launchers.

---

## Requirements

- Python 3.10 or later recommended
- Match video file(s)
- Event CSV data or a WhoScored match URL

Packaged launchers handle first-run dependency setup for supported builds.

---

## How it works

1. Load a match by scraping WhoScored or importing your own CSV
2. Load one or two match video files
3. Enter kick-off timestamps that match your video timeline
4. Explore the match in the Analyst Room or go straight to filtering
5. Build your export using manual filters or AI prompts
6. Render either individual clips or a combined reel

ClipMaker maps event times to the video timeline, builds clip windows around the selected moments, merges nearby events when appropriate, and exports the final result locally.

---

## CSV Format

Minimum required columns:

| Column | Description |
|--------|-------------|
| `minute` | Match clock minute |
| `second` | Match clock second |
| `type` | Event type, e.g. `Pass`, `Carry`, `Shot` |
| `period` | Half identifier, e.g. `FirstHalf` / `SecondHalf` or `1` / `2` |

Useful optional columns:

| Column | Unlocks |
|--------|---------|
| `xT` | xT threshold filters and Top N by xT |
| `prog_pass` | Progressive pass filtering |
| `prog_carry` | Progressive carry filtering |
| `goal_mouth_y` | Goalframe shot placement views |
| `goal_mouth_z` | Goalframe shot placement views |
| `team` | Team filtering and comparison features |
| `playerName` | Player filtering, AI prompts, comparison, and map views |
| computed `is_*` flags | Rich boolean filters and AI-assisted interpretation |

---

## Changelog

### v1.2

- Expanded from a simple clip generator into a **multi-page analysis + clipping app**
- Added **WhoScored scraping**
- Added the **Analyst Room**
- Added **Shot Map**, **Pass Map**, **Defensive Actions**, **Dribbles & Carries**, **Goalkeeper**, **Build-Up**, and **Comparison** views
- Added **Penalty Shootout analysis**
- Added **ClipMaker AI** with natural-language filtering and AI-generated clip workflows
- Added **quick presets** and **filter snapshots**
- Added richer computed football event flags and query parsing
- Improved packaged launchers and first-run setup flow
- Added custom frontend map components, local assets, and stronger theming

### v1.1

- Action type, progressive, xT, and Top N filters
- Split video file support
- Half filter
- Live assembly progress bar with ETA
- Finalising message during muxing
- Switched from MoviePy-heavy output flow to direct FFmpeg-based cutting and assembly for faster rendering and better multi-audio support

### v1.0

- Initial release
- Auto clip cutting and merging from event CSV
- Combined reel and individual clips modes
- Dry run preview
- Browser UI with file browse buttons

---

*ClipMaker by B4L1 — [@B03GHB4L1](https://x.com/B03GHB4L1)*
