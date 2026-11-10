# Analysis Workspace Migration Plan: Streamlit to Shared HTML/JS

Status: Phases 0-2 complete and green on Windows, Linux and macOS CI
(9-10 November 2026; Phase 2 passed its decision gate). Phase 3 (all Analyst Room tabs
native, now the default) complete locally on 10 November 2026; CI pending.

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

#### Phase 1 results (9 November 2026)

Built:
- `app/analysis_core/`: Streamlit-free package. `frames.py` holds the Analyst
  Room data loading, moved unchanged (the page now imports it; the golden
  snapshot still matches). `FrameCache` keys on CSV path, size and mtime, so
  saving UI state never reloads data but re-importing a CSV does.
  `registry.py` lists views and tabs with a `native` flag per tab.
- API (`packaging/clipmaker_api_server.py`):
  - `GET /api/analysis/config`: views, tabs and mode per view.
  - `GET /api/analysis/summary?project=`: teams, counts, periods, saved state.
  - `POST /api/analysis/<view>/<tab>`: validates names and project; returns
    501 with `classic: true` until a tab's native handler exists.
  - `/analysis-component/*`: serves only the map component's folder.
  - Projects store `analysis_state` (tab and controls per view), validated
    and capped at 20 KB.
- Feature flag `VIZORPLAY_ANALYSIS_UI` (`native`, or `analyst=native,
  tactical=classic`); default classic. `?ui=native|classic` overrides per page.
- `ui/analysis/component-host.js`: hosts the unchanged map component in an
  iframe and speaks its three-message protocol, accepting messages only from
  its own frame.
- `ui/analysis/native.js` + `native.css`: tab bar with arrow/Home/End keys,
  loading, error (with retry) and empty states, match summary, URL `?tab=`
  and per-project saved tab. Unmigrated tabs link to the classic workspace,
  which now opens on the same tab (`?tab=` honoured once per session).

Tests: `tests/test_analysis_core.py` (12: no Streamlit import, frames,
cache reuse/invalidation/eviction, registry, saved-state validation, mode
parsing, API config/summary/validation, component path containment, state
round trip, classic deep link) and a native stage in `tests/browser_smoke.py`
(tabs, keyboard, URL, saved state across reload, classic fallback on the same
tab, a recorded Shot Map rendered through the host with a real click returning
the selected shot, PNG export from the hosted map, 390 px layout with the active tab visible, error state, no
console errors).

Fixed while building: tab saves were debounced, so leaving within 300 ms lost
the choice outside the unload guard; saves are now immediate and queued.

The browser stage also downloads and validates a PNG export from the hosted
map. Not in Phase 1: collapsible control sections arrive with the first tab
that has controls (Phase 2).

### Phase 2: Pilot tab (Shot Map)

Chosen because it already has browser click/export acceptance tests.
- Shot Map (Normal + Penalty Shootout), team/player/zone filters, selection,
  watch panel with before/after sliders, clip preview, download, retry, clear.
- Measure against phase 0. **Decision gate:** if the native tab is not clearly
  faster, stop and reassess before migrating the rest.

#### Phase 2 results (10 November 2026)

Built:
- `analysis_core/common.py` (shared helpers), `shot_map.py` (shot payloads,
  labels, stats, qualifiers, filters, map arguments, full native view) and
  `video.py` (`clip_window`, the classic clip timing). The classic page now
  imports all three; the golden snapshot is unchanged.
- `POST /api/analysis/analyst/shot-map` returns the whole tab state for the
  given controls, validated server-side; `.../shot-map/clip` cuts the selected
  shot's clip with the classic timing and encoder settings (libx264
  ultrafast, default CRF), buffers 0-60 s, into `analysis-clips/` (newest 20
  kept).
