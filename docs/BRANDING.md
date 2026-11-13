# VizorPlay

The current product name is **VizorPlay**. Its displayed version is **1.0**,
shown only in the application footer, not appended to the app name or logo.
Build metadata uses the equivalent semantic version `1.0.0`.

The shared intake, filter, and analysis screens, desktop product/window title,
chart watermarks, launch messages, and football artwork use the new branding.
Programs users see are named VizorPlay: `vizorplay.exe` and the engine
`vizorplay-engine.exe` on Windows, `/usr/bin/vizorplay` on Linux, and the
Homebrew formula and command `vizorplay` (renamed 13 November 2026,
`docs/RENAME_TO_VIZORPLAY_PLAN.md`). The WinGet identifier is `B4L1.VizorPlay`.

## Compatibility

The repository name, the Homebrew tap name, the Tauri application identifier
(`com.b4l1.clipmaker`, which names the project folder), Python module names
and browser storage keys deliberately keep their old internal names. Renaming
these would orphan saved projects or need a separate migration. Upgrades
remove the old `clipmaker.exe` and `clipmaker-server.exe`; the macOS launcher
moves `~/Library/Application Support/ClipMaker/runtime` to `.../VizorPlay/runtime`
once. `VIZORPLAY_RUNTIME_DIR` and `VIZORPLAY_DATA_DIR` replace the old
`CLIPMAKER_*` names, which are still read.
No GitHub repository or external Homebrew tap has been changed or published.

Historical files in `older versions/` remain unchanged. Previous release notes
and test reports describe their original product names and versions.

Version 1.0.0 is numerically lower than the previous 1.3.0 metadata. Future
release/update publication must account for that reset; these source changes
are not a tested upgrade or downgrade path for an existing installation.

## Local Checks (19 October 2026)

- Shared-screen brand/footer and package metadata regression added.
- Browser checked intake and filter branding and 390px navigation layout.
- The new silver/green football is generated with Blender; original artwork
  and editable design files remain intact. The runtime GLB is about 580 KiB.
- Native installer builds and published package updates are outside this rename.
