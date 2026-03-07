# ⚽ ClipMaker
**Automatic football highlight reel generator from match event data**

Built by [@B03GHB4L1](https://x.com/B03GHB4L1)

---

## What it does

ClipMaker takes a match event CSV and a video file, and automatically cuts and assembles a highlight reel — no manual editing required. Point it at your data, set your kick-off timestamps, and it renders the clips.

---

## Features

- **Auto clip generation** from any match event CSV with minute/second columns
- **Action type filter** — select which event types to include (Pass, Carry, Shot, etc.)
- **Progressive actions filter** — clip only actions where `prog_pass` or `prog_carry` > 0
- **xT filter** — set a minimum expected threat threshold to exclude low-danger actions
- **Top N by xT** — rank all actions by xT and clip only the most dangerous N moments
- **Split video support** — works with a single match file or separate 1st/2nd half files
- **Individual clips or combined reel** — save each action as its own file or one assembled video
- **Dry run mode** — preview the clip list before committing to a full render
- **Live progress bar** — frame-level progress and estimated time remaining during rendering
- **Browser-based UI** — no command line needed, runs locally in your browser

---

## Download

Go to the [Releases](../../releases) page and download the zip for your platform:

- **ClipMaker_1.1_Windows.zip**
- **ClipMaker_1.1_Mac.zip**

Each zip includes the app, launcher, and setup guide.

---

## Requirements

- Python 3.8 or later — [python.org/downloads](https://www.python.org/downloads)
- The launcher installs all other dependencies automatically on first run

---

## How it works

1. Load your match video and event CSV into the app
2. Enter the kick-off timestamp for each half as shown in your video player
3. Apply any filters (action type, progressive, xT, Top N)
4. Choose individual clips or a combined reel
5. Click **Run ClipMaker**

The app maps each event's match clock time to the video timeline, cuts a clip around it (with configurable before/after buffers), merges events that happen close together, and either saves them individually or assembles them into one reel.

---

## CSV Format

Your CSV needs at minimum:

| Column | Description |
|--------|-------------|
| `minute` | Match clock minute |
| `second` | Match clock second |
| `type` | Action type (e.g. Pass, Carry, Shot) |
| `period` | Half identifier (FirstHalf / SecondHalf or 1 / 2) |

Optional columns that unlock additional filters:

| Column | Filter unlocked |
|--------|----------------|
| `xT` | Min xT filter, Top N by xT |
| `prog_pass` | Progressive actions filter |
| `prog_carry` | Progressive actions filter |

---

## Changelog

### v1.1
- Action type, progressive, xT, and Top N filters
- Split video file support (separate 1st/2nd half files)
- Live assembly progress bar with frame count and ETA
- Finalising message when muxing audio and video

### v1.0
- Initial release
- Auto clip cutting and merging from event CSV
- Combined reel and individual clips modes
- Dry run preview
- Browser UI with file browse buttons

---

*ClipMaker by B4L1 — [@B03GHB4L1](https://x.com/B03GHB4L1)*