- `ui/analysis/tabs/shot-map.js`: collapsible filters, mode/team/player/zone,
  stats bar, goal frame and pitch maps through the component host, click or
  list selection, clear, detail panel, Watch with before/after sliders
  (defaults from the project's filter buffers), re-cut on slider change,
  download, clear preview, error with retry. Controls save per project.

Verified locally:
- `tests/test_shot_map_native.py`: every recorded Shot Map scenario (normal
  and penalty modes) matches the classic page on map and goal-frame
  arguments, shot list, team/player options, stats numbers and selected-shot
  details. A deliberate one-line change makes 9 scenarios fail.
- API tests: view, validation order (bad buffers before missing video), no
  selection, unknown routes, and a real ffmpeg clip of exactly
  before + after seconds.
- Browser: real Rennes vs PSG match with a 125-minute test video: correct
  teams, a 13 s clip at default buffers whose burned-in clock starts 5 s
  before the 2'41" shot, re-cut to 18 s after moving a slider, player filter,
  penalty mode on the fixture, 390 px without overflow, no console errors.
  CI browser stage: real click on the plotted goal, details, clip at the
  project's saved 1 s/1 s buffers, PNG export, clear.

Decision gate, real match (Rennes vs PSG, 2,206 events), 3 rounds, same
session. Classic times stop when Streamlit finishes its script; native times
also wait for the map to redraw, so the comparison favours classic.

| Step | Classic median (max) | Native median (max) |
|---|---|---|
| Open workspace on Shot Map | 3.34 s (8.46 s) | 0.18 s (0.53 s, cold load) |
| Change team | 0.27 s / 0.23 s back (1.58 s) | 0.10 s / 0.09 s back (0.12 s) |
| Select a shot | not timed | 0.17 s (0.19 s) |
| Clear selection | not timed | 0.10 s (0.12 s) |

Result: clearly faster (about 18x to open, 2.5x per control) and within the
Phase 2 targets (open under 1 s, control under 300 ms). Proceed to Phase 3.

Default stays classic: with only one native tab, native mode would send
users to the classic workspace for the other seven Analyst tabs. Switch the
Analyst Room default once Phase 3 completes.

Found, not fixed (pre-existing):
- The penalty shootout component's header overlaps its export buttons at
  390 px in both workspaces.
- Filter-page preview renders in `previews/` are never deleted.

### Phase 3: Remaining Analyst Room tabs

Pass, Defensive Actions, Dribbles & Carries, Goalkeeper, Build-Up, Pressing,
Comparison (see checklist).

#### Phase 3 progress (10 November 2026)

Approach change: from Phase 3 on, native views are faithful ports in
`analysis_core` and the classic page code is left as it is, instead of
refactoring every classic tab to import them. The duplication ends in Phase 5
when the classic pages are deleted; until then each tab's parity test proves
the port shows what the classic tab shows.

Done (locally verified, CI pending):
- Shared view format (`analysis_core/views.py`) and one renderer
  (`ui/analysis/tabs/event-tab.js`) for map-style tabs: filters, stats,
  detail ("aux") and clickable ("map") components in separate stable
  containers so iframes never reload on reorder, picker, details with badges
  and fields, Watch panel. Clips resolve the selected event through the view
  builder, so only selectable events can be cut. The Shot Map moved onto it.
- Pass Map (team/player views, pass network, pass types, zones),
  Defensive Actions, Dribbles & Carries, Goalkeeper (actions, shots faced,
  distribution) in `analysis_core/event_maps.py`; Pressing in
  `analysis_core/pressing.py`.
- `tests/test_analyst_native.py` checks every recorded scenario of all six
  tabs: component arguments, picker lists, filter options, stats labels and
  values (metric cards for Pressing), prompts, empty messages and selected
  details including all badges. Deliberate one-line changes in notes, labels,
  stats labels, starter flags and distribution thresholds are each caught.
- Fixture enriched: goalkeeper distribution (goal kicks, throws), second-half
  substitutions, last-line defensive actions, chronological order. Before
  this, Distribution only ever showed its empty message in the snapshot.
- Real match (Rennes vs PSG) browser check: every tab's prompts, stats,
  selection, details and 13 s clips at default buffers; all goalkeeper
  modes; 390 px without overflow; no console errors.

Bug fixed in both workspaces: the classic Pressing caption said "Click a
press win marker", but markers carried no event id and the chart renderer
had no click handler, so clicks did nothing and the win detail and clip were
unreachable. The pressing option builder moved to `analysis_core.pressing`
(the classic wrapper now calls it) with ids on markers, the renderer reports
marker clicks, and the classic tab reads them. Native Pressing adds a
press-win list and the Watch panel. Note for tests: ECharts ignores clicks
during its 450 ms entry animation.

Build-Up and Comparison (done, locally verified, CI pending):
- `analysis_core/build_up.py`: entry modes list entries like the map tabs;
  chain modes list sequences, draw the selected one and clip it from first
  to last action with the classic timing (both ends on the start period's
  clock). Real match: a 2 s sequence gives a 15 s clip at 5 s / 8 s buffers.
- `analysis_core/comparison_helpers.py` holds the classic Comparison helpers
  copied verbatim by script; `comparison.py` builds radar and zone figures
  (Plotly JSON), Top 5 tables and the role-mismatch warning. Reels cut each
  moment and join them losslessly as the classic reel did; real match: five
  moments give a 65 s reel. `ui/analysis/tabs/comparison.js` draws figures
  with the Plotly build already shipped in the map component folder, loaded
  only when the tab opens.
- Parity: Build-Up compares entry pickers, sequence lists (against the
  classic buttons), metrics and sequence titles; Comparison compares all
  three figures (data and layout; templates differ by design because
  Streamlit sends a placeholder its browser code replaces), both Top 5
  tables, the warning, role selectors and captions.
- Recorder fixes: clicks are now part of a scenario's identity (a sequence
  click changes no control, so it was being dropped), and keeper-vs-outfield
  and keeper-vs-keeper comparisons are recorded.

