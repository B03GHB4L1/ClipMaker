# Automated Desktop E2E Testing

## For The Owner

You do not need your own Mac or Linux computer. The **Full Desktop E2E** GitHub
Actions workflow requests separate Windows, Linux, and macOS runners. It does
not publish source, create a release, or update a package manager.

### Before The First Run

1. The user authorized pushing and running tests in the existing public repository
   on 20 October 2026. The private-repository restriction has been removed. Test
   artifacts and source are therefore public; only synthetic fixtures belong here.
2. Push the test branch `codex/release-packaging`; this automatically starts the
   full suite. Do not push a release tag or run Desktop release to test it.
3. The workflow file must be present on the repository's default branch for
   GitHub's manual Run workflow button to appear. A later run can select a
   different branch containing the workflow.
4. Check your GitHub Actions allowance and spending limit. Runner availability
   and limits depend on repository/account settings. Full builds run automatically
   only on the named test branch, or via manual dispatch.

### Each Test Run

1. Open the repository on GitHub, then select **Actions**.
2. Select **Full Desktop E2E**, then **Run workflow** and choose the branch.
3. Optionally paste one current Scoresway match URL and/or one current WhoScored
   match URL. Leaving them blank deliberately skips live-provider testing.
4. Click **Run workflow**. All platform jobs are started automatically. You can
   close your computer while the hosted runners work.
5. Open the run and check **Full E2E verdict**. Required jobs must succeed; a
   skipped required job is not counted as a pass. The optional live-provider
   job is shown separately and "skipped" means not tested.
6. On failure, open the failed step's log. The run's **Artifacts** section has
   `e2e-Windows`, `e2e-Linux`, `e2e-macOS`, `native-Windows`, `native-Linux`, and
   `homebrew-macOS` evidence when those jobs reached their test stages.

There is no Apple Developer Program dependency, code-signing credential, or
paid macOS WebDriver service in this workflow. It does not establish Gatekeeper
behavior on a user's downloaded app.

## What Runs

| Layer | Platforms | What Is Actually Exercised |
| --- | --- | --- |
| Regression | All three | Unit/API/project/analytical regressions and autosave test |
| Source browser | All three | Real UI CSV/video uploads, kickoff inputs, keyboard menu, filters, edited preview and download, real export/download/decode, saved-plan reload, analysis/tactical tab entry, narrow layouts |
| Source media | All three | FFmpeg combined/individual exports, extra-time source pixels, range requests, overwrite protection, real export cancellation after a completed clip |
| Frozen backend | All three | PyInstaller build followed by the same media and browser journeys, not merely successful compilation |
| Installed native app | Windows and Linux | Build NSIS/DEB, install into runner, launch installed Tauri window via native WebDriver, filter/edit/export/decode, close and launch again, verify saved plan |
| Homebrew installation | macOS | Archive exact checked-out commit, install a local test formula, build private Python runtime, start installed command, exercise browser journey against that installed server |
| Live providers (optional) | Linux | Real scraper -> saved project -> nonempty events; no fabricated success or substitute fixtures |

The native-window journey deliberately seeds source metadata and video references
through the local API; it does not automate OS file dialogs. The browser journey
tests the actual CSV/video upload controls. These complementary boundaries are
not interchangeable.

macOS currently ships a Homebrew launcher plus browser UI, not a Tauri .app.
Consequently its acceptance path is installation + installed launcher + browser.
The frozen macOS backend test is additional packaging coverage, not a claim that
the shipped macOS product uses that binary.

## Evidence And Isolation

- Every test uses synthetic fixtures and temporary project directories.
- Tauri accepts `VIZORPLAY_DATA_DIR` for isolated local storage. With no override,
  the existing user data location is unchanged.
- Homebrew CI sets `CLIPMAKER_RUNTIME_DIR` under the runner's temporary directory.
  The launcher accepts `--port`, `--data-dir`, and `--no-browser`; regular launches
  retain the original behavior.
- Browser failures record a traceback, screenshot, HTML, console log, Playwright
  trace and video. Backend stdout/stderr are kept outside the deleted project
  directory. The short synthetic preview/export videos are also retained.
- Native failures record driver logs, screenshot/HTML when a session exists,
  and failure text. Build or install errors remain in the Actions step logs.
- Evidence artifacts expire after seven days. Each native test builds its own
  backend and runs independently of browser jobs, retaining executable permissions
  when copying resources into its installation package.
- The workflow has read-only repository permissions. It never changes repository
  visibility or publishes a release. Public-repository execution is authorized.

## Coverage Limits

This suite is a reproducible main-workflow acceptance test, not proof that every
historical feature or every filter combination is bug-free. Outstanding ledger
items still include exhaustive chart gestures and PNG/GIF exports, every qualifier
combination, live multi-match/batch sources, real-match shootouts/ET2, native file
dialogs, RPM installation, upgrades/downgrades, uninstall, signing, Gatekeeper,
distribution downloads, and hardware/codec-specific behavior. New bug fixes should
add focused cases here as well as unit regressions.

If a live provider rejects CI traffic, changes its page, or times out, that optional
job fails visibly. Fix or investigate it; do not silently replace its result with
fixture data. The deterministic suite does not require public websites.

