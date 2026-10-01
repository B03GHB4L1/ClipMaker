"""Serve the shared ClipMaker frontend and its local application API."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
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
from urllib.parse import urlparse


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


class MatchStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "matches.json"
        self._lock = threading.Lock()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return value if isinstance(value, list) else []

    def upsert(self, match: dict[str, Any]) -> dict[str, Any]:
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
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not clean["id"]:
            parts = [clean["home_team"], clean["away_team"]]
            clean["id"] = "-vs-".join(part.lower().replace(" ", "-") for part in parts if part)
        if not clean["id"]:
            raise ValueError("A match id or team names are required")

        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            matches = []
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        matches = loaded
                except (OSError, json.JSONDecodeError):
                    matches = []
            matches = [item for item in matches if item.get("id") != clean["id"]]
            matches.insert(0, clean)
            fd, temporary_name = tempfile.mkstemp(dir=self.data_dir, prefix="matches-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                    json.dump(matches, temporary, indent=2)
                os.replace(temporary_name, self.path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
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


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancellations: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, config: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "queued",
            "dry_run": bool(config["dry_run"]),
            "logs": [],
            "progress": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        cancellation = threading.Event()
        with self._lock:
            self._jobs[job_id] = job
            self._cancellations[job_id] = cancellation
        threading.Thread(
            target=self._run,
            args=(job_id, config, cancellation),
            daemon=True,
        ).start()
        return dict(job)

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
            from clipmaker_core import run_clip_maker
        except Exception as error:
            self._append_log(job_id, f"Could not start the ClipMaker engine: {error}")
            self._update(
                job_id,
                status="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            self._cleanup_temporary_data(config)
            return

        logs: queue.Queue[dict[str, Any]] = queue.Queue()
        progress: queue.Queue[dict[str, Any]] = queue.Queue()
        self._update(job_id, status="running")

        def execute_engine() -> None:
            try:
                run_clip_maker(config, logs, progress, cancellation)
            except Exception as error:
                logs.put({"type": "error", "msg": f"ClipMaker engine stopped: {error}"})

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
        self._update(
            job_id,
            status=terminal_status or ("cancelled" if cancellation.is_set() else "complete"),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        self._cleanup_temporary_data(config)

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
    data_file, temporary_data_file = prepare_filtered_data(
        csv_path,
        str(match.get("id") or "match"),
        options,
        data_dir,
    )

    config = {
        "video_file": str(match.get("video_path") or ""),
        "video2_file": "",
        "video3_file": "",
        "video4_file": "",
        "video5_file": "",
        "split_video": False,
        "extra_time_video_mode": "single",
        "data_file": data_file,
        "_temporary_data_file": temporary_data_file,
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
        "output_dir": str((data_dir / "exports").resolve()),
        "output_filename": str(options.get("output_filename") or "Highlights.mp4"),
        "output_format": ".mp4",
        "video_crf": 20,
        "encoder_preset": "veryfast",
        "audio_bitrate": "128k",
        "timeline_corrections": [],
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
    return config


def detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "scoresway.com" in host:
        return "scoresway"
    if "whoscored.com" in host:
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
    server_version = "ClipMaker/1.3"

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

    def send_media(self, token: str) -> None:
        media_path = self.media_files.get(token)
        if media_path is None or not media_path.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Video is no longer available"})
            return
        size = media_path.stat().st_size
        start = 0
        end = size - 1
        range_header = self.headers.get("Range", "")
        if range_header.startswith("bytes="):
            requested = range_header.removeprefix("bytes=").split(",", 1)[0]
            first, _, last = requested.partition("-")
            if first:
                start = max(0, min(int(first), size - 1))
            if last:
                end = max(start, min(int(last), size - 1))
        length = end - start + 1
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
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "version": "1.3.0"})
            return
        if path == "/api/matches":
            self.send_json(HTTPStatus.OK, {"matches": self.store.list()})
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
                self.send_json(HTTPStatus.OK, {"job": job})
            return
        if path.startswith("/api/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API endpoint"})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self.read_json()
            if path == "/api/matches":
                saved = self.store.upsert(body)
                self.send_json(HTTPStatus.OK, {"match": saved})
                return
            if path == "/api/scrape":
                url = str(body.get("url") or "").strip()
                scraped = scrape_match(url, self.match_data_dir)
                self.send_json(HTTPStatus.OK, {"match": scraped})
                return
            if path == "/api/files/video":
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
                selected = Path(str(match.get("video_path") or "")).resolve()
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
            if path == "/api/events":
                csv_path = str(body.get("csv_path") or "").strip()
                if not csv_path:
                    raise ValueError("Scrape or reopen a saved match before opening the table.")
                self.send_json(HTTPStatus.OK, load_event_rows(csv_path))
                return
            if path == "/api/filter-options":
                match = self.store.get(str(body.get("match_id") or "").strip())
                if match is None:
                    raise ValueError("Choose a saved match before filtering.")
                self.send_json(HTTPStatus.OK, load_filter_options(match))
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
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / ".clipmaker-data")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.data_dir.resolve())
    print(f"ClipMaker shared UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
