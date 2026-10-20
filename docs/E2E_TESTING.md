# Automated Desktop E2E Testing

## For The Owner

You do not need your own Mac or Linux computer. The **Full Desktop E2E** GitHub
Actions workflow requests separate Windows, Linux, and macOS runners. It does
not publish source, create a release, or update a package manager.

### Before The First Run

1. Make the source repository private yourself. Open the repository's Settings,
   then General, then Danger Zone, then Change repository visibility. Follow
   GitHub's confirmation steps. The assistant must not change visibility.
2. Once privacy is confirmed, authorize pushing the committed test changes to
   that private repository. Work is currently local only. Do not push a release
   tag or run the separate Desktop release workflow to test this suite.
3. The workflow file must be present on the repository's default branch for
   GitHub's manual Run workflow button to appear. A later run can select a
   different branch containing the workflow.
4. Check your GitHub Actions allowance and spending limit. Private-repository
   runners have account-dependent usage limits; macOS/build jobs can consume
   substantial minutes. This is why the full suite is manual by default.

### Each Test Run

1. Open the private repository on GitHub, then select **Actions**.
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
- Evidence artifacts expire after seven days. Backend transfer archives expire
  after three days and preserve Linux executable permissions.
- The workflow has read-only repository permissions. A privacy gate runs before
  any checkout. It never changes repository visibility or publishes a release.

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

## Developer Commands

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
