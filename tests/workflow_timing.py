"""Time the main workflow outside the analysis screens.

Starts the backend (source or frozen), then times: backend cold start, the
intake page becoming usable, a live scrape, loading filter options, computing
clip windows, rendering one preview, and exporting a reel and individual clips
from a real match video. Prints a table; --json writes raw results.

  python tests/workflow_timing.py --video match.mp4 --scoresway-url URL
  python tests/workflow_timing.py --server dist/clipmaker-server/clipmaker-server.exe ...
  VIZORPLAY_VIDEO_ENCODER=software python tests/workflow_timing.py ...   # force x264

The scrape is network-bound and the clip timings depend on the video and the
computer; compare runs on the same machine and inputs only.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, request  # noqa: E402

SHOT_TYPES = ["Goal", "SavedShot", "MissedShots", "ShotOnPost"]


def timed(results, name, action, rounds=1):
    values, value = [], None
    for _ in range(rounds):
        started = time.perf_counter()
        value = action()
        values.append(time.perf_counter() - started)
    results.append({"step": name, "median_s": round(statistics.median(values), 3),
                    "max_s": round(max(values), 3), "samples": len(values)})
    print(f"  {name:<46} {statistics.median(values):7.2f} s (max {max(values):6.2f}, n={len(values)})", flush=True)
    return value


def wait_job(base, job_id, timeout=1800):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = request(base, f"/api/jobs/{job_id}")["job"]
        if job["status"] in {"complete", "failed", "cancelled"}:
            assert job["status"] == "complete", job
            return job
        time.sleep(0.1)
    raise AssertionError("export did not finish")


def cold_start(command, root, rounds):
    values = []
    for index in range(rounds):
        started = time.perf_counter()
        with backend(command, root / f"cold-{index}") as base:
            values.append(time.perf_counter() - started)
            request(base, "/api/health")
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", type=Path, help="frozen backend (default: source server)")
    parser.add_argument("--video", type=Path, required=True, help="real match video (first half)")
    parser.add_argument("--scoresway-url", required=True)
    parser.add_argument("--kickoff", default="00:00:30", help="first-half kick-off in the video")
    parser.add_argument("--clips", type=int, default=20, help="clips per export")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    command = [str(args.server)] if args.server else [sys.executable, str(ROOT / "packaging" / "clipmaker_api_server.py")]
    results = []
    with tempfile.TemporaryDirectory(prefix="vizorplay-workflow-") as name:
        root = Path(name)
        starts = cold_start(command, root, args.rounds)
        results.append({"step": "backend cold start", "median_s": round(statistics.median(starts), 3),
                        "max_s": round(max(starts), 3), "samples": len(starts)})
        print(f"  {'backend cold start':<46} {statistics.median(starts):7.2f} s (max {max(starts):6.2f}, n={len(starts)})")
        with backend(command, root / "data") as base:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()

                def open_intake():
                    page.goto(base + "/", wait_until="networkidle")
                    page.locator("[data-project-status]").wait_for()
                timed(results, "intake page usable (warm backend)", open_intake, args.rounds)
                browser.close()
            project = request(base, "/api/projects", {"name": "Timing"})["project"]
            scraped = timed(results, "live Scoresway scrape", lambda: request(
                base, "/api/scrape", {"url": args.scoresway_url, "project_id": project["id"]})["match"])
            request(base, f"/api/projects/{project['id']}", {
                "video_path": str(args.video.resolve()), "video_name": args.video.name,
                "markers": {"1H": args.kickoff, "2H": args.kickoff}})
            print(f"    ({len(scraped.get('events', []))} events)")
            timed(results, "load filter options", lambda: request(base, "/api/filter-options", {"match_id": project["id"]}),
                  args.rounds)
            options = {"filter_types": SHOT_TYPES, "half_filter": "1st half only"}
            windows = timed(results, "compute clip windows (shots)", lambda: request(
                base, "/api/previews", {"match_id": project["id"], "options": options})["windows"], args.rounds)
            all_passes = {"filter_types": ["Pass"], "half_filter": "Both halves"}
            many = timed(results, "compute clip windows (all passes)", lambda: request(
                base, "/api/previews", {"match_id": project["id"], "options": all_passes})["windows"], args.rounds)
            print(f"    ({len(windows)} shot windows, {len(many)} pass windows)")
            first = windows[0]
            timed(results, f"render one preview ({first['end'] - first['start']:.0f} s clip)", lambda: request(
                base, "/api/previews/render", {"match_id": project["id"], "start": first["start"], "end": first["end"],
                                              "period": first.get("period", 1)}), args.rounds)
            if not args.skip_export:
                # Default buffers (5 s before, 8 s after): 13 s clips spread across the half.
                chosen = [{"start": 120.0 + index * 160, "end": 133.0 + index * 160, "period": 1,
                           "label": f"Pass @ {index}"} for index in range(args.clips)]
                seconds = sum(item["end"] - item["start"] for item in chosen)
                for individual in (False, True):
                    label = "individual clips" if individual else "reel"

                    def export(individual=individual):
                        out = root / f"out-{time.perf_counter_ns()}"
                        job = request(base, "/api/jobs", {"match_id": project["id"], "options": {
                            "dry_run": False, "individual_clips": individual, "clip_windows": chosen,
                            "output_dir": str(out), "output_filename": "Timing"}})["job"]
                        return wait_job(base, job["id"])
                    timed(results, f"export {len(chosen)} clips as {label} ({seconds:.0f} s)", export)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"server": str(args.server or "source"), "video": args.video.name,
                                         "results": results}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
