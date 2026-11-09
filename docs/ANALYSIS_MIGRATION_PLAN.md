# Analysis Workspace Migration Plan: Streamlit to Shared HTML/JS

Status: Phase 0 complete locally (Windows) on 9 November 2026; CI on Linux
and macOS pending. Phase 1 not started.

## Goal

Make the Analyst Room and Tactical Lab fast and glitch-free by running them in
the shared `ui/` frontend instead of a second Streamlit process, with no loss
of analytical behaviour. This is stage 1 of the staged route toward a smaller
Rust-hosted backend; it is required whether or not that later port happens.

Non-goals for this stage: changing analytical algorithms, restyling beyond the
shared design, slimming dependencies (Chromium, pandas), or the Rust port.

## Why

Measured on 9 November 2026 (Windows, source run):

| Step | Time |
|---|---|
| Main backend cold start to `/api/health` | 0.5-0.6 s (frozen exe also ~0.5 s) |
| Streamlit analysis server cold start to `/_stcore/health` | 1.7-3.3 s, before any page renders |
| Each control change in Streamlit | Re-runs a 3,612-line (Analyst) or 1,767-line (Tactical) page script; not yet timed |

The lag comes from the second process and Streamlit's rerun model, not from
the analytical code itself.

## Current architecture

```
ui/analysis.html  --iframe-->  Streamlit subprocess (analysis_server.py)
                                 app/analysis_entry.py
                                 app/pages/2_The_Analysts_Room.py  (8 tabs)
                                 app/pages/3_Tactical_Lab.py       (5 tabs)
                                 app/project_analysis.py           (project -> session_state)
                                 app/smp_component/frontend/index.html  (JS maps, Plotly, ECharts, GIF export)
```

## Target architecture

```
ui/analysis.html + ui/analysis/*.js   (tabs, controls, selection, URL state)
   |  fetch JSON
   v
clipmaker_api_server.py  /api/analysis/<view>/<tab>  (existing server, no subprocess)
   |
app/analysis_core/  pure functions, no `streamlit` import
   - per-project DataFrame cache keyed by (project id, revision)
   - returns map payloads and Plotly figure JSON
ui/vendor/smp/  existing map renderers, with a small shim replacing
                Streamlit.setValue / setHeight with callbacks
Clip cutting and reels go through the existing /api/jobs queue (progress + cancel).
```

Design rules:

1. **Move, don't rewrite, the algorithms.** Lift each computation (for example
   `_score_moments`, `detect_defensive_transitions`, `compute_style_metrics`,
   `build_up_entry_events`) out of the page into `app/analysis_core/`
   unchanged, then delete the page copy. Existing unit tests keep passing
   against the moved functions.
2. **Reuse the JS map component.** `smp_component/frontend/index.html` already
   draws every map and handles PNG/GIF export. Only its Streamlit messaging
   (`setComponentValue`, `setHeight`) is replaced by a shim.
3. **Keep Plotly figures identical.** Python builds the same figure and sends
   `fig.to_json()`; the browser draws it with the bundled Plotly.js.
4. **Fast round trips.** The project CSV is loaded once per revision and
   cached; a control change should be a single small JSON request.
5. **Project-scoped state.** Selected tab, team, player, zones, sliders and
   selection are saved with the project and restored on reopen, using the
   existing atomic project store.
6. **Feature flag during migration.** `VIZORPLAY_ANALYSIS_UI=streamlit|native`
   per view, so unfinished tabs keep working on Streamlit. Streamlit is
   removed only in phase 5.
7. **Validated API.** Each endpoint validates view, tab, team and player
   against the loaded project; there is no path or filesystem input from the
   browser.

## Phases

Each phase ends with tests on Windows, Linux and macOS in GitHub Actions and
a commit. A phase is not done while any of its checklist rows are unverified.

### Phase 0: Baseline (before changing code)

- Playwright timing script on the fixture project: open Analyst, open
  Tactical, switch every tab, change one control per tab. Record numbers here.
- **Golden snapshots:** for every tab and mode, record the data the current
  page computes (map payloads, metric values, table rows, figure data) from
  the fixture CSV(s) into `tests/golden/analysis/`. These become the parity
  oracle for later phases.
- Confirm `app/ClipMaker.py`, `pages/1_Filtering_Output.py` and the
  `clipmaker_server.py` Streamlit launcher are no longer reachable from the
  shipped app (they appear only in `theme.py` navigation). Record the result;
  remove them in phase 5 if unused.

#### Phase 0 results (9 November 2026, Windows 11, source backend, headless Chromium)

