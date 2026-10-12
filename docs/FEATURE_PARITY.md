# ClipMaker Desktop Feature And Verification Ledger

Updated: 12 October 2026. This is a release checklist, not a declaration that every
platform and interaction has passed acceptance testing.

## Historical Baseline

Read the Mac, Linux, and Windows launchers, README files, intake source,
filtering page, Analyst Room, Tactical Lab, core, and component integration in
`older versions/`. Historical copies are left untouched.

The three historical intake files share SHA-256
`a96583c3b151e9d84c0ea4f640ef6678ef6eeb2249f62e05cdf10f7eb05d32ee`.
The three cores share SHA-256
`11b6ade0fba4cdeef086bb09a4be9de1918dc93db14f9792a7537bb76facafc0`.
All three filtering pages, all three Analyst Room pages, and all three Tactical
Lab pages also match their respective platform copies byte for byte.
The platform-specific differences are installation, launch, theme patching,
file dialogs, and dependency setup rather than different analytical algorithms.

## Architecture

- One shared HTML/JS intake, filtering, project manager, and analytical shell.
- One local Python API and the existing clipping/scraping engine.
- Preserve the complete original Analyst Room and Tactical Lab implementations
  in an embedded, local Streamlit workspace. These are retained implementations,
  not rewrites in the new HTML design system.
- A project adapter supplies saved CSV paths, footage, all period markers,
  separate period videos, and corrections to those workspaces.
- The analytical subprocess is started on demand and stopped with its owner.
- Windows/Linux use the packaged backend and Tauri shell. macOS uses the
  Homebrew launcher and the same shared frontend in the browser.
- AI filtering remains excluded, as requested previously.

## Feature Checklist

| Feature | Current Implementation | Evidence Or Remaining Check |
| --- | --- | --- |
| Independent named local projects | UUID directories and atomic project JSON | Isolation, restart, patch, and legacy-history tests |
| New project / reopen | Both shared pages; navigation project picker | Browser creation, independent IDs, rename/reload, and picker checked |
| Scrape metadata preservation | Project-specific data directories | Existing scraper integration retained; live providers remain external dependencies |
| Scoresway and WhoScored | Existing source adapters | Source-validation tests; fresh live-provider regression still required |
| Batch scrape | Collapsed batch control, one project per URL, partial failure report | Needs live multi-URL acceptance |
| Imported match CSV | Streamed local import with column validation | HTTP import regression |
| Event data table / search / period filters | Intake preview and full dialog | Existing implementation retained; browser check required after each change |
| Full match playback / keyboard seek | Local media tokens and HTTP ranges | Range regression; video smoke test |
| Kickoffs for 1H / 2H / ET1 / ET2 / shootout | Explicit marker inputs and use-playhead action | Marker validation and project adapter tests |
| Scrubbing must not change saved kickoffs | Separate playhead and marker state | Browser regression required |
| Separate second-half / extra-time / shootout files | Per-project video references, render source selection | Mapping tests and individual extra-time source/pixel smoke; full ET2/PEN real-match acceptance pending |
| Mac browser-safe video and CSV import | No tkinter video picker on macOS | Source and HTTP tests; native macOS acceptance pending |
| Linux without tkinter | Browser import fallback and typed export directory | Native Linux acceptance pending |
| Teams / multiple players / period / action types | Full shared filtering workspace | Existing focused API regressions |
| Non-AI action qualifier catalog | 64 definitions, data-aware availability, ANY/ALL logic | Focused qualifier regressions; exhaustive per-flag acceptance pending |
| Presets | Set pieces, progression, attacking, defending | Retained original filtering semantics |
| Pitch / depth zones | Shared controls and original engine | Original calculations reused |
| xT minimum / Top N | Shared controls and original engine | Retained; exhaustive mixed-filter acceptance pending |
| Filter and export settings saved with project | Atomic project patch | Patch-preservation regression |
| Filter snapshots | Atomic local shared library, migrated browser/project snapshots, recoverable deletion | Restart and recoverability regression; browser acceptance pending |
| Before / after / merge gap | Shared controls and original engine | Real two-second render smoke |
| Timeline corrections | Period-specific additive corrections | Boundary and other-period regressions |
| Editable clip previews | Real FFmpeg rendering, start/end edits, exclusions | Preview and edited-window regressions |
| Clip selection range | First/last numeric clip controls | Seven-goal Chelsea plan and range 2-3 persist after browser reload |
| Combined and individual exports | Original engine; per-project default export directory | Combined and individual synthetic-video exports decoded; real-match multi-clip acceptance pending |
| Format / CRF / speed / audio bitrate | Shared advanced settings | Config validation; MKV previously manually tested |
| Cancellation and logs | Existing cancellation-aware engine and progress polling | Cancellation-event regression; native in-flight FFmpeg cancellation acceptance pending |
| Export downloads | Registered local media URLs; saved export history | Download bytes match real individual export; browser save-dialog acceptance pending |
| Avoid overwriting earlier exports | Reserved names for active reels, unique suffix for repeated names, unique individual directories | Repeat-export media smoke and concurrent-name reservation regression |
| Shot map / penalty shootout map | Original interactive component | All-view render test; click/export acceptance pending |
| Pass maps / pass networks | Original component | Network and team-view mode render tests |
| Defensive actions | Original component | All-view render test |
| Dribbles and carries | Original component | All-view render test |
| Goalkeeper actions / shots faced / distribution | Original component | All-mode render test; empty-long-pass bug fixed |
| Build-up chains / possession / final-third / box entries | Original component and core | All-mode render tests |
| Pressing | Original component and core | All-view render test |
| Player comparison / radar / zones / top moments / reels | Original page | Render regression; real moment/reel acceptance pending |
| Defensive and attacking transitions | Original Tactical Lab | All-view render tests |
| Style profile / trends / zone heatmaps | Original Tactical Lab | Render regression; missing-zone import bug fixed |
| Set pieces / restarts | Original Tactical Lab | All-view render test |
| Tactical Video Lab / playlists / moment and reel export | Original Tactical Lab | Render regression; real-video acceptance pending |
| Multi-match Tactical Lab | Original multi-match loading, saved-project CSV list | Multi-match numerical and video-source acceptance pending |
| Map PNG/GIF and chart exports | Original components and bundled chart libraries | Browser exports acceptance pending |
| Compact brand / version footer | CM superscript 1.3 and menu; every shared screen | Intake geometry at widths 1021, 614, 390; desktop intake/filter/Analyst screenshots and narrow filter screenshot |
| Soft chrome football | Locally bundled GLB and PNG fallback | Prior browser/pixel checks; unchanged this pass |

