# Plan: drop the bundled Playwright browser

Status: implemented 11 November 2026 (results below). Checks and Full Desktop E2E green
on Windows, Linux and macOS at d719d03; the installed-browser test ran on all three.

## Findings

- Playwright is used in one place: `app/scoresway_scraper.py`,
  `discover_with_playwright`. It is a **fallback**, run only when static
  discovery cannot find the PerformFeeds `match` and `matchevent` URLs in the
  page HTML. WhoScored never uses it (curl_cffi only).
- Static discovery worked on the live match the CI live check uses
  (Sabah vs Borussia Dortmund, 11 November 2026): "Static Opta widget config
  discovery succeeded", event feed 917 KB, no browser started.
- The original apps in `older versions/` have the same fallback, so it is part
  of the feature baseline and should be kept, not deleted.
- Its cost in the frozen backend (Windows, local build of 10 November):
  `playwright/driver` is 755 MB of the 973 MB total: Node 86 MB, full Chromium
  394 MB, Chromium headless shell 259 MB. CI builds install only the headless
  shell, so a CI-built backend carries about 350 MB for it. The Homebrew
  launcher also downloads the headless shell on first launch.
- `curl_cffi` (already a dependency) has a WebSocket client, which is all a
  minimal Chrome DevTools Protocol (CDP) client needs.

## Proposal

Replace the Playwright fallback with a small CDP client that drives a
Chromium-family browser **already installed** on the computer, and remove
Playwright from the shipped app.

1. **Browser locator (platform adapter).** Find, in order: Microsoft Edge
   (installed with Windows 10/11), Google Chrome, Chromium, Brave. Known paths
   per OS plus `PATH`. No download, no install.
2. **CDP fallback** in `app/browser_capture.py`: start the browser with
   `--headless=new --remote-debugging-port=0` and a temporary profile; read
   `DevToolsActivePort`; enable `Network`; navigate; collect
   `api.performfeeds.com/soccerdata/{match,matchevent}` responses and fetch
   their bodies with `Network.getResponseBody`; stop the browser and delete the
   profile in `finally`, including on timeout and cancellation. Same matching
   rules (match id) as today.
3. **Honest failure.** If static discovery fails and no supported browser is
   found, the scrape fails with: "This page needs a browser to read. Install
   Microsoft Edge or Google Chrome, or try again later." Never silently skip.
4. **Packaging.** Remove `playwright` from `requirements.txt`, from
   `collect_all` in the PyInstaller spec (add it to excludes), and the
   `playwright install` step from the Homebrew bootstrap. Playwright stays in
   the test requirements only, for browser smoke tests.
5. **Docs.** INSTALLATION.md and the release checklist state the browser
   requirement for the fallback per OS (Edge preinstalled on Windows; Chrome
   or Edge on macOS and Linux; Safari and Firefox cannot be used).

## Tests

- Unit: browser locator per OS with fake paths; CDP client against a fake
  WebSocket peer (navigate, capture, body fetch, match-id filtering, timeout,
  cleanup of process and profile); the no-browser error message.
- Integration (all three CI OSes): a local test page that loads fake
  `/soccerdata/match/...` and `/matchevent/...` JSON, captured through the real
  installed browser (CI runners have Chrome; Windows also has Edge).
- Contract: the frozen backend contains no `playwright` folder and no
  `node` binary; Homebrew bootstrap no longer runs `playwright install`.
- Existing: live Scoresway and batch checks (optional workflow inputs), source
  and frozen smoke, browser smoke, full suite.

## Expected result

- Frozen backend: roughly 973 MB to about 220 MB locally (about 350 MB less
  than a CI build), with a matching cut to installer size and install time.
- Homebrew: first launch no longer downloads a browser.
- Scraping: unchanged when static discovery works (the common case seen so
  far); the fallback uses the system browser instead of a bundled one.

## Risks

- A Linux or macOS user with no Chromium-family browser loses only the
  fallback, and gets a clear message. Their static scrapes still work.
- System browsers update on their own; CDP is stable for the few commands
  used, and CI tests the real installed browser on every run.
- Pages that detect headless browsers could behave differently from the
  bundled shell; the live check covers the known provider.

## Next size targets after this

`imageio_ffmpeg` (84 MB; Homebrew already depends on system ffmpeg),
`numpy.libs` (21 MB), `PIL` (13 MB, check whether it is still needed) and
Tk (file dialogs).

## Results (11 November 2026, Windows 11)

- `app/browser_capture.py`: locator plus a standard-library CDP client.
  Edge's Windows launcher hands off to a child process and exits with 0, so
  the browser is closed with CDP `Browser.close`; if that fails, processes
  still using the throwaway profile are ended. Repeated runs left no browser
  processes and no profile folders.
- Scoresway pages first load an interstitial check, so capture waits for the
  network to go quiet after the last load rather than a fixed delay.
- Found while testing on the live match: `extract_match_id` returned the team
  slug (`sabah`) for `/match/<teams>/<id>/<tab>` URLs, so a match-id filter
  would reject the real feed; and the match-summary page never requests the
  event feed (the old Playwright fallback had the same gap). Fixed: the Opta
  id is parsed, and the event feed URL is built from the captured match feed's
  outlet key and id. Live fallback through Edge: match 8.6 KB and events
  917 KB in 13.6 s.
- Tests: `tests/test_browser_capture.py` (locator, scripted CDP peer, Scoresway
  wiring, real installed browser against a local page; CI requires the browser
  test with `VIZORPLAY_REQUIRE_BROWSER_TEST=1`). The scripted-peer test caught
  a race where a second response of the same kind could replace the first.
  Packaging contract: no Playwright in requirements, build, bootstrap or CI
  bundling.
- Verified locally: 227 Python tests (2 OS-specific skips), source smoke,
  frozen smoke, full browser smoke.
- Size: frozen backend 973 MB to 216 MB (local Windows build; no Playwright
  or Node.js inside).