The first full hosted run remains necessary to validate runner dependencies,
installer paths, WebDriver versions, selectors, and platform-specific timing.
Until that run succeeds, treat these automation jobs as implemented but unverified.

## Failure Investigation (21 October 2026)

Run `39502791303` passed Linux/macOS source and frozen browser/media workflows
and the installed macOS Homebrew workflow, but failed the full verdict.

- Windows browser: CSV upload eventually returned HTTP 200 after about 144
  seconds, while the browser timed out. Console evidence recorded GPU readback
  stalls. The shared ball no longer preserves its drawing buffer, renders at
  most 30 fps, and uses the existing still without starting WebGL when reduced
  motion is requested. Browser acceptance requests reduced motion; this does not
  certify animated rendering on every graphics driver.
- Linux installed window: the app launched and reopened its seeded project.
  The test waited for a transparent, off-screen reveal section without scrolling.
  Native element lookup now scrolls into view before waiting for clickability.
- Windows installed window: WebDriver session creation failed with
  `DevToolsActivePort file doesn't exist`. Native CI is pinned to `windows-2022`
  while the [reported runner regression](https://github.com/actions/runner-images/issues/14738)
  is investigated upstream. The driver is downloaded for the installed WebView2
  runtime, not the independently installed Edge browser. Browser/backend coverage
  continues on `windows-latest`; this is not native acceptance of that image.
- Scoresway completed in the hosted live check before WhoScored failed, but the
  old harness discarded partial results and hid HTTP response bodies. It now
  saves each result, checks both providers even after a failure, and retains
  actual errors. WhoScored now includes its exception in the scraper error queue.
  Both supplied URLs passed locally (1,923 Scoresway and 1,838 WhoScored events).
  Local success is not proof that GitHub-hosted provider traffic will succeed.

These changes require a new hosted run before the full suite can be marked passed.

The rerun `39624375234` confirmed Scoresway passes on GitHub (1,923 events),
but WhoScored returns HTTP 403 from the hosted runner. This is an external
provider restriction, not a missing Python dependency; it remains a failed live
acceptance check. The app now reports the denial without suggesting an already
installed dependency. No network-block bypass or fabricated provider success
was added. The local 60-test regression suite, Node autosave test, and actionlint
validation passed during this investigation.

## Developer Commands

### Native Completion Fix (22 October 2026)

Run `39625014429` completed every browser/frozen-backend and Homebrew job, but
both native runs stopped at the export completion assertion. The Windows
failure screenshot shows the actual saved export and EXPORT COMPLETE. Selenium
`.text` reflects CSS uppercase transformation; it was incorrectly compared with
mixed-case `Export complete`. The native check now reads the DOM label via
`textContent`, still fails on real terminal errors, downloads the rendered file,
decodes it, then verifies persistence after closing/relaunching the installed app.

The Linux traceback shows the same assertion failed before diagnostic collection
hung. Each WebDriver request now has a 45-second transport deadline; page/script
timeouts, a 600-second process watchdog, persistent stage logs, and 12-minute
native acceptance steps prevent a silent hour-long diagnostic hang. Xvfb now
starts before the D-Bus session so activation inherits DISPLAY.

Native coverage now also plays the H.264 fixture and checks the edited preview's
decoded dimensions/duration inside the installed webview. Debian dependencies
include GStreamer's MP4/decoder support. These new hosted checks must pass before
native playback can be certified. Local regression: 62 Python tests plus the
Node autosave test passed; actionlint validated both workflows. Release builds
reuse the full acceptance workflow and cannot proceed when required jobs fail.

Install the separate test dependencies in a virtual environment:

```powershell
python -m pip install -r requirements-e2e.txt
python -m playwright install --with-deps chromium
python -m unittest discover -s tests -v
node --test tests/projects.test.mjs
python packaging/smoke_test.py
python tests/browser_smoke.py --evidence build/e2e/source
```

After building a frozen backend:

```powershell
python tests/browser_smoke.py --server dist/clipmaker-server/clipmaker-server.exe --evidence build/e2e/frozen
```

On Linux/macOS omit `.exe`. Native tests additionally need Rust, `tauri-driver`,
the matching Edge driver on Windows or `WebKitWebDriver` on Linux, and an installed
application. CI provisions them. Only run `native_smoke.py` against a disposable
test install. It never points to the developer's normal data directory.

## Local Verification (20 October 2026)

- 53 Python tests passed, including four new automation/launcher/formula contracts.
- Source media smoke passed with real cancellation after FFmpeg completed a clip.
- A fresh Windows frozen-backend build passed the same media and real cancellation
  smoke. Logs are `build/e2e-build.log` and `build/e2e-frozen-media.log`.
- Workflow YAML/contract checks passed. The official actionlint 1.7.12 binary,
  verified against its release checksum, was used to validate workflow expressions.
- Python test scripts compile. Browser/native automation is authored for CI and
  has not been executed locally; native Rust tools are unavailable on this machine.
- GitHub still reported the source repository PUBLIC during a read-only check.
  No changes were pushed, no workflow was dispatched, and no visibility changed.

References: [GitHub manual workflow runs](https://docs.github.com/en/actions/managing-workflow-runs/manually-running-a-workflow),
[Tauri native WebDriver setup](https://v2.tauri.app/develop/tests/webdriver/manual-setup/).
