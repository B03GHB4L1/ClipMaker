# Desktop release process

ClipMaker uses one shared application source in `app/`.

## Windows and Linux

Pushing a version tag such as `v1.3.0` starts `.github/workflows/release.yml`.
GitHub's hosted runners build the Windows NSIS installer plus Linux `.deb` and
`.rpm` packages, then attach the files to the GitHub release.

The desktop shell starts the packaged Streamlit backend on an available local
port and displays it inside the ClipMaker window. The user does not need Python,
FFmpeg, Playwright, Chromium, Node.js, or Rust.

## macOS

macOS uses a Homebrew formula rather than an unsigned application bundle. The
formula installs the shared source and a `clipmaker` launcher. On its first run,
the launcher creates a private Python environment under the user's Library,
installs the pinned dependencies and Playwright headless browser, then opens the
local ClipMaker interface in the default browser.

After publishing a tag, calculate the SHA-256 hash of GitHub's tag archive and
render the formula:

```text
python packaging/render_homebrew_formula.py --version 1.3.0 --sha256 HASH --output Formula/clipmaker.rb
```

The resulting formula belongs in the separate `homebrew-clipmaker` tap.
