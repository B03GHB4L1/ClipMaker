"""Browser timing baseline for the analysis workspace (Phase 0 of
docs/ANALYSIS_MIGRATION_PLAN.md).

Opens the real Analyst Room and Tactical Lab in Chromium through the shared
backend and reports, per step, wall time until the page settles and the bytes
the analysis server streams to the browser.

  python tests/analysis_timing.py                     # synthetic fixture
  python tests/analysis_timing.py --csv match.csv     # a local real match
  python tests/analysis_timing.py --json build/timing.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, request  # noqa: E402

IDLE = '[data-testid="stApp"][data-test-script-state="notRunning"]'
RUNNING = '[data-testid="stApp"][data-test-script-state="running"]'


class Meter:
    """Counts websocket bytes the Streamlit server sends to the page."""

    def __init__(self, page):
        self.bytes = 0
        page.on("websocket", lambda ws: ws.on("framereceived", self._frame))

    def _frame(self, payload):
        self.bytes += len(payload) if payload else 0


def settle(frame, started, timeout=120_000):
    """Wait for a rerun to start (if it has not already finished) and then end."""
    try:
        frame.locator(RUNNING).wait_for(timeout=1500)
    except Exception:
        pass  # Fast reruns can finish before the poll sees them.
    frame.locator(IDLE).wait_for(timeout=timeout)
    return time.monotonic() - started


def step(results, name, meter, action, frame):
    before = meter.bytes
    started = time.monotonic()
    action()
    seconds = settle(frame, started)
    results.append({"step": name, "seconds": round(seconds, 3), "bytes": meter.bytes - before})
    print(f"  {name:<44} {seconds:6.2f} s  {(meter.bytes - before) / 1e6:7.2f} MB", flush=True)


def measure(base, project_id, rounds, teams):
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        meter = Meter(page)
        for view, tabs, control in (
            ("analyst", ["◉ Shot Map", "◎ Pass Map", "■ Defensive Actions", "◈ Dribbles & Carries",
                         "⊞ Goalkeeper", "↗ Build-Up", "◆ Pressing", "⇄ Comparison"], "Shot Map team"),
            ("tactical", ["Defensive Transitions", "Attacking Transitions", "Style Profile", "Set Pieces",
                          "Video Lab"], None),
        ):
            for round_index in range(rounds):
                label = f"{view} r{round_index + 1}"
                started = time.monotonic()
                before = meter.bytes
                page.goto(f"{base}/analysis.html?view={view}&ui=classic&project={project_id}")
                frame = page.frame_locator("[data-analysis-frame]")
                frame.get_by_role("tab", name=tabs[0]).wait_for(timeout=120_000)
                seconds = settle(frame, started)
                results.append({"step": f"{view}: open workspace", "round": round_index + 1,
                                "seconds": round(seconds, 3), "bytes": meter.bytes - before})
                print(f"  {label} open workspace{'':<26} {seconds:6.2f} s  {(meter.bytes - before) / 1e6:7.2f} MB", flush=True)
                for tab in tabs[1:] + tabs[:1]:
                    step(results, f"{view}: switch to {tab}", meter,
                         lambda tab=tab: frame.get_by_role("tab", name=tab).click(), frame)
                if control:
                    home, away = teams
                    option = lambda name: frame.locator('[data-testid="stRadio"] label').filter(has_text=name).first
                    step(results, f"{view}: change {control}", meter, lambda: option(away).click(), frame)
                    step(results, f"{view}: change {control} back", meter, lambda: option(home).click(), frame)
                if round_index == 0:
                    page.screenshot(path=str(ROOT / "build" / f"timing-{view}.png"))
        browser.close()
    return results


# Counts map redraws: the component posts setFrameHeight after every render.
REDRAW_PROBE = """
window.__redraws = 0;
window.addEventListener("message", (event) => {
  if (event.data && event.data.type === "streamlit:setFrameHeight") window.__redraws += 1;
});
"""


def native_step(page, results, name, action, timeout=60_000):
    """Time an action until the analysis request finishes and the map redraws."""
    before = page.evaluate("window.__redraws")
    started = time.monotonic()
    action()
    page.wait_for_function(f"window.__redraws > {before} && !document.querySelector('.native-panel[aria-busy]')",
                           timeout=timeout)
    seconds = time.monotonic() - started
    results.append({"step": name, "seconds": round(seconds, 3), "bytes": 0})
    print(f"  {name:<44} {seconds:6.2f} s", flush=True)


def native_tab_switch(page, results, tab):
    """Time a tab switch until its data loads and its maps or charts have drawn."""
    started = time.monotonic()
    page.get_by_role("tab", name=tab, exact=True).click()
    page.wait_for_function("""() => {
        const panel = document.querySelector('.native-panel');
        if (!panel || panel.hasAttribute('aria-busy') || !panel.firstElementChild) return false;
        const plots = panel.querySelectorAll('.native-figure');
        if (plots.length) return [...plots].every(p => p.closest('[hidden]') || p.querySelector('.main-svg'));
        const frames = [...panel.querySelectorAll('iframe')];
        return frames.every(f => parseInt(f.style.height || '0') > 120);
    }""", timeout=60_000)
    seconds = time.monotonic() - started
    results.append({"step": f"native: switch to {tab}", "seconds": round(seconds, 3), "bytes": 0})
    print(f"  native: switch to {tab:<32} {seconds:6.2f} s", flush=True)


def measure_native(base, project_id, rounds, teams):
    from playwright.sync_api import sync_playwright
    results = []
    home, away = teams
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script(REDRAW_PROBE)
        for round_index in range(rounds):
            url = f"{base}/analysis.html?view=analyst&project={project_id}&ui=native&tab=shot-map"
            started = time.monotonic()
            page.goto(url)
            page.wait_for_function("window.__redraws > 0 && !document.querySelector('.native-panel[aria-busy]')",
                                   timeout=120_000)
            seconds = time.monotonic() - started
            results.append({"step": "native: open workspace on Shot Map", "round": round_index + 1,
                            "seconds": round(seconds, 3), "bytes": 0})
            print(f"  native r{round_index + 1} open workspace on Shot Map{'':<14} {seconds:6.2f} s", flush=True)
            team = lambda name: page.locator(".native-panel [role=radiogroup][aria-label=Team] label").filter(has_text=name).first
            native_step(page, results, "native: change Shot Map team", lambda: team(away).click())
            native_step(page, results, "native: change Shot Map team back", lambda: team(home).click())
            picker = page.locator(".native-picker select")
            native_step(page, results, "native: select a shot",
                        lambda: picker.select_option(picker.locator("option").nth(1).get_attribute("value")))
            native_step(page, results, "native: clear selection",
                        lambda: page.get_by_role("button", name="Clear selection").click())
            for tab in ["Pass Map", "Defensive Actions", "Dribbles & Carries", "Goalkeeper", "Build-Up",
                        "Pressing", "Comparison", "Shot Map"]:
                native_tab_switch(page, results, tab)
            started = time.monotonic()
            page.goto(f"{base}/analysis.html?view=tactical&project={project_id}&ui=native&tab=defensive-transitions")
            page.wait_for_function("""() => { const p = document.querySelector('.native-panel');
                return p && !p.hasAttribute('aria-busy') && document.querySelector('.native-figure .main-svg'); }""",
                                   timeout=120_000)
            seconds = time.monotonic() - started
            results.append({"step": "native: open Tactical Lab", "round": round_index + 1, "seconds": round(seconds, 3), "bytes": 0})
            print(f"  native r{round_index + 1} open Tactical Lab{'':<27} {seconds:6.2f} s", flush=True)
            for tab in ["Attacking Transitions", "Style Profile", "Set Pieces", "Video Lab", "Defensive Transitions"]:
                native_tab_switch(page, results, tab)
            if round_index == 0:
                page.screenshot(path=str(ROOT / "build" / "timing-native-shot-map.png"))
        browser.close()
    return results


def summarize(results):
    groups = {}
    for item in results:
        groups.setdefault(item["step"], []).append(item)
    summary = []
    for name, items in groups.items():
        summary.append({"step": name, "median_s": round(statistics.median(i["seconds"] for i in items), 3),
                        "max_s": round(max(i["seconds"] for i in items), 3),
                        "median_mb": round(statistics.median(i["bytes"] for i in items) / 1e6, 2),
                        "samples": len(items)})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, help="match CSV (default: synthetic fixture)")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--backend", nargs="+", default=[sys.executable, str(ROOT / "packaging" / "clipmaker_api_server.py")],
                        help="backend command (default: source server)")
    parser.add_argument("--json", type=Path, help="write raw results and summary here")
    parser.add_argument("--native", action="store_true", help="also time the native Shot Map")
    parser.add_argument("--native-only", action="store_true", help="time only the native Shot Map")
    args = parser.parse_args(argv)
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vizorplay-timing-") as name:
        root = Path(name)
        csv = args.csv.resolve() if args.csv else root / "fixture.csv"
        if not args.csv:
            from tests.analysis_fixture import write_fixture
            write_fixture(csv)
        with backend(args.backend, root / "data") as base:
            project = request(base, "/api/projects", {"name": "Timing baseline"})["project"]
            match = request(base, f"/api/files/upload?project={project['id']}", raw=csv.read_bytes(),
                            headers={"Content-Type": "application/octet-stream", "X-File-Name": csv.name})["match"]
            request(base, f"/api/projects/{project['id']}", {"markers": {"1H": "00:00:00", "2H": "00:50:00"}})
            # The team radios show event team names, resolved from the fixture labels.
            import pandas as pd
            sys.path.insert(0, str(ROOT / "app"))
            from team_names import resolve_home_away
            event_teams = pd.read_csv(csv, usecols=["team"], low_memory=False)["team"].dropna().astype(str).unique().tolist()
            teams = resolve_home_away(str(match["home_team"]), str(match["away_team"]), event_teams)
            results = [] if args.native_only else measure(base, project["id"], args.rounds, teams)
            if args.native or args.native_only:
                results += measure_native(base, project["id"], args.rounds, teams)
    summary = summarize(results)
    print("\nMedian over rounds:")
    for item in summary:
        print(f"  {item['step']:<48} {item['median_s']:6.2f} s (max {item['max_s']:5.2f})  {item['median_mb']:6.2f} MB")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"input": csv.name, "rounds": args.rounds, "summary": summary,
                                         "results": results}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
