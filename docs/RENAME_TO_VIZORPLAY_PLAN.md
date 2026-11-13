# Plan: rename ClipMaker to VizorPlay

Status: implemented 13 November 2026 after the owner's approval; CI results
are recorded in `docs/RELEASE_1_0_CHECKLIST.md`.

## Goal

Nothing a user sees says "ClipMaker": the program is `vizorplay.exe`, the
engine is `vizorplay-engine.exe`, the Mac command is `vizorplay`. Existing
installs upgrade in place and keep every project, preset and setting.

## What a user sees today

| Where | Today | After |
|---|---|---|
| Window title, Start menu, install folder | VizorPlay | unchanged |
| App program (Windows) | `clipmaker.exe` | `vizorplay.exe` |
| Engine program | `backend/clipmaker-server.exe` | `backend/vizorplay-engine.exe` |
| Linux package and command | `clipmaker` | `vizorplay` |
| Homebrew formula / command | `clipmaker` (plus a `vizorplay` link) | `vizorplay` |
| winget package id (prepared, unpublished) | `B4L1.ClipMaker` | `B4L1.VizorPlay` |

## The one risky part: where projects are saved

Projects, imports, previews and exports live in a folder named after the
app's internal ID, `com.b4l1.clipmaker`:

- Windows: `%LOCALAPPDATA%\com.b4l1.clipmaker`
- The webview's own storage (filter presets kept in the browser) is keyed by
  the same ID.

Changing the ID would make the new version open an empty folder, and the
projects would look lost.

**Recommendation: keep the internal ID `com.b4l1.clipmaker`.** Users never see
it, and keeping it means no migration code, no risk to projects, and upgrades
keep working exactly as tested. (Changing it later would need a tested
one-time move of the data folder and webview storage.)

Also kept, for the same reason, because they are internal or saved in users'
browsers: the `clipmaker.*` browser storage keys, the Python module names
(`clipmaker_core`, `clipmaker_api_server`), and the GitHub repository name
(renaming the repository is a separate decision; GitHub redirects old links).

## Steps

1. **App program name.** Cargo package `clipmaker` to `vizorplay` (library
   `vizorplay_lib`), so Windows builds `vizorplay.exe` and Linux installs
   `/usr/bin/vizorplay`.
2. **Engine program name.** PyInstaller `name="vizorplay-engine"`; update the
   path the app starts (`src-tauri/src/lib.rs`) and every workflow, smoke
   test and release script that runs `clipmaker-server`.
3. **Upgrade from the old name.** An installer hook
   (`src-tauri/windows/hooks.nsh`) deletes the old `clipmaker.exe` and
   `backend\clipmaker-server.exe` after install and uninstall. The Linux
   package keeps its package name, so `apt` replaces the old files. The macOS
   launcher moves its old `ClipMaker/runtime` folder to `VizorPlay/runtime` once.
   CI builds the predecessor from the last pre-rename commit (`fcd36ad`) and
   upgrades it.
4. **Homebrew.** Formula `vizorplay` with the command `vizorplay`. The formula
   was never published, so no `clipmaker` alias is kept. The tap repository
   keeps its name (`homebrew-clipmaker`); renaming it is a separate GitHub change.
5. **winget.** Package id `B4L1.VizorPlay` (unpublished, so no migration).
6. **Environment variables.** Accept `VIZORPLAY_DATA_DIR` /
   `VIZORPLAY_RUNTIME_DIR`, still reading the old `CLIPMAKER_*` names.
7. **Docs.** Installation, release, testing and checklist pages.

## Verification

- Contract tests: no user-visible `clipmaker` names in the build settings;
  the internal ID is unchanged.
- CI install tests on Windows and Linux: install the current `clipmaker`
  build with a saved project, upgrade to the renamed build, confirm the
  project opens, then uninstall and confirm nothing named ClipMaker remains
  in the Start menu, program list or install folder.
- Homebrew upgrade test from the `clipmaker` formula to `vizorplay`.
- A manual check on your PC: upgrade over your current install and open an
  existing project.

## Size

About 230 mentions across ~40 files, mostly tests and build scripts. One
commit for the rename, one for upgrade handling, then a full CI run.
