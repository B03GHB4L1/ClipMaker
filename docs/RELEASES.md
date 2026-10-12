# Desktop release process

ClipMaker uses the shared frontend in `ui/`, its local API in `packaging/`, and
the existing clipping and analytical implementations in `app/`.

Release readiness is tracked in `docs/FEATURE_PARITY.md`. Do not treat a
successful build as proof that installation, native interactions, or upgrades
have passed. New remote builds are currently on hold at the user's request.

## Windows and Linux

Pushing a version tag such as `v1.3.0` starts `.github/workflows/release.yml`.
GitHub's hosted runners build the Windows NSIS installer plus Linux `.deb` and
`.rpm` packages, then attach the files to the GitHub release.

The release also includes a three-file WinGet manifest set. After the first
version is accepted into the WinGet community repository, Windows users can
install with `winget install --id B4L1.ClipMaker -e` and receive later versions
with `winget upgrade --id B4L1.ClipMaker -e`.

The desktop shell starts the packaged shared-UI backend on an available local
port and displays it inside the ClipMaker window. Analytical workspaces start
a second local server on demand. The user does not need Python,
FFmpeg, Playwright, Chromium, Node.js, or Rust.

## macOS

macOS uses a Homebrew formula rather than an unsigned application bundle. The
formula installs the shared source and a `clipmaker` launcher. On its first run,
the launcher creates a private Python environment under the user's Library,
installs the pinned dependencies and Playwright headless browser, then opens the
local ClipMaker interface in the default browser.
The formula includes the analytical-server adapter. Video and CSV selection use
browser-safe local imports on macOS; the export-folder picker uses macOS's own
folder chooser, with a typed-path fallback. No quarantine-removal workaround is
installed or promised.

The formula currently downloads a tagged source archive. It is not a way to
distribute an anonymously installable application while concealing that source;
resolve the private-source distribution plan before publishing it.

The tagged release automatically includes a rendered `clipmaker.rb` formula
with the correct source SHA-256. To render it locally when troubleshooting, run:

```text
python packaging/render_homebrew_formula.py --version 1.3.0 --sha256 HASH --output Formula/clipmaker.rb
```

The resulting formula belongs in the separate `homebrew-clipmaker` tap.
Once that tap is published, macOS users install and upgrade with:

```text
brew tap B03GHB4L1/clipmaker
brew install clipmaker
brew upgrade clipmaker
```

## Linux installation and upgrades

Ubuntu, Debian, and Linux Mint users install a downloaded package with:

```text
sudo apt install ./ClipMaker_1.3.0_amd64.deb
```

Fedora and RHEL-family users install a downloaded package with:

```text
sudo dnf install ./ClipMaker-1.3.0-1.x86_64.rpm
```

Installing a newer package with the same command upgrades the existing app and
keeps ClipMaker's per-user runtime data.

## Verification

Run the source tests and a real local-media smoke test:

```text
python -m unittest discover -s tests -v
python packaging/smoke_test.py
```

After PyInstaller builds, use `--server` with the actual packaged executable.
The smoke test creates disposable synthetic data, renders and decodes a clip,
checks media seeking, and starts the analytical server. It does not operate
on the user's saved projects.

The Checks workflow has Windows, Linux, and macOS matrices plus a CI-only
browser regression in `tests/browser_smoke.py`. Do not claim those runs passed
until there are actual results from the latest commit.

Local project JSON lives under `projects/<id>/project.json` in the backend's
data directory. Legacy `matches.json` is read without being overwritten.
Project video paths reference selected files; browser imports make a local copy
under the project. Snapshots live in `filter-snapshots.json`, independent of the
random server port. Deleted snapshots are retained under `snapshot-trash/`.
