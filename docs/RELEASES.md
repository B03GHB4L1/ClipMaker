# Desktop release process

VizorPlay uses the shared frontend in `ui/`, its local API in `packaging/`, and
the existing clipping and analytical implementations in `app/`.

Release readiness is tracked in `docs/FEATURE_PARITY.md`. Do not treat a
successful build as proof that installation, native interactions, or upgrades
have passed. Public test runs are authorized; publishing a release still requires
the owner's separate instruction. No release has been published by these tests.

The release workflow first calls Full Desktop E2E against the same commit. It
then assembles the exact NSIS/DEB installer bytes and Homebrew source archive
retained by successful acceptance jobs; it never rebuilds after acceptance.
SHA-256 receipts bind every payload to that commit and its passing evidence.
Missing receipts, changed files, mismatched commits or failed jobs block the
candidate. Optional live-provider URLs are not set by this workflow: skipped
means not tested, not provider certification. The current release gates are in
`RELEASE_1_0_CHECKLIST.md`.

Manually dispatch **Desktop release** on `codex/release-packaging` to prepare a
candidate without publishing. Download `VizorPlay-1.0.0-candidate` from that
run's artifacts: it includes installers, the exact tested source archive,
Homebrew formula, WinGet manifests, acceptance receipts, a candidate manifest
and SHA256SUMS. Artifacts expire after 30 days. Verify checksums before use.

## Windows and Linux

Only after separate owner authorization, pushing `v1.0.0` starts acceptance and
attaches its exact tested candidate to the GitHub release. No tag should be
created merely to test the workflow. Windows NSIS and Ubuntu 22.04 `.deb` are
the supported native paths. Untested RPM packages are excluded from this
candidate rather than being advertised as verified installers.

The release also includes a three-file WinGet manifest set. After the first
version is accepted into the WinGet community repository, Windows users can
install with `winget install --id B4L1.ClipMaker -e` and receive later versions
with `winget upgrade --id B4L1.ClipMaker -e`.

The desktop shell starts the packaged shared-UI backend on an available local
port and displays it inside the VizorPlay window. Analytical workspaces start
a second local server on demand. The user does not need Python,
FFmpeg, Playwright, Chromium, Node.js, or Rust.

## macOS

macOS uses a Homebrew formula rather than an unsigned application bundle. The
formula installs the shared source and a `clipmaker` launcher. On its first run,
the launcher creates a private Python environment under the user's Library,
installs the pinned dependencies and Playwright headless browser, then opens the
local VizorPlay interface in the default browser. The primary launcher is
`vizorplay`; `clipmaker` remains a compatibility alias.
The formula includes the analytical-server adapter. Video and CSV selection use
browser-safe local imports on macOS; the export-folder picker uses macOS's own
folder chooser, with a typed-path fallback. No quarantine-removal workaround is
installed or promised.

The prepared formula downloads the exact source archive attached to the release,
using the checksum of the archive installed during acceptance. The source repo
is public by the owner's instruction. The separate tap remains private and
empty until an authorized publication step; `brew tap` is not yet a public
installation path.

The candidate includes a rendered `clipmaker.rb` formula with its source SHA-256.
To render a tag-archive formula locally when troubleshooting, run:

```text
python packaging/render_homebrew_formula.py --version 1.0.0 --sha256 HASH --output Formula/clipmaker.rb
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
sudo apt install ./VizorPlay_1.0.0_amd64.deb
```

Installing a newer package with the same command upgrades the existing app and
keeps VizorPlay's per-user runtime data. Debian packages declare GStreamer
playback dependencies. There is no apt/dnf repository or in-app automatic updater
yet: Linux updates currently require downloading the newer DEB. Fedora/RPM and
other distributions remain outside the verified 1.0 candidate scope.

Acceptance installs a controlled 0.9.0 predecessor built from the same source,
saves project data, upgrades to 1.0.0, relaunches and renders/exports, reinstalls,
then uninstalls while preserving the isolated project. macOS likewise upgrades
a local test formula from 0.9.0 to 1.0.0 and reopens the project. These checks
exercise different-version package lifecycle; they do not certify migration
from every historical ClipMaker binary/schema or the public package channels.

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
