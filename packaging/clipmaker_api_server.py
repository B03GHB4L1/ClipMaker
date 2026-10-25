"""Serve the shared ClipMaker frontend and its local application API."""

from __future__ import annotations

import argparse
import atexit
import json
import mimetypes
import os
import queue
import re
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    log_dir = Path(os.environ.get("CLIPMAKER_DATA_DIR") or Path.cwd())
    log_dir.mkdir(parents=True, exist_ok=True)
    startup_log = (log_dir / "backend-startup.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or startup_log
    sys.stderr = sys.stderr or startup_log


def resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    script_root = Path(__file__).resolve().parent
    return script_root if (script_root / "app").is_dir() else script_root.parent


ROOT = resource_root()
APP_DIR = ROOT / "app"
UI_DIR = ROOT / "ui"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if __package__:
    from .analysis_server import AnalysisServer, run_analysis, watch_process_owner
else:
    from analysis_server import AnalysisServer, run_analysis, watch_process_owner


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix="saving-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            json.dump(value, temporary, indent=2, allow_nan=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


class MatchStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "matches.json"
        self._lock = threading.RLock()

    def create(self, name: str = "Untitled project") -> dict[str, Any]:
        return self.upsert({"id": uuid.uuid4().hex, "project_name": name,
                            "status": "draft", "markers": {}})

    def project_path(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", project_id):
            raise ValueError("Invalid project id")
        return self.data_dir / "projects" / project_id / "project.json"

    def snapshots(self) -> dict:
        with self._lock:
            path = self.data_dir / "filter-snapshots.json"
            if path.exists():
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("Invalid snapshot library; it has not been overwritten.")
                return value
            library = {}
            for project in reversed(self.list()):
                library.update(project.get("filter_snapshots") or {})
            return library

    def update_snapshot(self, name: str, options: dict | None) -> dict:
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("Use a snapshot name between 1 and 100 characters.")
        with self._lock:
            library = self.snapshots()
            if options is None:
                if name not in library:
                    raise ValueError("Snapshot not found")
                atomic_json(self.data_dir / "snapshot-trash" / f"{uuid.uuid4().hex}.json", {name: library.pop(name)})
            else:
                if name not in library and len(library) >= 100:
                    raise ValueError("The snapshot library is full (100 snapshots).")
                library[name] = options
            atomic_json(self.data_dir / "filter-snapshots.json", library)
            return library

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            legacy = []
            if self.path.exists():
                legacy = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(legacy, list):
                    raise ValueError("Saved match history is invalid; it has not been overwritten.")
            projects = {item["id"]: item for item in legacy if isinstance(item, dict) and item.get("id")}
            for path in (self.data_dir / "projects").glob("*/project.json"):
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or value.get("id") != path.parent.name:
                    raise ValueError(f"Invalid saved project: {path.parent.name}")
                projects[value["id"]] = value
            return sorted(projects.values(), key=lambda item: item.get("updated_at", ""), reverse=True)

    def upsert(self, match: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._upsert(match)

    def _upsert(self, match: dict[str, Any]) -> dict[str, Any]:
        project_id = str(match.get("id") or "").strip()
        existing = self.get(project_id) if project_id else None
        if existing and any(
            key in match and match[key] != existing.get(key)
            for key in ("markers", "csv_path", "video_path", "period_videos")
        ):
            # Edited clip windows belong to the source and alignment that built them.
            match = {**match, "preview_windows": [], "preview_range": {}}
        match = {**(existing or {}), **match}
        clean = {
            "id": str(match.get("id") or "").strip(),
            "home_team": str(match.get("home_team") or "").strip(),
            "away_team": str(match.get("away_team") or "").strip(),
            "source_url": str(match.get("source_url") or "").strip(),
            "source": str(match.get("source") or "").strip(),
            "event_count": int(match.get("event_count") or 0),
            "home_score": int(match.get("home_score") or 0),
            "away_score": int(match.get("away_score") or 0),
            "score_status": str(match.get("score_status") or "FT").strip(),
            "video_name": str(match.get("video_name") or "").strip(),
            "video_path": str(match.get("video_path") or "").strip(),
            "csv_path": str(match.get("csv_path") or "").strip(),
            "markers": match.get("markers") if isinstance(match.get("markers"), dict) else {},
            "status": str(match.get("status") or "in_progress"),
            "schema_version": 1,
            "project_name": str(match.get("project_name") or "").strip()[:120],
            "created_at": str(match.get("created_at") or datetime.now(timezone.utc).isoformat()),
            "filter_settings": match.get("filter_settings") if isinstance(match.get("filter_settings"), dict) else {},
            "preview_windows": match.get("preview_windows") if isinstance(match.get("preview_windows"), list) else [],
            "preview_range": match.get("preview_range") if isinstance(match.get("preview_range"), dict) else {},
            "period_videos": match.get("period_videos") if isinstance(match.get("period_videos"), dict) else {},
            "had_extra_time": bool(match.get("had_extra_time") or (match.get("markers") or {}).get("ET1") or (match.get("markers") or {}).get("ET2")),
            "had_penalties": bool(match.get("had_penalties") or (match.get("markers") or {}).get("PEN")),
            "filter_snapshots": match.get("filter_snapshots") if isinstance(match.get("filter_snapshots"), dict) else {},
            "export_history": match.get("export_history") if isinstance(match.get("export_history"), list) else [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not clean["id"]:
            parts = [clean["home_team"], clean["away_team"]]
            clean["id"] = "-vs-".join(part.lower().replace(" ", "-") for part in parts if part)
        if not clean["id"]:
            raise ValueError("A match id or team names are required")

        path = self.project_path(clean["id"])
        if not clean["project_name"]:
            clean["project_name"] = f"{clean['home_team']} vs {clean['away_team']}" if clean["home_team"] else "Untitled project"
        for period, clock in clean["markers"].items():
            if period not in {"1H", "2H", "ET1", "ET2", "PEN"} or not re.fullmatch(r"\d{1,3}:[0-5]\d:[0-5]\d", str(clock)):
                raise ValueError("Kickoff markers must use HH:MM:SS with minutes and seconds below 60.")
        atomic_json(path, clean)
        return clean

    def get(self, match_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item.get("id") == match_id), None)


FILTER_QUALIFIERS = [
    ("successful_only", "outcomeType", "Successful", "Outcome & movement", "Successful"),
    ("unsuccessful_only", "outcomeType", "Unsuccessful", "Outcome & movement", "Unsuccessful"),
    ("progressive_only", "__progressive__", "Progressive actions", "Outcome & movement", None),
    ("fast_break_only", "is_fast_break", "Fast break", "Outcome & movement", None),
    ("touch_in_box_only", "is_touch_in_box", "Touch in box", "Outcome & movement", None),
    ("key_passes_only", "is_key_pass", "Key passes", "Passing", None),
    ("crosses_only", "is_cross", "Crosses", "Passing", None),
    ("long_balls_only", "is_long_ball", "Long balls", "Passing", None),
    ("switches_only", "is_switch_of_play", "Switches of play", "Passing", None),
    ("diagonals_only", "is_diagonal_long_ball", "Diagonals", "Passing", None),
    ("through_balls_only", "is_through_ball", "Through balls", "Passing", None),
    ("corners_only", "is_corner", "Corners", "Passing", None),
    ("freekicks_only", "is_freekick", "Free kicks", "Passing", None),
    ("headers_only", "is_header", "Headers", "Passing", None),
    ("throw_ins_only", "is_throw_in", "Throw ins", "Passing", None),
    ("goal_kicks_only", "is_goal_kick", "Goal kicks", "Passing", None),
    ("keeper_throws_only", "is_keeper_throw", "Keeper throws", "Passing", None),
    ("gk_hoofs_only", "is_gk_hoof", "Goalkeeper hoofs", "Passing", None),
    ("pull_backs_only", "is_pull_back", "Pull backs", "Passing", None),
    ("lay_offs_only", "is_lay_off", "Lay offs", "Passing", None),
    ("flick_ons_only", "is_flick_on", "Flick ons", "Passing", None),
    ("launches_only", "is_launch", "Launches", "Passing", None),
    ("assists_only", "is_assist", "Assists", "Passing", None),
    ("attacking_passes_only", "is_attacking_pass", "Attacking passes", "Passing", None),
    ("box_entry_pass_only", "is_box_entry_pass", "Box entry passes", "Passing", None),
    ("deep_completion_only", "is_deep_completion", "Deep completions", "Passing", None),
    ("final_third_entry_pass_only", "is_final_third_entry_pass", "Final-third entry passes", "Passing", None),
    ("big_chances_only", "is_big_chance_shot", "Big chances", "Shots", None),
    ("own_goals_only", "is_own_goal", "Own goals", "Shots", None),
    ("penalties_only", "is_penalty", "Penalties", "Shots", None),
    ("volleys_only", "is_volley", "Volleys", "Shots", None),
    ("chipped_only", "is_chipped", "Chipped shots", "Shots", None),
    ("direct_from_corner_only", "is_direct_from_corner", "Direct from corner", "Shots", None),
    ("left_foot_only", "is_left_foot", "Left foot", "Shots", None),
    ("right_foot_only", "is_right_foot", "Right foot", "Shots", None),
    ("scrambles_only", "is_scramble", "Scrambles", "Shots", None),
    ("corner_situations_only", "is_corner_situation", "Corner situations", "Shots", None),
    ("shot_strong_only", "is_shot_strong", "Strong shots", "Shots", None),
    ("shot_weak_only", "is_shot_weak", "Weak shots", "Shots", None),
    ("individual_play_only", "is_individual_play", "Individual play", "Shots", None),
    ("follows_dribble_only", "is_follows_dribble", "Follows dribble", "Shots", None),
    ("one_on_one_only", "is_1on1", "One on one", "Shots", None),
    ("deflected_only", "is_deflected", "Deflected", "Shots", None),
    ("woodwork_only", "is_hit_woodwork", "Hit woodwork", "Shots", None),
    ("back_heel_only", "is_back_heel", "Back heel", "Shots", None),
    ("big_chances_created_only", "is_big_chance", "Big chances created", "Assists", None),
    ("assist_throughball_only", "is_assist_throughball", "Through-ball assists", "Assists", None),
    ("assist_cross_only", "is_assist_cross", "Cross assists", "Assists", None),
    ("assist_corner_only", "is_assist_corner", "Corner assists", "Assists", None),
    ("assist_freekick_only", "is_assist_freekick", "Free-kick assists", "Assists", None),
    ("intentional_assists_only", "is_intentional_assist", "Intentional assists", "Assists", None),
    ("gk_saves_only", "is_gk_save", "Goalkeeper saves", "Goalkeeping", None),
    ("yellow_cards_only", "is_yellow_card", "Yellow cards", "Discipline", None),
    ("red_cards_only", "is_red_card", "Red cards", "Discipline", None),
    ("second_yellow_only", "is_second_yellow", "Second yellows", "Discipline", None),
    ("nutmegs_only", "is_nutmeg", "Nutmegs", "Dribbling & carrying", None),
    ("success_in_box_only", "is_success_in_box", "Successful in box", "Dribbling & carrying", None),
    ("box_entry_carry_only", "is_box_entry_carry", "Box-entry carries", "Dribbling & carrying", None),
    ("final_third_entry_carry_only", "is_final_third_entry_carry", "Final-third entry carries", "Dribbling & carrying", None),
    ("last_line_only", "is_last_line", "Last-line actions", "Defending & errors", None),
    ("forced_out_only", "is_forced_out", "Forced out", "Defending & errors", None),
    ("blocked_cross_only", "is_blocked_cross", "Blocked crosses", "Defending & errors", None),
    ("errors_to_shot_only", "is_error_led_to_shot", "Errors leading to shot", "Defending & errors", None),
    ("errors_to_goal_only", "is_error_led_to_goal", "Errors leading to goal", "Defending & errors", None),
]

FILTER_FLAGS = {definition[0] for definition in FILTER_QUALIFIERS} | {
    "shots_and_key_passes_only"
}


def choose_video_file() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(
            parent=root,
            title="Choose full match footage",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
    finally:
        root.destroy()
    return Path(selected).resolve() if selected else None


def choose_output_folder(initial_dir: str = "") -> Path | None:
    if sys.platform == "darwin":
        import subprocess
        selected = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose VizorPlay export folder")'], capture_output=True, text=True)
        if selected.returncode:
            if "-128" in selected.stderr:
                return None
            raise ValueError("The macOS folder picker is unavailable. Enter an export folder path instead.")
        return Path(selected.stdout.strip()).resolve()
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    options: dict[str, Any] = {"parent": root, "title": "Choose export folder"}
    if initial_dir and Path(initial_dir).is_dir():
        options["initialdir"] = initial_dir
    try:
        selected = filedialog.askdirectory(**options)
    finally:
        root.destroy()
    return Path(selected).resolve() if selected else None


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancellations: dict[str, threading.Event] = {}
        self._reserved_outputs: set[str] = set()
        self._workers: dict[str, threading.Thread] = {}
        self._closing = False
        self._lock = threading.Lock()

    def start(self, config: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        config = dict(config)
        if not config["dry_run"]:
            output = Path(config["output_dir"]) / config["output_filename"]
            if config.get("individual_clips"):
                config["output_dir"] = str(output.parent / f"clips-{job_id}")
            else:
                with self._lock:
                    if output.exists() or str(output.resolve()) in self._reserved_outputs:
                        config["output_filename"] = f"{output.stem}-{job_id}{output.suffix}"
                    self._reserved_outputs.add(str((output.parent / config["output_filename"]).resolve()))
        job = {
            "id": job_id,
            "status": "queued",
            "dry_run": bool(config["dry_run"]),
            "logs": [],
            "progress": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": config["output_dir"],
            "output_filename": config["output_filename"],
        }
        cancellation = threading.Event()
        worker = threading.Thread(target=self._run, args=(job_id, config, cancellation), daemon=True)
        with self._lock:
            if self._closing:
                if not config["dry_run"] and not config.get("individual_clips"):
                    self._reserved_outputs.discard(str((Path(config["output_dir"]) / config["output_filename"]).resolve()))
                raise ValueError("The local engine is shutting down")
            self._jobs[job_id] = job
            self._cancellations[job_id] = cancellation
            worker.start()
            self._workers[job_id] = worker
        return dict(job)

    def close(self, timeout: float = 8) -> bool:
        with self._lock:
            self._closing = True
            for cancellation in self._cancellations.values():
                cancellation.set()
            workers = list(self._workers.values())
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        return all(not worker.is_alive() for worker in workers)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return json.loads(json.dumps(job)) if job else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            cancellation = self._cancellations.get(job_id)
            job = self._jobs.get(job_id)
            if not cancellation or not job:
                return False
            cancellation.set()
            if job["status"] == "queued":
                job["status"] = "cancelled"
            return True

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(values)

    def _append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["logs"].append(message)

    def _run(self, job_id: str, config: dict[str, Any], cancellation: threading.Event) -> None:
        try:
            self._execute(job_id, config, cancellation)
        except Exception as error:
            self._append_log(job_id, f"Export worker stopped: {error}")
            self._update(job_id, status="failed", files=[], finished_at=datetime.now(timezone.utc).isoformat())
        finally:
            self._cleanup_temporary_data(config)
            if not config["dry_run"] and not config.get("individual_clips"):
                output = str((Path(config["output_dir"]) / config["output_filename"]).resolve())
                with self._lock:
                    self._reserved_outputs.discard(output)

    def _execute(self, job_id: str, config: dict[str, Any], cancellation: threading.Event) -> None:
        try:
            from clipmaker_core import run_clip_maker
        except Exception as error:
            self._append_log(job_id, f"Could not start the VizorPlay engine: {error}")
            self._update(
                job_id,
                status="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            return

        logs: queue.Queue[dict[str, Any]] = queue.Queue()
        progress: queue.Queue[dict[str, Any]] = queue.Queue()
        self._update(job_id, status="running")

        def execute_engine() -> None:
            try:
                run_clip_maker(config, logs, progress, cancellation)
            except Exception as error:
                logs.put({"type": "error", "msg": f"VizorPlay engine stopped: {error}"})

        engine = threading.Thread(
            target=execute_engine,
            daemon=True,
        )
        engine.start()
        terminal_status = None
        while engine.is_alive() or not logs.empty() or not progress.empty():
            while not logs.empty():
                message = logs.get_nowait()
                if message.get("msg"):
                    self._append_log(job_id, str(message["msg"]))
                if message.get("type") == "done":
                    terminal_status = "complete"
                elif message.get("type") == "error":
                    terminal_status = "failed"
                elif message.get("type") == "cancelled":
                    terminal_status = "cancelled"
            while not progress.empty():
                update = progress.get_nowait()
                if update.get("error"):
                    self._append_log(job_id, str(update["error"]))
                    terminal_status = "failed"
                self._update(job_id, progress=update)
            time.sleep(0.05)
        engine.join()
        files = []
        if terminal_status == "complete" and not config["dry_run"]:
            directory = Path(config["output_dir"])
            outputs = sorted(directory.glob("*")) if config.get("individual_clips") else [directory / config["output_filename"]]
            files = [{"path": str(path), "name": path.name, "size": path.stat().st_size} for path in outputs if path.is_file() and path.stat().st_size > 0 and path.suffix.lower() in {".mp4", ".mov", ".mkv"}]
            if not files:
                terminal_status = "failed"
                self._append_log(job_id, "The export finished without a readable output file.")
        if terminal_status is None and not cancellation.is_set():
            terminal_status = "failed"
            self._append_log(job_id, "The engine stopped without reporting completion.")
        self._update(
            job_id,
            status=terminal_status or "cancelled",
            finished_at=datetime.now(timezone.utc).isoformat(),
            files=files,
        )

    @staticmethod
    def _cleanup_temporary_data(config: dict[str, Any]) -> None:
        temporary_path = str(config.get("_temporary_data_file") or "")
        if not temporary_path:
            return
        try:
            Path(temporary_path).unlink(missing_ok=True)
        except OSError:
            pass


def prepare_filtered_data(
    csv_path: str,
    match_id: str,
    options: dict[str, Any],
    data_dir: Path,
) -> tuple[str, str | None]:
    team_filter = str(options.get("team_filter") or "").strip()
    player_filters = options.get("player_filters")
    players = (
        [str(value).strip() for value in player_filters if str(value).strip()][:100]
        if isinstance(player_filters, list)
        else []
    )
    if not team_filter and not players:
        return csv_path, None

    import pandas as pd

    frame = pd.read_csv(csv_path, low_memory=False)
    if team_filter and "team" in frame.columns:
        frame = frame[frame["team"].astype(str) == team_filter]
    if players and "playerName" in frame.columns:
        frame = frame[frame["playerName"].astype(str).isin(players)]
    if frame.empty:
        raise ValueError("No events match the selected team and players.")

    working_dir = data_dir / "job-data"
    working_dir.mkdir(parents=True, exist_ok=True)
    safe_match_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in match_id
    ).strip("-") or "match"
    path = working_dir / f"{safe_match_id}-{uuid.uuid4().hex[:10]}.csv"
    frame.to_csv(path, index=False)
    return str(path), str(path)


def compute_clip_windows(config: dict[str, Any]) -> list[dict[str, Any]]:
    import pandas as pd

    from clipmaker_core import (
        _clock_seconds_for_period,
        apply_filters,
        apply_timeline_corrections,
        assign_periods,
        match_clock_to_video_time,
        merge_overlapping_windows,
        normalise_timeline_corrections,
        read_csv_safe,
        resolve_period_starts_for_video,
        safe_clock_int,
        to_seconds,
    )

    frame = read_csv_safe(config["data_file"])
    for column in ("minute", "second", "type"):
        if column not in frame.columns:
            raise ValueError(f"CSV missing column: '{column}'")
    frame = assign_periods(
        frame,
        config.get("period_column") or None,
        config.get("fallback_row"),
    )
    anchor_frame = frame.copy()
    half_filter = config.get("half_filter", "Both halves")
    if half_filter == "1st half only":
        frame = frame[frame["resolved_period"] == 1]
    elif half_filter == "2nd half only":
        frame = frame[frame["resolved_period"] == 2]
    frame, _ = apply_filters(frame, config)

    starts = {}
    for period, key in enumerate(
        ("half1_time", "half2_time", "half3_time", "half4_time", "half5_time"),
        1,
    ):
        value = str(config.get(key) or "").strip()
        if value:
            starts[period] = to_seconds(value)
    starts = resolve_period_starts_for_video(anchor_frame, starts)
    offsets = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0), 5: (120, 0)}
    corrections = normalise_timeline_corrections(config)

    frame = frame.copy()
    frame["_clip_order"] = range(len(frame))
    timestamps = []
    for _, row in frame.iterrows():
        minute = safe_clock_int(row.get("minute"))
        second = safe_clock_int(row.get("second"))
        period = safe_clock_int(row.get("resolved_period"))
        if minute is None or second is None or period is None:
            timestamps.append(None)
            continue
        try:
            timestamp = match_clock_to_video_time(
                minute,
                second,
                period,
                starts,
                offsets,
            )
            timestamp = apply_timeline_corrections(
                timestamp,
                _clock_seconds_for_period(minute, second, period),
                period,
                corrections,
            )
            timestamps.append(timestamp)
        except (TypeError, ValueError):
            timestamps.append(None)
    frame["video_timestamp"] = timestamps
    frame["_match_minute"] = pd.to_numeric(frame["minute"], errors="coerce")
    frame["_match_second"] = pd.to_numeric(frame["second"], errors="coerce")
    frame = (
        frame.dropna(subset=["video_timestamp"])
        .sort_values(
            ["resolved_period", "_match_minute", "_match_second", "_clip_order"],
            kind="mergesort",
        )
        .drop(
            columns=["_match_minute", "_match_second", "_clip_order"],
            errors="ignore",
        )
    )

    raw_windows = []
    for _, row in frame.iterrows():
        minute = safe_clock_int(row.get("minute"))
        second = safe_clock_int(row.get("second"))
        period = safe_clock_int(row.get("resolved_period"))
        if minute is None or second is None or period is None:
            continue
        player = str(row.get("playerName") or "").strip()
        player = "" if player.lower() == "nan" else player
        label = f"{f'{player} - ' if player else ''}{row['type']} @ {minute}:{second:02d} (P{period})"
        timestamp = float(row["video_timestamp"])
        raw_windows.append(
            (
                timestamp - config["before_buffer"],
                timestamp + config["after_buffer"],
                label,
                period,
            )
        )
    merged = merge_overlapping_windows(raw_windows, config["min_gap"])
    return [
        {
            "id": index,
            "start": max(0.0, float(start)),
            "end": float(end),
            "label": str(label),
            "period": int(period),
        }
        for index, (start, end, label, period) in enumerate(merged, 1)
        if float(end) > max(0.0, float(start))
    ]


def render_preview_clip(
    video_path: str,
    start: float,
    end: float,
    output_dir: Path,
    crf: int,
    encoder_preset: str,
    audio_bitrate: str,
) -> Path:
    import shutil
    import subprocess

    source = Path(video_path).resolve()
    if not source.is_file():
        raise ValueError("The saved match video is no longer available.")
    import math
    duration = end - start
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or duration <= 0 or duration > 600:
        raise ValueError("Preview windows must be between 0 and 10 minutes long.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as error:
            raise ValueError("FFmpeg is required to render clip previews.") from error
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"preview-{uuid.uuid4().hex[:12]}.mp4"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start),
        "-i",
        str(source),
        "-t",
        str(duration),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        encoder_preset,
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(output),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise ValueError(f"Could not render preview: {(result.stderr or '')[-500:]}")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def video_for_period(match: dict[str, Any], period: int) -> str:
    if period not in {1, 2, 3, 4, 5}:
        raise ValueError("Choose a valid match period.")
    videos = match.get("period_videos") or {}
    if period > 1:
        key = {2: "2H", 3: "ET1", 4: "ET2", 5: "PEN"}[period]
        return str(videos.get(key) or (videos.get("ET1") if period == 4 else None)
                   or videos.get("2H") or match.get("video_path") or "")
    return str(match.get("video_path") or "")


def build_clip_config(match: dict[str, Any], options: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    csv_path = str(match.get("csv_path") or "").strip()
    if not csv_path or not Path(csv_path).is_file():
        raise ValueError("This match has no saved event CSV. Scrape it again before filtering.")
    markers = match.get("markers") if isinstance(match.get("markers"), dict) else {}
    filter_types = options.get("filter_types") if isinstance(options.get("filter_types"), list) else []
    clean_types = [str(value) for value in filter_types if str(value).strip()][:50]
    half_filter = str(options.get("half_filter") or "Both halves")
    if half_filter not in {"1st half only", "2nd half only", "Both halves"}:
        raise ValueError("Choose first half, second half, or both halves.")
    if half_filter != "2nd half only" and not str(markers.get("1H") or "").strip():
        raise ValueError("Set the first-half kick-off marker before building a clip plan.")
    if half_filter != "1st half only" and not str(markers.get("2H") or "").strip():
        raise ValueError("Set the second-half kick-off marker before building a clip plan.")
    qualifier_logic = str(options.get("qualifier_logic") or "any").strip().lower()
    if qualifier_logic not in {"any", "all"}:
        raise ValueError("Qualifier logic must be either any or all.")
    output_format = str(options.get("output_format") or ".mp4").strip().lower()
    if not output_format.startswith("."):
        output_format = f".{output_format}"
    if output_format not in {".mp4", ".mov", ".mkv"}:
        raise ValueError("Export format must be MP4, MOV, or MKV.")
    encoder_preset = str(options.get("encoder_preset") or "veryfast").strip()
    if encoder_preset not in {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
    }:
        raise ValueError("Choose a supported encoder speed.")
    audio_bitrate = str(options.get("audio_bitrate") or "128k").strip()
    if audio_bitrate not in {"96k", "128k", "160k", "192k", "256k"}:
        raise ValueError("Choose a supported audio bitrate.")
    requested_output_dir = str(options.get("output_dir") or "").strip().strip('"')
    output_dir = (
        Path(requested_output_dir).expanduser().resolve()
        if requested_output_dir
        else (data_dir / "projects" / str(match.get("id") or "match") / "exports").resolve()
    )
    clip_windows = []
    if "clip_windows" in options:
        import math
        if not isinstance(options["clip_windows"], list) or len(options["clip_windows"]) > 2000:
            raise ValueError("Supply at most 2000 valid clip windows.")
        if not options["clip_windows"] and not options.get("dry_run", True):
            raise ValueError("There are no clips selected for export.")
        for item in options["clip_windows"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid clip window.")
            try:
                start = float(item.get("start", 0))
                end = float(item.get("end", 0))
                period = int(float(item.get("period", 1)))
            except (TypeError, ValueError):
                raise ValueError("Invalid clip window.")
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or period not in {1, 2, 3, 4, 5}:
                raise ValueError("Clip end must follow a non-negative start, with a valid period.")
            clip_windows.append(
                {
                    "start": start,
                    "end": end,
                    "label": str(item.get("label") or "Edited clip"),
                    "period": period,
                }
            )

    config = {
        "video_file": str(match.get("video_path") or ""),
        "video2_file": str((match.get("period_videos") or {}).get("2H") or match.get("video_path") or ""),
        "video3_file": str((match.get("period_videos") or {}).get("ET1", "")),
        "video4_file": str((match.get("period_videos") or {}).get("ET2") or (match.get("period_videos") or {}).get("ET1", "")),
        "video5_file": str((match.get("period_videos") or {}).get("PEN", "")),
        "split_video": bool(any((match.get("period_videos") or {}).values())),
        "extra_time_video_mode": "single",
        "data_file": csv_path,
        "_temporary_data_file": None,
        "half1_time": str(markers.get("1H") or ""),
        "half2_time": str(markers.get("2H") or ""),
        "half3_time": str(markers.get("ET1") or ""),
        "half4_time": str(markers.get("ET2") or ""),
        "half5_time": str(markers.get("PEN") or ""),
        "period_column": "period",
        "fallback_row": None,
        "before_buffer": max(0, min(60, int(options.get("before_buffer", 5)))),
        "after_buffer": max(0, min(60, int(options.get("after_buffer", 8)))),
        "min_gap": max(0, min(60, int(options.get("min_gap", 6)))),
        "output_dir": str(output_dir),
        "output_filename": Path(str(options.get("output_filename") or "Highlights")).stem + output_format,
        "output_format": output_format,
        "video_crf": max(16, min(30, int(options.get("video_crf", 20)))),
        "encoder_preset": encoder_preset,
        "audio_bitrate": audio_bitrate,
        "timeline_corrections": (
            options.get("timeline_corrections")
            if isinstance(options.get("timeline_corrections"), list)
            else []
        ),
        "clip_windows": clip_windows,
        "individual_clips": bool(options.get("individual_clips", False)),
        "dry_run": bool(options.get("dry_run", True)),
        "half_filter": half_filter,
        "filter_types": clean_types,
        "qualifier_logic": qualifier_logic,
        "pitch_zone_filter": options.get("pitch_zone_filter") or None,
        "depth_zone_filter": options.get("depth_zone_filter") or None,
        "xt_min": float(options.get("xt_min", 0) or 0),
        "top_n": int(options["top_n"]) if options.get("top_n") else None,
        "minute_min": float(options["minute_min"]) if options.get("minute_min") not in {None, ""} else None,
        "minute_max": float(options["minute_max"]) if options.get("minute_max") not in {None, ""} else None,
    }
    for flag in FILTER_FLAGS:
        config[flag] = bool(options.get(flag, False))
    if not config["dry_run"] and not Path(config["video_file"]).is_file():
        raise ValueError("A native video path is required before rendering clips.")
    config["data_file"], config["_temporary_data_file"] = prepare_filtered_data(
        csv_path, str(match.get("id") or "match"), options, data_dir,
    )
    return config


def detect_source(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("Paste an HTTP or HTTPS match URL")
    if host == "scoresway.com" or host.endswith(".scoresway.com"):
        return "scoresway"
    if host == "whoscored.com" or host.endswith(".whoscored.com"):
        return "whoscored"
    raise ValueError("Paste a Scoresway or WhoScored match URL")


def json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and (value != value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def normalize_period(value: Any) -> int | str:
    labels = {
        "firsthalf": 1,
        "secondhalf": 2,
        "firstperiodofextratime": 3,
        "secondperiodofextratime": 4,
        "extratimefirsthalf": 3,
        "extratimesecondhalf": 4,
        "penaltyshootout": 5,
        "penalties": 5,
    }
    text = str(value or "").strip()
    compact = "".join(character for character in text.lower() if character.isalnum())
    if compact in labels:
        return labels[compact]
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return text


def infer_score(frame: Any, home_team: str, away_team: str) -> tuple[int, int]:
    scores = {home_team: 0, away_team: 0}
    if "type" not in frame.columns or "team" not in frame.columns:
        return 0, 0
    for _, event in frame.iterrows():
        if str(event.get("type") or "").strip().lower() != "goal":
            continue
        if normalize_period(event.get("period")) == 5:
            continue
        team = str(event.get("team") or "").strip()
        own_goal = str(event.get("is_own_goal") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if own_goal:
            team = away_team if team == home_team else home_team if team == away_team else team
        if team in scores:
            scores[team] += 1
    return scores[home_team], scores[away_team]


def load_event_rows(csv_path: str) -> dict[str, Any]:
    import pandas as pd

    path = Path(csv_path).resolve()
    if not path.is_file():
        raise ValueError("The saved event table is no longer available.")
    frame = pd.read_csv(path, low_memory=False)
    preferred_columns = ["minute", "second", "playerName", "type", "team", "period", "xT"]
    columns = [column for column in preferred_columns if column in frame.columns]
    rows = []
    for row in frame[columns].head(5000).to_dict(orient="records"):
        clean = {key: json_value(value) for key, value in row.items()}
        if "period" in clean:
            clean["period"] = normalize_period(clean["period"])
        rows.append(clean)
    return {"events": rows, "event_count": len(frame), "truncated": len(frame) > 5000}


def load_filter_options(match: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    csv_path = Path(str(match.get("csv_path") or "")).resolve()
    if not csv_path.is_file():
        raise ValueError("This match has no saved event table. Scrape it again first.")
    frame = pd.read_csv(csv_path, low_memory=False)

    action_types = []
    if "type" in frame.columns:
        action_types = sorted(
            {str(value).strip() for value in frame["type"].dropna() if str(value).strip()},
            key=str.casefold,
        )

    team_players: dict[str, list[str]] = {}
    if "team" in frame.columns:
        teams = sorted(
            {str(value).strip() for value in frame["team"].dropna() if str(value).strip()},
            key=str.casefold,
        )
        for team in teams:
            if "playerName" not in frame.columns:
                team_players[team] = []
                continue
            team_rows = frame[frame["team"].astype(str) == team]
            team_players[team] = sorted(
                {
                    str(value).strip()
                    for value in team_rows["playerName"].dropna()
                    if str(value).strip()
                },
                key=str.casefold,
            )

    qualifiers = []
    for flag, column, label, group, expected in FILTER_QUALIFIERS:
        count = 0
        if column == "__progressive__":
            progressive = pd.Series(False, index=frame.index)
            for progressive_column in ("prog_pass", "prog_carry"):
                if progressive_column in frame.columns:
                    progressive |= (
                        pd.to_numeric(frame[progressive_column], errors="coerce")
                        .fillna(0)
                        .gt(0)
                    )
            count = int(progressive.sum())
        elif column in frame.columns:
            if expected is not None:
                count = int(frame[column].astype(str).eq(expected).sum())
            else:
                count = int(
                    frame[column]
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .isin({"true", "1", "yes"})
                    .sum()
                )
        qualifiers.append(
            {
                "flag": flag,
                "label": label,
                "group": group,
                "available": count > 0,
                "count": count,
            }
        )

    return {
        "match": match,
        "action_types": action_types,
        "team_players": team_players,
        "qualifiers": qualifiers,
        "has_xt": "xT" in frame.columns,
        "event_count": len(frame),
    }


def scrape_match(url: str, output_dir: Path) -> dict[str, Any]:
    from scoresway_scraper import scrape_scoresway
    from whoscored_scraper import save_scraped_match_csv, scrape_whoscored

    source = detect_source(url)
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    scraper = scrape_scoresway if source == "scoresway" else scrape_whoscored
    scraper(url, messages, str(APP_DIR))

    result = None
    errors = []
    while not messages.empty():
        message = messages.get_nowait()
        if message.get("type") == "data":
            result = message
        elif message.get("type") == "error":
            errors.append(str(message.get("msg") or "Unknown scraper error"))
    if result is None:
        raise RuntimeError(errors[-1] if errors else "The scraper returned no match data")

    frame = result["df"]
    home_team = str(result.get("home_team") or "")
    away_team = str(result.get("away_team") or "")
    home_score, away_score = infer_score(frame, home_team, away_team)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = save_scraped_match_csv(
        frame,
        result.get("home_team", ""),
        result.get("away_team", ""),
        str(output_dir),
        source=result.get("source", source),
    )
    preferred_columns = ["minute", "second", "playerName", "type", "team", "period", "xT"]
    columns = [column for column in preferred_columns if column in frame.columns]
    preview = [
        {key: json_value(value) for key, value in row.items()}
        for row in frame[columns].head(200).to_dict(orient="records")
    ]
    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "score_status": "FT",
        "source": result.get("source", source),
        "source_url": url,
        "event_count": len(frame),
        "csv_path": csv_path,
        "events": preview,
    }


class ClipMakerHandler(SimpleHTTPRequestHandler):
    server_version = "VizorPlay/1.0"

    @property
    def store(self) -> MatchStore:
        return self.server.match_store  # type: ignore[attr-defined]

    @property
    def match_data_dir(self) -> Path:
        return self.server.match_data_dir  # type: ignore[attr-defined]

    @property
    def jobs(self) -> JobManager:
        return self.server.jobs  # type: ignore[attr-defined]

    @property
    def media_files(self) -> dict[str, Path]:
        return self.server.media_files  # type: ignore[attr-defined]

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        relative = parsed.lstrip("/") or "index.html"
        candidate = (UI_DIR / relative).resolve()
        if UI_DIR.resolve() not in candidate.parents and candidate != UI_DIR.resolve():
            return str(UI_DIR / "index.html")
        return str(candidate)

    def send_json(self, status: HTTPStatus, payload: Any) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("A JSON request body is required")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("The request body must be a JSON object")
        return value

    def validate_local_request(self) -> None:
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") not in {expected, f"localhost:{self.server.server_port}"}:
            raise ValueError("VizorPlay only accepts requests to its local address.")
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{expected}", f"http://localhost:{self.server.server_port}"}:
            raise ValueError("Requests from other websites are not allowed.")

    def receive_upload(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        project_id = query.get("project", [""])[0]
        project = self.store.get(project_id)
        if project is None:
            raise ValueError("Open a project before importing files.")
        filename = Path(unquote(self.headers.get("X-File-Name", ""))).name
        suffix = Path(filename).suffix.lower()
        is_csv = suffix == ".csv"
        if suffix not in {".csv", ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"}:
            raise ValueError("Choose a match CSV or a supported video file.")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > (50_000_000 if is_csv else 100_000_000_000):
            raise ValueError("Invalid file size (CSV limit 50 MB; video limit 100 GB).")
        folder = self.store.project_path(project_id).parent / "imports"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{uuid.uuid4().hex}{suffix}"
        temporary = destination.with_suffix(".part")
        try:
            with temporary.open("wb") as output:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("File import was interrupted; no partial file was saved.")
                    output.write(chunk)
                    remaining -= len(chunk)
            if is_csv:
                import pandas as pd
                from clipmaker_core import read_csv_safe
                frame = read_csv_safe(str(temporary))
                missing = {"minute", "second", "type"} - set(frame.columns)
                if missing or frame.empty:
                    raise ValueError("Match CSV needs event rows and minute, second, type columns.")
                teams = frame["team"].dropna().astype(str).unique().tolist() if "team" in frame else []
                home = str(frame["homeTeam"].dropna().iloc[0]) if "homeTeam" in frame and frame["homeTeam"].notna().any() else (teams[0] if teams else "Home")
                away = str(frame["awayTeam"].dropna().iloc[0]) if "awayTeam" in frame and frame["awayTeam"].notna().any() else (teams[1] if len(teams) > 1 else "Away")
                if "period" in frame:
                    frame["period"] = frame["period"].map(normalize_period)
                home_score, away_score = infer_score(frame, home, away)
                frame.to_csv(temporary, index=False)
            os.replace(temporary, destination)
            if is_csv:
                project = self.store.upsert({"id": project_id, "csv_path": str(destination),
                    "home_team": home, "away_team": away, "home_score": home_score,
                    "away_score": away_score, "event_count": len(frame), "source": "csv", "status": "in_progress"})
                self.send_json(HTTPStatus.OK, {"match": {**project, **load_event_rows(str(destination))}})
            else:
                token = uuid.uuid4().hex
                self.media_files[token] = destination
                self.send_json(HTTPStatus.OK, {"file": {"name": filename, "path": str(destination), "size": length, "url": f"/api/media/{token}"}})
        finally:
            if temporary.exists():
                temporary.unlink()

    def send_media(self, token: str) -> None:
        media_path = self.media_files.get(token)
        if media_path is None or not media_path.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Video is no longer available"})
            return
        size = media_path.stat().st_size
        start = 0
        end = size - 1
        range_header = self.headers.get("Range", "")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            valid = bool(match and size and any(match.groups()))
            if valid:
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                    valid = start < size and end >= start
                else:
                    count = int(last)
                    valid = count > 0
                    start = max(0, size - count)
            if not valid:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = max(0, end - start + 1)
        status = HTTPStatus.PARTIAL_CONTENT if range_header else HTTPStatus.OK
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(media_path.name)[0] or "video/mp4")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with media_path.open("rb") as media:
            media.seek(start)
            remaining = length
            while remaining:
                chunk = media.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    break
                remaining -= len(chunk)

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.validate_local_request()
            self.handle_get()
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except OSError as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def handle_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/snapshots":
            self.send_json(HTTPStatus.OK, {"snapshots": self.store.snapshots()})
            return
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "version": "1.0.0", "pid": os.getpid(), "parent_pid": os.getppid(),
                "desktop_owner_pid": getattr(self.server, "desktop_owner_pid", None)})
            return
        if path == "/api/matches":
            self.send_json(HTTPStatus.OK, {"matches": self.store.list()})
            return
        if path == "/api/projects":
            self.send_json(HTTPStatus.OK, {"projects": self.store.list(), "directory": str(self.store.data_dir / "projects")})
            return
        if path.startswith("/api/projects/"):
            project = self.store.get(path.rsplit("/", 1)[-1])
            self.send_json(HTTPStatus.OK if project else HTTPStatus.NOT_FOUND, {"project": project} if project else {"error": "Project not found"})
            return
        if path.startswith("/api/media/"):
            self.send_media(path.rsplit("/", 1)[-1])
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            job = self.jobs.get(job_id)
            if job is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown clip job"})
            else:
                for file in job.get("files", []):
                    token = uuid.uuid5(uuid.NAMESPACE_URL, file["path"]).hex
                    self.media_files[token] = Path(file["path"])
                    file["url"] = f"/api/media/{token}"
                self.send_json(HTTPStatus.OK, {"job": job})
            return
        if path.startswith("/api/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API endpoint"})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            self.validate_local_request()
            if path == "/api/files/upload":
                self.receive_upload()
                return
            body = self.read_json()
            if path in {"/api/snapshots", "/api/snapshots/delete"}:
                options = body.get("options")
                if path == "/api/snapshots" and not isinstance(options, dict):
                    raise ValueError("Snapshot options must be an object.")
                self.send_json(HTTPStatus.OK, {"snapshots": self.store.update_snapshot(str(body.get("name") or ""), options if path == "/api/snapshots" else None)})
                return
            if path == "/api/shutdown":
                self.send_json(HTTPStatus.OK, {"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "/api/projects":
                self.send_json(HTTPStatus.CREATED, {"project": self.store.create(str(body.get("name") or "Untitled project"))})
                return
            if path == "/api/analysis":
                project = self.store.get(str(body.get("project_id") or ""))
                if not project or not project.get("csv_path") or not Path(project["csv_path"]).is_file():
                    raise ValueError("Scrape or import a match before opening an analytical workspace.")
                view = str(body.get("view") or "analyst")
                if view not in {"analyst", "tactical"}:
                    raise ValueError("Unknown analytical view")
                port = self.server.analysis.start()
                self.send_json(HTTPStatus.OK, {"url": f"http://127.0.0.1:{port}/?project={project['id']}&view={view}&embed=true"})
                return
            if path.startswith("/api/projects/"):
                project_id = path.rsplit("/", 1)[-1]
                if self.store.get(project_id) is None:
                    raise ValueError("Project not found")
                saved = self.store.upsert({**body, "id": project_id})
                self.send_json(HTTPStatus.OK, {"project": saved})
                return
            if path == "/api/matches":
                saved = self.store.upsert(body)
                self.send_json(HTTPStatus.OK, {"match": saved})
                return
            if path == "/api/scrape":
                url = str(body.get("url") or "").strip()
                project_id = str(body.get("project_id") or "")
                directory = self.store.project_path(project_id).parent / "match-data" if project_id else self.match_data_dir
                if project_id and self.store.get(project_id) is None:
                    raise ValueError("Project not found")
                scraped = scrape_match(url, directory)
                if project_id:
                    events = scraped.get("events", [])
                    current = self.store.get(project_id)
                    if current.get("project_name") == "Untitled project":
                        scraped["project_name"] = f"{scraped['home_team']} vs {scraped['away_team']}"
                    scraped = {**self.store.upsert({**scraped, "id": project_id, "status": "in_progress",
                                                   "preview_windows": [], "preview_range": {}}), "events": events}
                self.send_json(HTTPStatus.OK, {"match": scraped})
                return
            if path == "/api/files/video":
                if sys.platform == "darwin":
                    self.send_json(HTTPStatus.OK, {"browser_picker": True})
                    return
                selected = choose_video_file()
                if selected is None:
                    self.send_json(HTTPStatus.OK, {"cancelled": True})
                    return
                token = uuid.uuid4().hex
                self.media_files[token] = selected
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "file": {
                            "name": selected.name,
                            "path": str(selected),
                            "size": selected.stat().st_size,
                            "url": f"/api/media/{token}",
                        }
                    },
                )
                return
            if path == "/api/files/reopen":
                match = self.store.get(str(body.get("match_id") or "").strip())
                if match is None:
                    raise ValueError("That saved match is no longer available.")
                period = {"1H": 1, "2H": 2, "ET1": 3, "ET2": 4, "PEN": 5}.get(str(body.get("period") or "1H"), 1)
                selected = Path(video_for_period(match, period)).resolve()
                if not selected.is_file():
                    raise ValueError("The saved video has moved or is no longer available.")
                token = uuid.uuid4().hex
                self.media_files[token] = selected
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "file": {
                            "name": selected.name,
                            "path": str(selected),
                            "size": selected.stat().st_size,
                            "url": f"/api/media/{token}",
                        }
                    },
                )
                return
            if path == "/api/folders/output":
                selected = choose_output_folder(str(body.get("initial_dir") or ""))
                self.send_json(
                    HTTPStatus.OK,
                    {"cancelled": selected is None, "path": str(selected or "")},
                )
                return
            if path == "/api/events":
                csv_path = str(body.get("csv_path") or "").strip()
                if not csv_path:
                    raise ValueError("Scrape or reopen a saved match before opening the table.")
                known = {Path(item["csv_path"]).resolve() for item in self.store.list() if item.get("csv_path")}
                if Path(csv_path).resolve() not in known:
                    raise ValueError("Open event data belonging to a saved project.")
                self.send_json(HTTPStatus.OK, load_event_rows(csv_path))
                return
            if path == "/api/filter-options":
                match = self.store.get(str(body.get("match_id") or "").strip())
                if match is None:
                    raise ValueError("Choose a saved match before filtering.")
                self.send_json(HTTPStatus.OK, load_filter_options(match))
                return
            if path == "/api/previews":
                match = self.store.get(str(body.get("match_id") or "").strip())
                if match is None:
                    raise ValueError("Choose a saved match before previewing clips.")
                options = body.get("options") if isinstance(body.get("options"), dict) else {}
                options = {**options, "dry_run": True, "clip_windows": []}
                config = build_clip_config(match, options, self.store.data_dir)
                try:
                    windows = compute_clip_windows(config)
                finally:
                    JobManager._cleanup_temporary_data(config)
                self.send_json(
                    HTTPStatus.OK,
                    {"windows": windows, "event_count": len(windows)},
                )
                return
            if path == "/api/previews/render":
                match = self.store.get(str(body.get("match_id") or "").strip())
                if match is None:
                    raise ValueError("Choose a saved match before rendering a preview.")
                start = float(body.get("start") or 0)
                end = float(body.get("end") or 0)
                encoder_preset = str(body.get("encoder_preset") or "veryfast")
                if encoder_preset not in {
                    "ultrafast",
                    "superfast",
                    "veryfast",
                    "faster",
                    "fast",
                    "medium",
                    "slow",
                }:
                    raise ValueError("Choose a supported encoder speed.")
                audio_bitrate = str(body.get("audio_bitrate") or "128k")
                if audio_bitrate not in {"96k", "128k", "160k", "192k", "256k"}:
                    raise ValueError("Choose a supported audio bitrate.")
                preview = render_preview_clip(
                    video_for_period(match, int(body.get("period") or 1)),
                    start,
                    end,
                    self.store.data_dir / "previews",
                    max(16, min(30, int(body.get("video_crf") or 20))),
                    encoder_preset,
                    audio_bitrate,
                )
                token = uuid.uuid4().hex
                self.media_files[token] = preview
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "file": {
                            "name": preview.name,
                            "size": preview.stat().st_size,
                            "url": f"/api/media/{token}",
                        }
                    },
                )
                return
            if path == "/api/jobs":
                match_id = str(body.get("match_id") or "").strip()
                match = self.store.get(match_id)
                if match is None:
                    raise ValueError("Save the match setup before building a clip plan.")
                options = body.get("options") if isinstance(body.get("options"), dict) else {}
                config = build_clip_config(match, options, self.store.data_dir)
                job = self.jobs.start(config)
                self.send_json(HTTPStatus.ACCEPTED, {"job": job})
                return
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path.split("/")[-2]
                if not self.jobs.cancel(job_id):
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown clip job"})
                else:
                    self.send_json(HTTPStatus.OK, {"cancelled": True})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API endpoint"})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def log_message(self, message: str, *args: Any) -> None:
        print(f"[clipmaker] {self.address_string()} {message % args}")


def create_server(host: str, port: int, data_dir: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), ClipMakerHandler)
    server.match_store = MatchStore(data_dir)  # type: ignore[attr-defined]
    server.match_data_dir = data_dir / "match-data"  # type: ignore[attr-defined]
    server.jobs = JobManager()  # type: ignore[attr-defined]
    server.media_files = {}  # type: ignore[attr-defined]
    server.analysis = AnalysisServer(ROOT, data_dir)  # type: ignore[attr-defined]
    atexit.register(server.analysis.close)
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / ".clipmaker-data")
    parser.add_argument("--analysis-port", type=int)
    args = parser.parse_args()
    if args.analysis_port:
        return run_analysis(ROOT, args.analysis_port)
    owner = os.environ.get("VIZORPLAY_OWNER_PID")
    owner_pid = int(owner) if owner else None
    if owner_pid is not None and (owner_pid <= 0 or owner_pid == os.getpid()):
        raise ValueError("Desktop owner must identify another live process")
    server = create_server(args.host, args.port, args.data_dir.resolve())
    server.desktop_owner_pid = owner_pid
    if owner_pid is not None:
        watch_process_owner(owner_pid, server.shutdown)
    print(f"VizorPlay shared UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if not server.jobs.close():
            print("Export workers did not finish within the shutdown deadline", file=sys.stderr)
        server.analysis.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
