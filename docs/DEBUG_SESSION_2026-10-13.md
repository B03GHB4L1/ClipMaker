# Desktop Debug Session - 13 October 2026

## Scope And Result

Broad local debugging of the shared frontend, local project API, clipping
engine, and retained analytical workspaces. This is not exhaustive feature
acceptance or certification of the three native releases. Work remains local;
no commits were pushed, Actions dispatched, or repository settings changed.

User projects were not used for destructive testing. Browser import, filter,
preview, export, correction, and snapshot checks used a separate server on
port 4181, synthetic video, and `build/full-debug-browser-data`. Source and
frozen-backend media smoke tests used temporary directories.

## Reproduced And Fixed

- Changing saved kickoff markers, CSV, footage, or separate period footage
  left edited clip windows available for an incorrectly aligned export.
  Source/alignment changes now invalidate the plan and selection range while
  retaining filter settings. Re-scraping also clears the plan when the CSV
  filename stays the same. Added storage and HTTP regressions.
- An export engine exiting silently, or emitting completion without creating
  an output, could report success. These cases now fail explicitly with logs.
  Worker exceptions are reported and reserved output names are released on
  exit. Added regressions for silent and missing-output completion.
- With footage loaded, Space on the navigation button played the video instead
  of opening the menu. Playback shortcuts now respect focused interactive
  controls. Reproduced before the fix and verified after it in the browser.
- Reopened clip plans displayed the misleading instruction to preview first.
  Restored plans now show their ready count. Verified in the browser and added
  a CI browser assertion.

The preceding analytical redraw fix remains covered: hidden input preservation
does not reassign transient Streamlit button state. Repeated Build-Up sequence
selection and analytical tab switching are tested.

## Verification Evidence

- 48 Python tests passed: `build/full-debug-tests.log`. Coverage includes project
  isolation/restart, API validation, media ranges, corrections, filters,
  cancellation events, clip-window edits, output reservations, and retained
  Analyst/Tactical views and secondary modes.
- The Node project autosave regression passed. `node --check` passed for both
  changed JavaScript modules. Node emits an existing module-type warning.
- Source backend real-media smoke passed: `build/full-debug-source-smoke.log`.
- Windows PyInstaller backend build passed: `build/full-debug-build.log`.
- Frozen Windows backend real-media smoke passed:
  `build/full-debug-frozen-smoke.log`. Both media runs covered CSV import, local
  projects, shared assets, playable preview, seeking, decoded combined export,
  repeated-export protection, individual extra-time video selection verified
  by decoded pixels, download bytes, and analytical server startup.
- Browser: imported Home/Away metadata and 1-0 score, event search and full-table
  dialog, keyboard menu, seek without kickoff mutation, Goal filter, 1-second
  buffers, edited 1-3.5 second preview decoding to 2.5 seconds, and actual reel
  export completed. Filters, buffers, and edited endpoints survived reopening.
- Browser: a P1 correction from match second 1 of -1 second rebuilt the window
  from 1-3 seconds to 0-2 seconds. Snapshot save/reset/load restored Goal filters.
- Filter layout had no document horizontal overflow at 1021, 614, and 390 pixel
  widths. No error-level console messages were captured on the isolated flow.
- One initial suite run hit a Windows connection-abort error during the rejected
  cross-origin request test. That test passed alone and the complete suite
  subsequently passed; the transient failure is not concealed.

## Remaining Acceptance And External Gates

- Fresh live Scoresway/WhoScored scraping and live batch scraping were not run
  in this session. Scrape persistence was tested with a mocked provider result.
- All 64 qualifiers and every mixed-filter combination are not exhaustively
  browser-accepted. The event dialog still shows the common preview columns,
  not an arbitrary-column CSV inspector.
- Real in-flight FFmpeg cancellation, analytical map PNG/GIF downloads, every
  interactive chart gesture, multi-match video workflows, and complete ET2/
  shootout real-match acceptance remain open in the feature ledger.
- Direct pointer automation inside the embedded analytical workspace remains
  unreliable. Earlier keyboard checks and analytical render tests are not
  substitutes for exhaustive native-webview interaction testing.
- No Tauri installer was built or launched: Rust tooling is unavailable locally.
  The frozen backend smoke result is not a Windows installer launch result.
- Linux/macOS native installation, dialogs, launch, upgrades, and uninstall
  require OS-specific acceptance. Unsigned macOS behavior is not guaranteed to
  bypass Gatekeeper. No Apple Developer membership is assumed.
- CI browser regressions were updated but not executed. GitHub Actions cannot
  be dispatched without pushing; the user's local-only instruction is retained.

See `FEATURE_PARITY.md` for the full outstanding release checklist. Do not
describe the app as complete or bug-free on the strength of this pass.