Tools:
- `tests/analysis_fixture.py`: deterministic synthetic match (regular time,
  extra time, penalty shootout) mirroring the scraped schema. Real scraped
  files stay out of git.
- `tests/analysis_golden.py`: records every tab, mode, nested selection,
  slider edge and multi-match view (150 scenarios) into
  `tests/golden/analysis/fixture.json.gz`; `--csv` captures local real
  matches to an uncommitted file. Checked deterministic over two runs.
- `tests/test_analysis_golden.py`: fails if anything a user sees changes.
- `tests/analysis_timing.py`: browser timing and bytes streamed per step.

Timings: median wall time until Streamlit finishes the rerun. Map drawing
inside the component iframe can add a little more; it is not included.

| Step | Synthetic fixture (3 rounds) | Rennes vs Paris SG, 2,206 events (2 rounds) |
|---|---|---|
| Open Analyst Room (includes starting Streamlit) | 3.4 s (max 7.6), 4.1 MB | 6.6 s (max 8.8), 4.1 MB |
| Open Tactical Lab | 3.3 s, 4.1 MB | 2.3 s, 4.1 MB |
| Analyst tab switch | 0.23-0.71 s | 0.29-1.49 s (Comparison slowest) |
| Shot Map team change | 0.24-0.29 s | 0.31-0.98 s |
| Tactical tab switch | 0.97-1.52 s | 1.09-2.57 s (Style Profile, Video Lab slowest) |

About 4 MB per workspace open is inline font CSS (one 3.6 MB Iosevka
stylesheet plus two 234 KB Geist blocks). Reruns stream only 0.01-0.3 MB, so
rerun cost is server-side script time, not transfer.

Proposed Phase 2 targets: workspace open under 1 s once the backend is up,
tab switch and control change under 300 ms, on the same real match.

Bugs found and fixed during Phase 0 (each with a regression test):
- Goalkeeper > Distribution crashed with `KeyError ['x', 'endX']` when the
  selected keeper had no passes (`test_goalkeeper_distribution_without_passes_shows_empty_state`).
- Scoresway matches (2 of 2 local; 0 of 36 WhoScored): short fixture labels
  ("Rennes", "Paris SG") did not match full event names, so the Analyst Room
  swapped home and away and the Tactical Lab listed label-only teams with no
  events, defaulting to an empty "Rennes". Shared matcher `app/team_names.py`
  (`tests/test_team_names.py`).
- `preserve_analysis_controls` re-assigns widget state each rerun, which made
  Streamlit show a one-off yellow "created with a default value but also had
  its value set via the Session State API" warning (reproduced in AppTest on
  the penalty picker; not yet observed in a browser). Disabled for the
  analysis entry
  (`test_preserved_controls_do_not_show_streamlit_duplication_warning`).

Findings left for later phases:
- Multi-match lists follow project folder (random id) order, so match order
  and the default team can differ between sessions.
- `test_projects.test_cross_origin_request_is_rejected` failed once in a full
  local run with `WinError 10053` (server closed the connection before the
  client read the 4xx) and passed alone. Cause: POST errors were answered
  without reading the request body. Fixed by draining small rejected bodies
  (`test_rejected_request_with_unread_body_still_gets_error_reply`).
- In AppTest a stale Video Lab moment selection breaks `format_func`; the
  browser sends an index instead, so this is not confirmed as a user bug.
- `app/ClipMaker.py`, `app/pages/1_Filtering_Output.py` and
  `packaging/clipmaker_server.py` are unreachable from the desktop app and the
  Homebrew bootstrap (both start `clipmaker_api_server.py`) but are still
  bundled. Remove in Phase 5.

### Phase 1: Foundation

- `app/analysis_core/` package plus a project DataFrame cache.
- `/api/analysis/<view>/<tab>` endpoint with input validation and error JSON.
- JS shim so the map component runs inside `ui/` without Streamlit.
- Native `analysis.html` shell: tab bar, collapsible control sections,
  loading/error/empty states, footer version, URL and project state.
- Feature flag; Streamlit path still default.
- Test: shim click-to-select and export in a browser; endpoint validation.

### Phase 2: Pilot tab (Shot Map)

Chosen because it already has browser click/export acceptance tests.
- Shot Map (Normal + Penalty Shootout), team/player/zone filters, selection,
  watch panel with before/after sliders, clip preview, download, retry, clear.
- Measure against phase 0. **Decision gate:** if the native tab is not clearly
  faster, stop and reassess before migrating the rest.

### Phase 3: Remaining Analyst Room tabs

Pass, Defensive Actions, Dribbles & Carries, Goalkeeper, Build-Up, Pressing,
Comparison (see checklist).

