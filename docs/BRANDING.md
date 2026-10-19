# VizorPlay

The current product name is **VizorPlay**. Its displayed version is **1.0**,
shown only in the application footer, not appended to the app name or logo.
Build metadata uses the equivalent semantic version `1.0.0`.

The shared intake, filter, and analysis screens, desktop product/window title,
chart watermarks, launch messages, and football artwork use the new branding.
Homebrew exposes `vizorplay` alongside the existing `clipmaker` command.

## Compatibility

The repository name, WinGet package identifier, Tauri application identifier,
Python module names, storage directories, environment variables, and browser
storage keys deliberately keep their old internal names. Renaming these would
require a separate migration and could orphan saved projects or installed apps.
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
