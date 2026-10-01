# Desktop release process

ClipMaker uses one shared application source in `app/`.

## Windows and Linux

Pushing a version tag such as `v1.3.0` starts `.github/workflows/release.yml`.
GitHub's hosted runners build the Windows NSIS installer plus Linux `.deb` and
`.rpm` packages, then attach the files to the GitHub release.

The release also includes a three-file WinGet manifest set. After the first
version is accepted into the WinGet community repository, Windows users can
install with `winget install --id B4L1.ClipMaker -e` and receive later versions
with `winget upgrade --id B4L1.ClipMaker -e`.

The desktop shell starts the packaged Streamlit backend on an available local
port and displays it inside the ClipMaker window. The user does not need Python,
FFmpeg, Playwright, Chromium, Node.js, or Rust.

## macOS

macOS uses a Homebrew formula rather than an unsigned application bundle. The
formula installs the shared source and a `clipmaker` launcher. On its first run,
the launcher creates a private Python environment under the user's Library,
installs the pinned dependencies and Playwright headless browser, then opens the
local ClipMaker interface in the default browser.

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
