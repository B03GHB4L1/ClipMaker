<p align="center">
  <img src="./ui/assets/vizorplay-football.png" alt="VizorPlay" width="140">
</p>

<div align="center">
  <h1>VizorPlay</h1>

  **Football video clipping and analysis workstation built from match event data**

Built by [@B03GHB4L1](https://x.com/B03GHB4L1) · Version 1.0
</div>

---

## What it does

VizorPlay turns match event data and match video into clips and analysis, all
on your own computer.

- Scrape a match from Scoresway or WhoScored, or import your own event CSV
- Attach the match video: one file, or separate halves, extra-time halves and
  penalties
- Filter the events you want (players, actions, zones, xT, progressive actions
  and many football tags) and preview every clip before exporting
- Export individual clips or one combined reel
- Explore the match in the Analyst Room and a team's style in the Tactical Lab

Every project is saved locally with its match data, video links, kick-off
times, filters and export settings. Starting a new project never overwrites
another one.

VizorPlay was previously called ClipMaker.

---

## Install

Installers are attached to each release on the [Releases](../../releases) page.
Version 1.0 is being prepared and is not published yet.

| System | How |
|---|---|
| Windows 10 and 11 | Run `VizorPlay_1.0.0_x64-setup.exe`. It installs for your user only. The installer is not code-signed, so Windows may say "Windows protected your PC": choose **More info**, then **Run anyway**. |
| Ubuntu, Debian, Linux Mint | `sudo apt install ./VizorPlay_1.0.0_amd64.deb`, then start **VizorPlay** from the app menu or run `vizorplay`. |
| macOS | Through Homebrew once the tap is published: `brew tap B03GHB4L1/clipmaker`, `brew install vizorplay`, then run `vizorplay`. It opens in your default browser. There is no Apple-signed app, so no promise that every macOS security prompt is avoided. |

Installing a newer version over an older one upgrades it and keeps your
projects. Uninstalling also keeps your projects. See
[docs/INSTALLATION.md](docs/INSTALLATION.md) for details, including where
projects are stored.

You do not need Python, FFmpeg or Node.js. For Scoresway pages that hide their
data links, VizorPlay uses the Microsoft Edge or Google Chrome already on your
computer.

---

## Features

### Match data

- **Scoresway and WhoScored scraping**, single matches or several at once
- **CSV import** for your own event data
- **Kick-off times** for each half, both extra-time halves and penalties, so
  event times line up with your video
- **Penalty shootouts** aligned from the timestamp of the first kick

### Filtering and clips

- Filters for players, teams, action types, halves, pitch and depth zones, xT
  thresholds, Top N by xT, progressive actions, and boolean tags such as key
  passes, crosses, switches, through balls, box entries, final-third entries,
  big chances and touches in the box
- Quick presets and saved filter snapshots
- Clip windows with adjustable before/after time, with nearby events merged
  into one clip
- **Preview and trim** any clip before exporting
- **Individual clips or a combined reel**, with progress, cancel, and a clear
  report if any clip fails

### Export speed

On a computer with an NVIDIA graphics card, VizorPlay encodes on the graphics
card: a 20-clip reel took 52 s instead of 347 s on the test laptop, at equal or
better quality. Other computers use x264 software encoding. An "Encoder"
setting lets you force software encoding. Details:
[docs/EXPORT_SPEED_PLAN.md](docs/EXPORT_SPEED_PLAN.md).

### Analyst Room

Shot map (with goalframe and penalty-shootout views), pass map and pass
network, defensive actions, pressing, dribbles and carries, goalkeeper actions
and shots faced, build-up chains with clip extraction, and player comparison
radars. Maps export as PNG or animated GIF with match and filter context.

### Tactical Lab

Team style across up to 20 saved matches: style radar, threat split, progression
funnel, territory heatmap, defensive and attacking transitions, set-piece and
restart profile, and a video lab for cutting tactical moments into reels.

---

## Event CSV format

Required columns:

| Column | Description |
|--------|-------------|
| `minute` | Match clock minute |
| `second` | Match clock second |
| `type` | Event type, e.g. `Pass`, `Carry`, `Shot` |

`period` (e.g. `FirstHalf` / `SecondHalf` or `1` / `2`) is strongly
recommended. Optional columns unlock more: `xT`, `prog_pass`, `prog_carry`,
`team`, `playerName`, `goal_mouth_y`, `goal_mouth_z` and computed `is_*` flags.

Scoresway and WhoScored do not expose identical tags and qualifiers, so some
analysis can differ slightly between the two sources.

---

## Developing

The app is one shared HTML/JS frontend (`ui/`), a local Python engine
(`packaging/clipmaker_api_server.py`, `app/`) and a small Tauri desktop shell
(`src-tauri/`), built for Windows, Linux and macOS from the same code. See
[Contributing.md](Contributing.md) for running from source and the tests, and
[docs/RELEASES.md](docs/RELEASES.md) for how installers are built and tested.

---

## Version history

### VizorPlay 1.0 (in preparation)

- Rebuilt as a desktop app: one shared interface for Windows, Linux and macOS,
  with Windows and Linux installers that upgrade in place and keep projects
- Much smaller installers (Windows about 67 MB), with no bundled browser
- Graphics-card encoding for much faster previews and exports
- Projects saved locally and reopened exactly as left
- AI-assisted filtering from earlier versions is not included

### Earlier versions (as ClipMaker)

- **1.2.3**: Scoresway scraping, PNG/GIF map exports, extra-time and shootout
  handling, an expanded Tactical Lab
- **1.2.2**: Tactical Lab, multi-player reels, multi-match scraping
- **1.2.1**: pressing map, clip trimming from preview, faster previews
- **1.2**: WhoScored scraping, the Analyst Room, presets and filter snapshots
- **1.1**: xT, progressive and Top N filters, split video files, FFmpeg cutting
- **1.0**: first release, clips and reels from an event CSV

The original applications are kept in `older versions/` as the feature
baseline.

---

*VizorPlay by B4L1 · [@B03GHB4L1](https://x.com/B03GHB4L1)*
