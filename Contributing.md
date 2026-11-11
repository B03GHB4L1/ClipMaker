# Contributing to VizorPlay

Thanks for helping. This guide describes the app as it is now: one shared
HTML/JS frontend, one local Python engine, and a small Tauri desktop shell,
built for Windows, Linux and macOS from the same code. The original
Streamlit apps are kept in `older versions/` only as the feature baseline.

Read `AGENTS.md` first: it holds the working agreement (scope, UX rules,
engineering rules, verification).

---

## Project structure

| Path | Purpose |
|------|---------|
| `ui/` | The shared frontend: Intake (`index.html`, `app.js`), Filters and export (`filters.*`), the analysis shell (`analysis.*`) and its tabs (`ui/analysis/`). Plain ES modules, no build step. Third-party libraries are vendored under `ui/vendor/`. |
| `packaging/clipmaker_api_server.py` | The local engine: a validated HTTP API on `127.0.0.1` serving `ui/`, projects, scraping, filtering, previews, export jobs and analysis views. |
| `packaging/process_owner.py` | Stops the engine when the desktop window that owns it exits. |
| `app/clipmaker_core.py` | Filtering, clip windows, timing alignment and the export pipeline. |
| `app/video_encoder.py` | Chooses the H.264 encoder: NVIDIA NVENC when it works, x264 otherwise (`docs/EXPORT_SPEED_PLAN.md`). |
| `app/scoresway_scraper.py`, `app/whoscored_scraper.py` | Match data scraping and event normalisation. |
| `app/browser_capture.py` | Scoresway fallback that drives the installed Edge/Chrome over CDP (`docs/SCRAPER_BROWSER_PLAN.md`). |
| `app/analysis_core/` | Analyst Room and Tactical Lab views. Never imports Streamlit. |
| `app/smp_component/frontend/` | The interactive map component (ECharts, Plotly, PNG/GIF export) hosted by the analysis tabs. |
| `app/config/` | Football glossary, inference flags, Opta event reference, xT grid. |
| `src-tauri/` | Desktop shell (Rust/Tauri): starts the engine, shows the UI, stops the engine on exit. |
| `packaging/pyinstaller/` | Freezes the engine for the desktop installers. |
| `packaging/homebrew/`, `packaging/winget/` | Distribution manifests (prepared, not published). |
| `tests/` | Unit, API, media, parity and browser tests (see below). |
| `docs/` | Plans, results, installation, release checklist and testing notes. |

---

## Running from source

Python 3.12 or newer and Node.js 22 are expected.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use .venv/bin/activate on Linux and macOS
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium   # browser for the tests only; the app does not bundle one
```

Start the engine and open the printed address in a browser:

```bash
python packaging/clipmaker_api_server.py --port 8502 --data-dir build/dev-data
```

Projects, imports, previews and exports for that run live under the data
directory. The desktop shell needs a frozen engine; see `docs/RELEASES.md`
and the `Full Desktop E2E` workflow for the exact build steps.

---

## Tests

| Command | What it covers |
|---------|----------------|
| `python -m unittest discover -s tests` | Unit, API, project store, media cutting, parity against the recorded classic analysis, browser-fallback capture (uses your installed Edge/Chrome) |
| `node --test tests/projects.test.mjs` | Frontend autosave |
| `python packaging/smoke_test.py [--server <frozen engine>]` | Real previews, exports, cancellation and shutdown through the API |
| `python tests/browser_smoke.py [--server <frozen engine>]` | Full browser journey, including chart PNG/GIF export and narrow layouts |
| `python tests/workflow_timing.py --video <match> --scoresway-url <url>` | Startup, scrape, filter, preview and export timings |
| `python tests/analysis_timing.py` | Analysis tab timings |

GitHub Actions runs the checks on Windows, Linux and macOS, builds the
installers, and launch-tests them (`.github/workflows/`). Say which layer you
ran: unit tests, build checks and installed-app launch tests are different
evidence.

---

## Rules that are easy to break

- **No arbitrary filesystem access through the API.** File paths sent by the
  browser are validated (`clean_client_project`); event data only comes from
  scraping or importing.
- **Atomic writes** for anything saved (`atomic_json`).
- **Never fail silently.** Missing dependencies, hardware fallbacks and
  partial exports are reported in the UI or job log.
- **Keep OS integrations behind adapters** (file dialogs, browser lookup,
  process ownership, encoders).
- **Analysis parity:** analysis changes must keep `tests/test_analyst_native.py`
  and `tests/test_tactical_native.py` passing; they compare against what the
  original pages showed.
- **AI filtering stays excluded** unless the owner decides otherwise.
- **No Gatekeeper promises:** there is no Apple Developer membership; macOS
  installs through the Homebrew source launcher.

---

## Data expectations

Event CSVs need at least:

| Column | Description |
|--------|-------------|
| `minute` | Match clock minute |
| `second` | Match clock second |
| `type` | Event type |

`period` is strongly recommended. Useful optional fields include `xT`,
`prog_pass`, `prog_carry`, `team`, `playerName`, `goal_mouth_y`,
`goal_mouth_z`, `homeTeam`, `awayTeam`, `matchName`, `matchDate` and the
computed `is_*` flags. Test filter changes against real match data, not only
toy rows. WhoScored and Scoresway do not expose identical tags or qualifiers.

---

## Pull requests

1. Create a descriptive branch.
2. Make the change and add a focused regression test for it.
3. Run the relevant tests above; check desktop and narrow layouts for
   overflow, hidden controls, dead actions and console errors when UI changes.
4. Open a pull request saying what changed, why, what you tested (which
   layers, which OS), and anything you could not verify.

---

*VizorPlay by B4L1 - [@B03GHB4L1](https://x.com/B03GHB4L1)*