### Phase 4: Tactical Lab

Team selector, multi-match mode, then the five tabs (see checklist).

### Phase 5: Remove Streamlit

- Delete `analysis_server.py` subprocess launch, `analysis_entry.py`,
  `project_analysis.py` Streamlit parts, the old pages and unused launchers.
- Remove `streamlit` from `requirements.txt` and `collect_all` in the
  PyInstaller spec; confirm a frozen build still starts and passes acceptance.
- Update `FEATURE_PARITY.md`, `RELEASE_1_0_CHECKLIST.md`, browser smoke tests.

## Parity checklist

Source of truth for behaviour: `older versions/` and the current Streamlit
pages. Status values: `todo`, `golden` (snapshot captured; video cutting, export
and browser-only behaviour still need browser tests), `native` (built),
`verified` (golden match + browser test on all three OSes).

### Shared

| Item | Status |
|---|---|
| Match source picker (Analyst) and saved-project match list | todo |
| Team name resolution and match export context in titles/filenames | golden (titles, notes, team options) |
| Light/dark pitch theme | todo |
| Chart PNG export and multi-frame GIF export with branded header | todo |
| Watch panel: before/after sliders, cut clip, preview, download, retry, clear | todo |
| Period kickoff alignment and timeline corrections used for every clip | todo |
| Selection survives control changes and tab switches | todo |
| Control state saved per project and restored on reopen | todo |
| Missing video / marker produces actionable error, not a crash | todo |
| Empty data states for every tab and mode | golden (fixture cases only) |
| Narrow layout: no overflow or hidden controls | todo |
| No console errors | todo |

### Analyst Room

| Tab | Behaviour to preserve | Status |
|---|---|---|
| Shot Map | Normal and Penalty Shootout modes; team radio, player, pitch zone; click to select; shot list; reclassified shots; stats panel | golden (data views) |
| Pass Map | Team view and player view; pass network; pass type filter; pitch and depth zones; select pass; stats | golden (data views) |
| Defensive Actions | Team, player, pitch and depth zones; select action; stats | golden (data views) |
| Dribbles & Carries | Team, player, pitch and depth zones; select action | golden (data views) |
| Goalkeeper | Actions, shots faced, distribution modes; zones; select item; empty long-pass case | golden (data views) |
| Build-Up | Entry modes (possession, final third, box entries) and sequences; min actions slider; sequence list, detail, watch; selection survives reruns | golden (data views) |
| Pressing | Team and zone; metrics row; detail; clear | golden (data views) |
| Comparison | Two players across teams; percentile radar; pitch zone heatmaps; role-based Top 5 moments with GK scoring; moments reel | golden (data views) |

### Tactical Lab

| Tab | Behaviour to preserve | Status |
|---|---|---|
| Match scope | Single match, multi-match toggle and multiselect, unique event IDs, saved labels, later opponents in team list | golden (data views) |
| Defensive Transitions | Reaction window and event cap sliders; period isolation; chart | golden (data views) |
| Attacking Transitions | Attack window and event cap; includes win, caps all events; chart | golden (data views) |
| Style Profile | Radar with info, pooled weighted metrics, strengths/weaknesses, zone heatmaps, per-match trends with dimension picker | golden (data views) |
| Set Pieces | Restart classification, retained/box entry/shot/xT, charts and 16-row table | golden (data views) |
| Video Lab | Playlists, before/after/reel-count sliders, moment list, sequence trace, cut moment, build and download reel, correct source time and order across projects | golden (data views) |

## Tests to add

- Golden parity test per tab and mode (phase 0 snapshots vs `analysis_core`).
- API validation tests: unknown view/tab/team/player, missing CSV, stale revision.
- Browser tests per tab: render, select, export, clip, empty state, narrow width.
- Performance test with a budget (proposed: tab switch under 300 ms and
  control change under 150 ms on the fixture project, measured in CI and
  reported, failing only on large regressions).
- Existing `test_analysis.py` and `test_tactical_acceptance.py` keep passing,
  retargeted from Streamlit pages to `analysis_core`.

## Risks

- **Hidden Streamlit behaviour.** Implicit reruns, `st.fragment`, widget keys
  and `preserve_analysis_controls` hold state rules that are easy to miss.
  Mitigation: golden snapshots plus explicit state tests.
- **Size of the work.** About 5,400 lines of page code. The phase 2 decision
  gate limits the cost if the approach disappoints.
- **Two UIs during migration.** The feature flag keeps both working; phase 5
  must not start until every row is `verified`.
- **Export differences.** GIF/PNG rely on the component's worker paths, which
  change when served from `ui/`. Covered by the export browser test.