## Platform And Release Gates

Local verification on 12 October 2026:

- 37 Python tests pass, including every retained analytical tab and secondary
  pass/goalkeeper/build-up modes, storage isolation, imported CSV, ranges,
  timing corrections, source selection, and cancellation events.
- The Node autosave regression passes: failed patches remain ordered, retries
  preserve earlier edits, and navigation waits for active imports/scrapes.
- Source-backend media smoke passes with real FFmpeg preview and reel rendering,
  repeat-export protection, individual extra-time source pixel checks, and
  download bytes. These synthetic fixtures do not prove every real-match case.
- The frozen Windows backend passes the same media smoke, including analytical
  server startup. This is an engine launch test, not a Tauri installer/UI test.
- Browser checks confirmed saved name and kickoff reload, independent projects,
  the project picker, a seven-goal Chelsea clip plan, persisted range 2-3, and
  populated Analyst/Tactical views. Screenshot capture initially timed out but
  recovered in a fresh browser tab; intake, filtering, and the populated shot
  map were inspected. Cross-frame control clicks could not be completed with
  the current browser tool, so interactive chart acceptance remains pending.
- The Rust toolchain is unavailable locally, so the changed Tauri shell has not
  been compiled here. Cross-OS browser CI and native installer tests have not run.

The CI workflow now targets Windows, Linux, and macOS for unit/render tests,
browser regression, and frozen-backend startup/media smoke testing. Release
builds run tests and a frozen-backend smoke test before bundling installers.
These checks do not prove a native installer, Gatekeeper, or package-manager
upgrade works on a user's physical machine.

GitHub reports the existing source repository is public. The user subsequently
requested keeping all new work local. Do not push, dispatch Actions, publish a
release, or alter repository visibility until the user changes that instruction.
No new CI result may be claimed until those workflows actually run.

Remaining release blockers:

1. Run the prepared CI matrix once remote execution is authorized.
2. Validate installation, launch, shutdown, project persistence, and upgrades
   using actual Windows/Linux packages and the Homebrew formula.
3. Complete the pending feature acceptance checks above with representative
   real match data, split videos, extra time, and penalty shootouts.
4. Validate visual density and chart interactions in each native desktop
   webview. Analytical pages retain their original embedded frontend, with
   compact styling, and have not been fully restyled in HTML/JS.
5. Resolve the source-privacy/distribution plan before publishing. A private
   source archive cannot be installed anonymously from a public Homebrew tap.

No guarantee is made that unsigned macOS software bypasses Gatekeeper. The
Homebrew approach uses a source/CLI launcher rather than an unsigned app bundle,
but native installation and security behavior still need verification.