With all eight tabs native, the Analyst Room now defaults to the native
workspace; `?ui=classic` and a "Classic workspace" link keep the classic
page reachable until Phase 5. The Tactical Lab stays classic (Phase 4).

Timing, real match (Rennes vs PSG), 3 rounds, same session, medians (max).
Classic stops when Streamlit finishes its script; native waits until maps
and charts have drawn, so the comparison favours classic.

| Step | Classic | Native |
|---|---|---|
| Open the Analyst Room | 3.31 s (8.15) | 0.13 s (0.54) |
| Pass Map | 0.56 s | 0.32 s |
| Defensive Actions | 0.24 s | 0.08 s |
| Dribbles & Carries | 0.34 s | 0.07 s |
| Goalkeeper | 0.22 s | 0.07 s |
| Build-Up | 0.46 s (0.95) | 0.20 s |
| Pressing | 0.43 s | 0.26 s |
| Comparison | 1.21 s (2.66) | 0.55 s (1.26, first load fetches Plotly) |
| Shot Map | 0.40 s | 0.13 s |
| Change Shot Map team | 0.29 s (1.57) | 0.10 s |

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
| Shot Map | Normal and Penalty Shootout modes; team radio, player, pitch zone; click to select; shot list; reclassified shots; stats panel | native (golden parity, browser click/clip/export; CI pending) |
| Pass Map | Team view and player view; pass network; pass type filter; pitch and depth zones; select pass; stats | native (golden parity, real-match browser check; CI pending) |
| Defensive Actions | Team, player, pitch and depth zones; select action; stats | native (golden parity, real-match browser check; CI pending) |
| Dribbles & Carries | Team, player, pitch and depth zones; select action | native (golden parity, real-match browser check; CI pending) |
| Goalkeeper | Actions, shots faced, distribution modes; zones; select item; empty long-pass case | native (golden parity, real-match browser check; CI pending) |
| Build-Up | Entry modes (possession, final third, box entries) and sequences; min actions slider; sequence list, detail, watch; selection survives reruns | native (golden parity, real-match browser check; CI pending) |
| Pressing | Team and zone; metrics row; detail; clear | native (golden parity, real-match browser check; CI pending) |
| Comparison | Two players across teams; percentile radar; pitch zone heatmaps; role-based Top 5 moments with GK scoring; moments reel | native (golden parity, real-match browser check; CI pending) |

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
