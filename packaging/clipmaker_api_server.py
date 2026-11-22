"""Serve the shared ClipMaker frontend and its local application API."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import re
import socketserver
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, parse_qs, unquote

if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    log_dir = Path(os.environ.get("VIZORPLAY_DATA_DIR") or os.environ.get("CLIPMAKER_DATA_DIR") or Path.cwd())
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
COMPONENT_DIR = APP_DIR / "smp_component" / "frontend"
COMPONENT_PREFIX = "/analysis-component/"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if __package__:
    from .process_owner import watch_process_owner
    from . import update_check, user_folders
else:
    from process_owner import watch_process_owner
    import update_check
    import user_folders
from telestration.clips import CLIP_ID, SESSION_ID, EditorClips
from live.recorder import PART as LIVE_PART, SEGMENT_FILE as LIVE_FILE, LiveRecordings


# Navigating here asks the Windows desktop shell to install the update
# (src-tauri/src/lib.rs watches for it).
INSTALL_UPDATE_PATH = "/__vizorplay__/install-update"


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


ANALYSIS_STATE_LIMIT = 20_000
_STATE_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Control keys mirror classic widget keys, some of which contain spaces
# (e.g. "vl_selected_moment_Defensive Transition").
_CONTROL_KEY = re.compile(r"^[A-Za-z0-9_. -]{1,64}$")


def _clean_control_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, list):
        return [_clean_control_value(item) for item in value[:50] if not isinstance(item, (list, dict))]
    raise ValueError("Analysis controls must be text, numbers, booleans or short lists.")


def clean_analysis_state(state: Any) -> dict[str, Any]:
    """Validate the native workspace's saved tab and control state per view."""
    if not state:
        return {}
    if not isinstance(state, dict):
        raise ValueError("Analysis state must be an object.")
    clean: dict[str, Any] = {}
    for view, entry in state.items():
        if view not in {"analyst", "tactical"} or not isinstance(entry, dict):
            raise ValueError("Unknown analytical view in saved state.")
        tab = str(entry.get("tab") or "")
        if tab and not _STATE_KEY.match(tab):
            raise ValueError("Invalid analytical tab in saved state.")
        controls = entry.get("controls") or {}
        if not isinstance(controls, dict):
            raise ValueError("Analysis controls must be an object.")
        tabs = {}
        for tab_name, values in controls.items():
            if not _STATE_KEY.match(str(tab_name)) or not isinstance(values, dict):
                raise ValueError("Invalid analysis controls in saved state.")
            tabs[str(tab_name)] = {str(key): _clean_control_value(value) for key, value in values.items()
                                   if _CONTROL_KEY.match(str(key))}
        clean[view] = {"tab": tab, "controls": tabs}
    if len(json.dumps(clean)) > ANALYSIS_STATE_LIMIT:
        raise ValueError("Saved analysis state is too large.")
    return clean


def clamp_buffer(value: Any) -> int:
    """Clip buffers use the classic Watch panel's 0-60 second range."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ValueError("Clip buffers must be whole seconds between 0 and 60.") from None
    if not 0 <= number <= 60:
        raise ValueError("Clip buffers must be whole seconds between 0 and 60.")
    return number


VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"}
PERIOD_KEYS = {"1H", "2H", "ET1", "ET2", "PEN"}


def clean_client_project(body: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    """Validate file paths a browser request may set on a project.

    Paths are later served back through /api/media and read by /api/events, so
    a request must not be able to point them at arbitrary files (AGENTS.md:
    no arbitrary filesystem access through the browser API). Event data only
    comes from scraping or importing; videos must be existing video files.
    Unchanged values are accepted so a project whose video moved still saves."""
    existing = existing or {}
    body = dict(body)
    if "csv_path" in body and str(body.get("csv_path") or "") != str(existing.get("csv_path") or ""):
        raise ValueError("Event data is set by scraping a match or importing a CSV.")
    if "source" in body and str(body.get("source") or "") != str(existing.get("source") or ""):
        raise ValueError("Event data is set by scraping, importing or coding a match.")
    for key in ("feed_csv_path", "feed_source"):
        if key in body and str(body.get(key) or "") != str(existing.get(key) or ""):
            raise ValueError("Event data is set by scraping, importing or coding a match.")
    if "live_gaps" in body and body.get("live_gaps") != existing.get("live_gaps", []):
        raise ValueError("Recording gaps are set by the live recorder.")

    def video(value: Any, previous: Any) -> str:
        text = str(value or "").strip()
        if not text or text == str(previous or "").strip():
            return text
        path = Path(text)
        if path.suffix.lower() not in VIDEO_SUFFIXES or not path.is_file():
            raise ValueError("Choose an existing video file (MP4, MKV, MOV, AVI, WebM, M4V or TS).")
        return str(path)

    if "video_path" in body:
        body["video_path"] = video(body.get("video_path"), existing.get("video_path"))
    if "period_videos" in body:
        videos = body.get("period_videos")
        if not isinstance(videos, dict) or not set(videos) <= PERIOD_KEYS:
            raise ValueError("Period videos must be keyed by 1H, 2H, ET1, ET2 or PEN.")
        previous = existing.get("period_videos") or {}
        body["period_videos"] = {key: video(value, previous.get(key)) for key, value in videos.items()}
    return body


def prune_files(folder: Path, keep: int, min_age: float = 1800) -> None:
    """Delete scratch clips beyond the newest ``keep``, sparing any made in
    the last ``min_age`` seconds (they may still be open in the app)."""
    if not folder.is_dir():
        return
    files = sorted((path for path in folder.glob("*.mp4") if path.is_file()),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    cutoff = time.time() - min_age
    for stale in files[keep:]:
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink(missing_ok=True)
        except OSError:
            pass  # In use (Windows) or already gone: try again next time.


def _native_tabs():
    from analysis_core import event_maps, shot_map
    tabs = {("analyst", "shot-map"): {"view": shot_map.build_view, "clip_event": shot_map.clip_event}}
    for slug, builder in event_maps.TABS.items():
        tabs[("analyst", slug)] = {"view": builder, "clip_event": event_maps.CLIPS[slug]}
    from analysis_core import build_up, comparison, pressing
    tabs[("analyst", "pressing")] = {"view": pressing.build_view, "clip_event": pressing.clip}
    tabs[("analyst", "comparison")] = {"view": comparison.build_view, "clip_event": comparison.clip}
    for slug in ("defensive-transitions", "attacking-transitions", "style-profile", "set-pieces", "video-lab"):
        tabs[("tactical", slug)] = {"tactical": True}
    tabs[("analyst", "build-up")] = {"view": build_up.build_view, "clip_event": build_up.clip}
    return tabs


class _LazyTabs(dict):
    """Imports analysis handlers (and pandas) on first use."""

    def get(self, key, default=None):  # type: ignore[override]
        if not self:
            self.update(_native_tabs())
        return super().get(key, default)


NATIVE_TABS = _LazyTabs()


def analysis_reel(project, frames, events, kickoffs, corrections, before, after, folder) -> Path:
    """Cut each moment and join them in order, like the classic Top 5 Moments reel."""
    import subprocess
    from analysis_core.video import clip_window
    import video_encoder as encoders
    parts: list[Path] = []
    try:
        windows = [clip_window(frames.timing_frame, kickoffs, corrections, event["minute"], event["second"],
                               event["period"], before, after) for event in events[:5]]
        encoder = encoders.resolve("auto", encoders.find_ffmpeg())
        try:
            for period, start, duration in windows:
                parts.append(render_preview_clip(video_for_period(project, period), start, start + duration,
                                                 folder, 23, "ultrafast", "128k", encoder))
        except encoders.HardwareEncodeError:
            for part in parts:  # joined by stream copy: never mix encoders
                part.unlink(missing_ok=True)
            parts = [render_preview_clip(video_for_period(project, period), start, start + duration,
                                         folder, 23, "ultrafast", "128k", encoders.SOFTWARE)
                     for period, start, duration in windows]
        if len(parts) == 1:
            return parts.pop()
        listing = folder / f"reel-{uuid.uuid4().hex[:12]}.txt"
        listing.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
        output = folder / f"reel-{uuid.uuid4().hex[:12]}.mp4"
        ffmpeg = encoders.find_ffmpeg()
        try:
            result = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                                     "-i", str(listing), "-c", "copy", str(output)],
                                    capture_output=True, text=True, timeout=300)
        finally:
            listing.unlink(missing_ok=True)
        if result.returncode != 0:
            output.unlink(missing_ok=True)
            raise ValueError(f"Could not join the reel: {(result.stderr or '')[-400:]}")
        return output
    finally:
        for part in parts:
            part.unlink(missing_ok=True)


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
            # Source "both" (C4): csv_path is the feed's table with coded rows merged in;
            # these keep the feed itself, which the Analyst Room and Tactical Lab read.
            "feed_csv_path": str(match.get("feed_csv_path") or "").strip(),
            "feed_source": str(match.get("feed_source") or "").strip(),
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
            "analysis_state": clean_analysis_state(match.get("analysis_state")),
            # Breaks in a live recording (L1): at = seconds into the joined video, length = seconds lost.
            "live_gaps": [{"at": float(gap["at"]), "length": float(gap["length"])} for gap in (match.get("live_gaps") or [])
                          if isinstance(gap, dict) and isinstance(gap.get("at"), (int, float)) and isinstance(gap.get("length"), (int, float))],
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

    def delete(self, project_id: str) -> Path:
        """Move a project out of the library into project-trash/, so it can be put back by hand.
        Video files the project points at are never touched."""
        with self._lock:
            folder = self.project_path(project_id).parent
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            trash = self.data_dir / "project-trash" / f"{project_id}-{stamp}"
            found = False
            if folder.is_dir():
                trash.parent.mkdir(parents=True, exist_ok=True)
                os.replace(folder, trash)
                found = True
            if self.path.exists():
                legacy = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(legacy, list):
                    kept = [item for item in legacy if not (isinstance(item, dict) and item.get("id") == project_id)]
                    if len(kept) != len(legacy):
                        removed = [item for item in legacy if isinstance(item, dict) and item.get("id") == project_id]
                        atomic_json(trash / "legacy-history.json", removed)
                        atomic_json(self.path, kept)
                        found = True
            if not found:
                raise ValueError("Project not found")
            return trash


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
    ("headed_shots_only", "is_header", "Headed shots", "Shots", None),
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
    ("open_play_shots_only", "is_regular_play", "Open-play shots", "Shots", None),
    ("set_piece_shots_only", "is_set_piece_shot", "Set-piece shots", "Shots", None),
    ("from_corner_shots_only", "is_from_corner", "Shots from corners", "Shots", None),
    ("direct_freekick_shots_only", "is_direct_freekick", "Direct free kicks", "Shots", None),
    ("first_time_shots_only", "is_first_time", "First-time shots", "Shots", None),
    ("assisted_shots_only", "is_assisted", "Assisted shots", "Shots", None),
    ("saved_off_line_only", "is_saved_off_line", "Cleared off the line", "Shots", None),
    ("big_chances_created_only", "is_big_chance", "Big chances created", "Assists", None),
    ("assist_throughball_only", "is_assist_throughball", "Through-ball assists", "Assists", None),
    ("assist_cross_only", "is_assist_cross", "Cross assists", "Assists", None),
    ("assist_corner_only", "is_assist_corner", "Corner assists", "Assists", None),
    ("assist_freekick_only", "is_assist_freekick", "Free-kick assists", "Assists", None),
    ("intentional_assists_only", "is_intentional_assist", "Intentional assists", "Assists", None),
    ("gk_saves_only", "is_gk_save", "Goalkeeper saves", "Goalkeeping", None),
    ("diving_saves_only", "is_diving_save", "Diving saves", "Goalkeeping", None),
    ("hand_saves_only", "is_save_hands", "Saves with hands", "Goalkeeping", None),
    ("feet_saves_only", "is_save_feet", "Saves with feet", "Goalkeeping", None),
    ("parried_saves_only", "is_parried", "Parried saves", "Goalkeeping", None),
    ("caught_saves_only", "is_caught", "Caught or collected", "Goalkeeping", None),
    ("attacking_duels_only", "is_attacking_duel", "Attacking duels", "Duels", None),
    ("defending_duels_only", "is_defending_duel", "Defending duels", "Duels", None),
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


_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def readable_name(text: str, fallback: str = "VizorPlay export") -> str:
    """A file or folder name every OS accepts, kept close to what the user typed."""
    name = _UNSAFE_NAME.sub(" ", str(text or "")).strip(" .")
    name = re.sub(r"\s+", " ", name)[:80].strip(" .")
    return name or fallback


_NAME_PARTICLES = {"van", "von", "de", "da", "di", "del", "della", "dos", "das", "du", "le", "la", "ter", "ten", "der", "den"}


def surname(name: str) -> str:
    """"Ismael Doukoure" -> "Doukoure"; keeps "van Dijk" and one-word names whole."""
    words = str(name or "").split()
    if len(words) < 2:
        return " ".join(words)
    kept = [words[-1]]
    for word in reversed(words[1:-1]):
        if word.lower() not in _NAME_PARTICLES:
            break
        kept.insert(0, word)
    return " ".join(kept)


def players_label(players: list[str]) -> str:
    names = list(dict.fromkeys(surname(player) for player in players if str(player or "").strip()))
    if len(names) <= 3:
        return ", ".join(names)
    return f"{', '.join(names[:2])} and {len(names) - 2} more"


def clip_folder_name(label: str, count: int) -> str:
    """e.g. "Doukoure - 3 clips" or "Doukoure, Nanasi - 8 clips"."""
    clips = "1 clip" if count == 1 else f"{count} clips"
    return f"{readable_name(label)} - {clips}"


def export_label(match: dict[str, Any], options: dict[str, Any], clip_windows: list[dict[str, Any]]) -> str:
    """Who the exported clips are of: the players in them (clip labels read
    "Player - Type @ mm:ss", joined by " + " when clips merge), else the player
    filter, else the team, else the match."""
    in_clips = [part.split(" - ", 1)[0] for window in clip_windows
                for part in str(window.get("label") or "").split(" + ") if " - " in part]
    chosen = options.get("player_filters") if isinstance(options.get("player_filters"), list) else []
    return (players_label(in_clips) or players_label([str(item) for item in chosen])
            or str(options.get("team_filter") or "").strip()
            or str(match.get("project_name") or "").strip()
            or " v ".join(team for team in (str(match.get("home_team") or "").strip(),
                                             str(match.get("away_team") or "").strip()) if team))


def numbered(path: Path, taken: Callable[[Path], bool], folder: bool = False) -> Path:
    """path, or "name (2)", "name (3)"... beside it when that name is already used.
    A folder is numbered on its whole name (club names can contain dots)."""
    stem, suffix = (path.name, "") if folder else (path.stem, path.suffix)
    candidate, number = path, 2
    while taken(candidate):
        candidate = path.with_name(f"{stem} ({number}){suffix}")
        number += 1
    return candidate


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
            with self._lock:
                taken = lambda path: path.exists() or str(path.resolve()) in self._reserved_outputs
                if config.get("individual_clips"):
                    # A set of clips gets its own folder, named so a person can tell sets apart.
                    folder = numbered(output.parent / clip_folder_name(
                        config.get("export_label") or "", len(config.get("clip_windows") or [])), taken, folder=True)
                    config["output_dir"] = str(folder)
                    self._reserved_outputs.add(str(folder.resolve()))
                else:
                    # Never overwrite an earlier reel: "Highlights (2).mp4" sits beside it.
                    config["output_filename"] = numbered(output, taken).name
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
                if not config["dry_run"]:
                    reserved = Path(config["output_dir"]) if config.get("individual_clips") else \
                        Path(config["output_dir"]) / config["output_filename"]
                    self._reserved_outputs.discard(str(reserved.resolve()))
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
            if not config["dry_run"]:
                output = Path(config["output_dir"]) if config.get("individual_clips") else \
                    Path(config["output_dir"]) / config["output_filename"]
                with self._lock:
                    self._reserved_outputs.discard(str(output.resolve()))

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
        reported_files: list[str] | None = None
        while engine.is_alive() or not logs.empty() or not progress.empty():
            while not logs.empty():
                message = logs.get_nowait()
                if message.get("msg"):
                    self._append_log(job_id, str(message["msg"]))
                if message.get("type") == "done":
                    terminal_status = "complete"
                    if isinstance(message.get("files"), list):
                        reported_files = [str(item) for item in message["files"]]
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
            directory = Path(config["output_dir"]).resolve()
            if reported_files is not None:
                # Only what this run wrote, and only inside the chosen folder.
                outputs = [path for path in (Path(item).resolve() for item in reported_files)
                           if path.parent == directory]
            elif config.get("individual_clips"):
                outputs = sorted(directory.glob("*"))
            else:
                outputs = [directory / config["output_filename"]]
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
        row_clip_window,
        coded_video_time,
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
    if config.get("_timeline_data_file", config["data_file"]) != config["data_file"]:
        anchor_frame = assign_periods(read_csv_safe(config["_timeline_data_file"]),
                                     config.get("period_column") or None, config.get("fallback_row"))
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
        coded = coded_video_time(row)
        if coded is not None:
            timestamps.append(coded)
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
        start, end = row_clip_window(row, timestamp, config["before_buffer"], config["after_buffer"])
        raw_windows.append((start, end, label, period))
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
    video_encoder: str = "auto",
) -> Path:
    """Cut one clip. ``video_encoder`` is a setting ("auto"/"software"), which may
    fall back to x264, or an exact encoder name, which never changes (reels
    must not mix encoders)."""
    import math
    import subprocess

    import video_encoder as encoders

    source = Path(video_path).resolve()
    if not source.is_file():
        raise ValueError("The saved match video is no longer available.")
    duration = end - start
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or duration <= 0 or duration > 600:
        raise ValueError("Preview windows must be between 0 and 10 minutes long.")
    ffmpeg = encoders.find_ffmpeg()
    exact = video_encoder in {encoders.SOFTWARE, encoders.NVENC}
    encoder = video_encoder if exact else encoders.resolve(video_encoder, ffmpeg)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"preview-{uuid.uuid4().hex[:12]}.mp4"

    def run(chosen: str) -> subprocess.CompletedProcess:
        before, video = encoders.video_args(chosen, ffmpeg, crf, encoder_preset)
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", *before,
                   "-ss", str(start), "-i", str(source), "-t", str(duration),
                   "-map", "0:v:0", "-map", "0:a:0?", *video, "-c:a", "aac", "-b:a", audio_bitrate,
                   "-movflags", "+faststart", str(output)]
        return subprocess.run(command, capture_output=True, text=True, timeout=180)

    try:
        result = run(encoder)
        if result.returncode != 0 and encoder != encoders.SOFTWARE:
            if exact:
                raise encoders.HardwareEncodeError((result.stderr or "")[-500:])
            result = run(encoders.SOFTWARE)  # graphics card failed on this source
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


def save_to_user_folder(folder: Path, name: str, suffix: str, write: Callable[[str], None],
                        fallback: str = "VizorPlay clip") -> Path:
    """Write a file into the user's folder under a readable name, atomically.
    Never replaces a file already there: "Saka 34' (2).mp4" and so on."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = readable_name(re.sub(rf"{re.escape(suffix)}$", "", str(name or ""), flags=re.IGNORECASE), fallback)
    destination = folder / f"{stem}{suffix}"
    number = 2
    while destination.exists():
        destination = folder / f"{stem} ({number}){suffix}"
        number += 1
    fd, temporary_name = tempfile.mkstemp(dir=folder, prefix="saving-", suffix=".tmp")
    os.close(fd)
    try:
        write(temporary_name)
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return destination


def save_clip_copy(source: Path, folder: Path, name: str) -> Path:
    """Copy a watched clip into the user's folder."""
    import shutil
    return save_to_user_folder(folder, name, ".mp4", lambda temporary: shutil.copyfile(source, temporary))


MAX_TRACK_FRAMES = 120 * 60  # two minutes at 60 fps
IMAGE_SIGNATURES = {b"\x89PNG\r\n\x1a\n": ".png", b"GIF87a": ".gif", b"GIF89a": ".gif",
                    b"\xff\xd8\xff": ".jpg"}  # JPEG: analyst-editor screenshots
IMAGE_LIMIT = 50_000_000


def image_suffix(data: bytes) -> str:
    """".png", ".gif" or ".jpg" from the file's own bytes; anything else is refused."""
    for signature, suffix in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return suffix
    raise ValueError("Only PNG and GIF pictures, or JPEG screenshots, can be saved.")


def coded_rows(project: dict[str, Any], document: dict[str, Any]):
    from coding import to_events
    return to_events.rows(document, project.get("markers") or {}, lambda period: video_for_period(project, period),
                          str(project.get("home_team") or ""), str(project.get("away_team") or ""))


def feed_of(project: dict[str, Any]) -> tuple[str, str]:
    """(table, source) of the project's scraped or imported events, or ("", "") when it has none."""
    source = str(project.get("source") or "")
    if source == "both":
        return str(project.get("feed_csv_path") or ""), str(project.get("feed_source") or "csv")
    current = str(project.get("csv_path") or "")
    if current and source != "coded":
        return current, source
    return "", ""


def write_coded_table(store: Any, project: dict[str, Any], document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the event table of a project with coded events, and point the project at it.

    Without a feed the table is the coded rows alone (source "coded"). With a
    scraped or imported table the coded rows are merged into a copy of it
    (source "both", milestone C4); the feed itself is never changed, and a
    project whose codes are all deleted goes back to it."""
    from coding import store as coding_store, to_events
    folder = store.project_path(project["id"]).parent
    if document is None:
        document = coding_store.read(folder)
    feed, feed_source = feed_of(project)
    table, _ = coded_rows(project, document)
    if not feed:
        path = to_events.write_csv(folder / "match-data" / "coded_events.csv", table)
        return store.upsert({"id": project["id"], "csv_path": str(path), "source": "coded", "event_count": len(table)})
    if not Path(feed).is_file():
        return project  # the feed moved: keep what the project points at rather than lose it
    if not document.get("events"):
        if project.get("source") != "both":
            return project
        import pandas as pd
        count = len(pd.read_csv(feed, low_memory=False))
        return store.upsert({"id": project["id"], "csv_path": feed, "source": feed_source, "event_count": count,
                             "feed_csv_path": "", "feed_source": ""})
    count = to_events.write_merged(Path(feed), table, folder / "match-data" / "merged_events.csv")
    return store.upsert({"id": project["id"], "csv_path": str(folder / "match-data" / "merged_events.csv"),
                         "source": "both", "event_count": count, "feed_csv_path": feed, "feed_source": feed_source})


def has_codes(store: Any, project_id: str) -> bool:
    from coding import store as coding_store
    try:
        return bool(coding_store.read(store.project_path(project_id).parent)["events"])
    except (ValueError, OSError):
        return False


def analysis_view(project: dict[str, Any]) -> dict[str, Any]:
    """The project as the Analyst Room and Tactical Lab see it: a "both" project's feed only,
    so a coded Goal on top of the feed's own is not counted twice."""
    if project.get("source") == "both" and project.get("feed_csv_path"):
        return {**project, "csv_path": project["feed_csv_path"]}
    return project


def build_clip_config(match: dict[str, Any], options: dict[str, Any], data_dir: Path,
                      default_output_dir: Path | None = None) -> dict[str, Any]:
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
    video_encoder = str(options.get("video_encoder") or "auto").strip()
    if video_encoder not in {"auto", "software"}:
        raise ValueError("Choose automatic or software encoding.")
    requested_output_dir = str(options.get("output_dir") or "").strip().strip('"')
    output_dir = (
        Path(requested_output_dir).expanduser().resolve()
        if requested_output_dir
        # The app passes the user's videos folder (Videos/VizorPlay); embedded callers
        # and tests without one keep exports inside the project.
        else Path(default_output_dir).resolve() if default_output_dir
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
                raw_number = item.get("number")
                number = len(clip_windows) + 1 if raw_number in (None, "") else int(raw_number)
            except (TypeError, ValueError):
                raise ValueError("Invalid clip window.")
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or period not in {1, 2, 3, 4, 5}:
                raise ValueError("Clip end must follow a non-negative start, with a valid period.")
            if not 1 <= number <= 9999:
                raise ValueError("Clip numbers must be between 1 and 9999.")
            clip_windows.append(
                {
                    "start": start,
                    "end": end,
                    "label": str(item.get("label") or "Edited clip")[:300],
                    "period": period,
                    "number": number,
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
        "output_filename": readable_name(Path(str(options.get("output_filename") or "Highlights")).stem, "Highlights") + output_format,
        # Names the folder a set of separate clips is saved in.
        "export_label": export_label(match, options, clip_windows),
        "output_format": output_format,
        "video_crf": max(16, min(30, int(options.get("video_crf", 20)))),
        "encoder_preset": encoder_preset,
        "audio_bitrate": audio_bitrate,
        "video_encoder": video_encoder,
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
    # Team/player subsets must not redefine the first shootout kick's clock.
    # Keep the original source solely for timing anchors in preview and export.
    config["_timeline_data_file"] = csv_path
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
    if "type" not in frame.columns or "team" not in frame.columns:
        return 0, 0
    # Fixture labels ("Paris SG") often differ from the event feed's team names
    # ("Paris Saint-Germain FC"), so map them onto the names the events use.
    from team_names import resolve_home_away

    event_teams = [str(team).strip() for team in frame["team"].dropna().unique() if str(team).strip()]
    home_team, away_team = resolve_home_away(home_team, away_team, event_teams)
    if not home_team or not away_team or home_team == away_team:
        return 0, 0
    scores = {home_team: 0, away_team: 0}
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


def repair_saved_score(store: Any, project: dict[str, Any], csv_path: str) -> dict[str, int]:
    """Re-derive a project's score from its saved events; projects scraped before team names
    were resolved can carry a wrong 0-0. Saves the corrected score and returns it."""
    import pandas as pd

    frame = pd.read_csv(csv_path, low_memory=False)
    if project.get("source") == "both" and "source" in frame.columns:
        frame = frame[frame["source"].astype(str) != "coded"]  # the score is the feed's
    home_score, away_score = infer_score(frame, str(project.get("home_team") or ""), str(project.get("away_team") or ""))
    if (home_score, away_score) != (project.get("home_score"), project.get("away_score")):
        store.upsert({"id": project["id"], "home_score": home_score, "away_score": away_score})
    return {"home_score": home_score, "away_score": away_score}


def event_table(frame: Any, limit: int) -> dict[str, Any]:
    """Every column of the event CSV, as compact rows for the intake tables, with each
    row's period number alongside so the tables can filter by half."""
    head = frame.head(limit)
    periods = head["period"] if "period" in head.columns else [None] * len(head)
    return {
        "columns": [str(column) for column in head.columns],
        "rows": [[json_value(value) for value in row] for row in head.itertuples(index=False, name=None)],
        "periods": [normalize_period(json_value(value) or "") for value in periods],
    }


def load_event_rows(csv_path: str) -> dict[str, Any]:
    import pandas as pd

    path = Path(csv_path).resolve()
    if not path.is_file():
        raise ValueError("The saved event table is no longer available.")
    frame = pd.read_csv(path, low_memory=False)
    return {"events": event_table(frame, 5000), "event_count": len(frame), "truncated": len(frame) > 5000}


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
    qualifier_rows: dict[str, list[int]] = {}
    from clipmaker_core import SCOPED_QUALIFIERS

    scopes = {flag: types for flag, _column, _label, types in SCOPED_QUALIFIERS}
    for flag, column, label, group, expected in FILTER_QUALIFIERS:
        mask = qualifier_mask(frame, column, expected)
        if flag in scopes and "type" in frame.columns:
            mask &= frame["type"].astype(str).isin(scopes[flag])  # count what the filter keeps: Headers are passes
        count = int(mask.sum())
        if count:
            qualifier_rows[flag] = [int(index) for index in mask.to_numpy().nonzero()[0]]
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
        "events": event_index(frame, action_types, team_players, qualifier_rows),
        "has_xt": "xT" in frame.columns,
        "event_count": len(frame),
        # Coded events without a clicked pitch location: lane and depth filters leave them out.
        "unlocated": int(((frame["source"].astype(str) == "coded") & pd.to_numeric(frame["x"], errors="coerce").isna()).sum())
        if {"source", "x"} <= set(frame.columns) else 0,
    }


def qualifier_mask(frame: Any, column: str, expected: str | None) -> Any:
    """Rows where a filter qualifier holds, as the clip filters read it."""
    import pandas as pd

    if column == "__progressive__":
        progressive = pd.Series(False, index=frame.index)
        for progressive_column in ("prog_pass", "prog_carry"):
            if progressive_column in frame.columns:
                progressive |= (
                    pd.to_numeric(frame[progressive_column], errors="coerce").fillna(0).gt(0)
                )
        return progressive
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    if expected is not None:
        return frame[column].astype(str).eq(expected)
    return frame[column].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def event_index(
    frame: Any,
    action_types: list[str],
    team_players: dict[str, list[str]],
    qualifier_rows: dict[str, list[int]],
) -> dict[str, Any]:
    """A compact per-event table so the filter page can count what is left in a
    scope (team, period, players, action types) without asking the engine.

    Each event is a position in the parallel lists; -1 means unknown. The period
    is 1-5 or 0 when the row has none."""
    teams = list(team_players)
    players = sorted({name for names in team_players.values() for name in names}, key=str.casefold)

    def positions(column: str, values: list[str]) -> list[int]:
        if column not in frame.columns:
            return [-1] * len(frame)
        lookup = {value: position for position, value in enumerate(values)}
        return [
            lookup.get(str(value).strip(), -1) if value == value and value is not None else -1
            for value in frame[column].tolist()
        ]

    if "period" in frame.columns:
        periods = []
        for value in frame["period"].tolist():
            period = normalize_period(value) if value == value else ""
            periods.append(period if isinstance(period, int) and 1 <= period <= 5 else 0)
    else:
        periods = [0] * len(frame)

    return {
        "teams": teams,
        "players": players,
        "team": positions("team", teams),
        "player": positions("playerName", players),
        "type": positions("type", action_types),
        "period": periods,
        "qualifiers": qualifier_rows,
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
    preview = event_table(frame, 200)
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
    _cache_header_sent = False

    def send_header(self, keyword: str, value: str) -> None:
        if keyword.lower() == "cache-control":
            self._cache_header_sent = True
        super().send_header(keyword, value)

    def end_headers(self) -> None:
        # Page files are checked with the engine on every load (a cheap 304 when
        # unchanged), so an updated app never runs a mix of old and new scripts.
        if not self._cache_header_sent:
            super().send_header("Cache-Control", "no-cache")
        self._cache_header_sent = False
        super().end_headers()

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
    def live(self) -> LiveRecordings:
        return self.server.live  # type: ignore[attr-defined]

    @property
    def media_files(self) -> dict[str, Path]:
        return self.server.media_files  # type: ignore[attr-defined]

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        if parsed.startswith(COMPONENT_PREFIX):
            # Map component assets only; never other app files.
            candidate = (COMPONENT_DIR / unquote(parsed[len(COMPONENT_PREFIX):] or "index.html")).resolve()
            if COMPONENT_DIR.resolve() in candidate.parents and candidate.is_file():
                return str(candidate)
            return str(COMPONENT_DIR / "__missing__")
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
        raw = self.rfile.read(length)
        self._body_read = getattr(self, "_body_read", 0) + len(raw)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("The request body must be a JSON object")
        return value

    DRAIN_LIMIT = 1_000_000

    def discard_unread_body(self) -> None:
        """Consume the rest of a rejected request before replying.

        Closing a socket with unread data makes Windows reset the connection,
        so the client sees "connection aborted" instead of the error reply.
        Small bodies are drained; larger ones get ``Connection: close``.
        """
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        remaining = length - getattr(self, "_body_read", 0)
        if remaining <= 0:
            return
        if remaining > self.DRAIN_LIMIT:
            self.close_connection = True
            return
        try:
            self.connection.settimeout(2)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                self._body_read = getattr(self, "_body_read", 0) + len(chunk)
        except OSError:
            self.close_connection = True

    def send_post_error(self, status: HTTPStatus, message: str) -> None:
        self.discard_unread_body()
        if self.close_connection:
            self.send_response(status)
            encoded = json.dumps({"error": message}).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            return
        self.send_json(status, {"error": message})

    def analysis_clip(self, project, frames, handler, controls, body) -> dict[str, Any]:
        """Cut the selected event's clip with the classic workspace's timing."""
        from analysis_core.video import clip_window, kickoff_times_from_project
        before, after = clamp_buffer(body.get("before")), clamp_buffer(body.get("after"))
        if not str(project.get("video_path") or "").strip():
            raise ValueError("No video file loaded. Go to Intake and add the match video.")
        event = handler["clip_event"](frames, controls)
        settings = project.get("filter_settings") or {}
        kickoffs, corrections = kickoff_times_from_project(project), settings.get("timeline_corrections", [])
        folder = self.store.data_dir / "analysis-clips"
        if event.get("reel"):
            clip = analysis_reel(project, frames, event["reel"], kickoffs, corrections, before, after, folder)
            return self.publish_clip(clip, f"{event['player']}.mp4", before, after, folder)
        period, start, duration = clip_window(frames.timing_frame, kickoffs, corrections,
                                              event["minute"], event["second"], event["period"], before, after)
        if event.get("end"):
            # A sequence: classic cut_build_up_clip runs from the first action minus
            # `before` to the last plus `after`, both on the start period's clock.
            _, end_start, end_length = clip_window(frames.timing_frame, kickoffs, corrections, event["end"]["minute"],
                                                   event["end"]["second"], event["period"], 0, after)
            start = max(0.0, start)
            duration = max(1.0, max(start, end_start + end_length) - start)
        # Same encoder settings as the classic Watch panel (libx264 ultrafast, default CRF).
        clip = render_preview_clip(video_for_period(project, period), start, start + duration,
                                   folder, 23, "ultrafast", "128k")
        return self.publish_clip(clip, f"{event['player']} {event['minute']}'.mp4", before, after, folder)

    def publish_clip(self, clip: Path, name: str, before: int, after: int, folder: Path) -> dict[str, Any]:
        prune_files(folder, keep=20)
        token = uuid.uuid4().hex
        self.media_files[token] = clip
        return {"name": f"{readable_name(name[:-4] if name.endswith('.mp4') else name)}.mp4", "size": clip.stat().st_size,
                "url": f"/api/media/{token}", "before": before, "after": after}

    def tactical_request(self, tab, project, controls, body, is_clip) -> dict[str, Any]:
        """Tactical Lab tabs run the classic tab code against a recorder."""
        import shutil
        from analysis_core import tactical
        projects = [analysis_view(item) for item in self.store.list()]
        if is_clip:
            action = str(body.get("action") or "")
            source, name = tactical.clip(tab, controls, project, projects, action)
            folder = self.store.data_dir / "analysis-clips"
            folder.mkdir(parents=True, exist_ok=True)
            clip = folder / f"tactical-{uuid.uuid4().hex[:12]}.mp4"
            shutil.move(source, clip)
            return {"file": self.publish_clip(clip, name, 0, 0, folder)}
        view, _ = tactical.render(tab, controls, project, projects, light=body.get("theme") != "dark")
        view["has_video"] = bool(str(project.get("video_path") or "").strip())
        return {"view": view}

    def project_codes(self, project_id: str, body: dict[str, Any] | None) -> None:
        """GET or POST /api/projects/<id>/codes: the project's coded events (app/coding)."""
        from coding import store as coding_store
        project = self.store.get(project_id)
        if project is None:
            raise ValueError("Project not found")
        folder = self.store.project_path(project_id).parent
        if body is None:
            document = coding_store.read(folder)
        else:
            document = coding_store.apply(folder, body)
            project = write_coded_table(self.store, project, document)
        _, unplaced = coded_rows(project, document)
        self.send_json(HTTPStatus.OK, {"codes": document["panel"]["codes"], "panel": document["panel"],
                                       "squads": document["squads"], "events": document["events"],
                                       "leads": document.get("leads", {}), "unplaced": unplaced, "project": project})

    @property
    def code_templates(self):
        from coding import templates
        return templates.TemplateLibrary(self.store.data_dir / "code-templates")

    def code_template_action(self, action: str, body: dict[str, Any]) -> None:
        """POST /api/code-templates[/delete|/export]: the analyst's code panels.

        Templates arrive as JSON values (the page reads an imported file itself),
        and an export is written to the export folder under the panel's name, so
        the browser never names a path."""
        from coding import templates
        library = self.code_templates
        if action == "":
            if set(body) - {"template", "replace"}:
                raise ValueError("Send a code panel as template.")
            saved = library.save(body.get("template"), replace=body.get("replace") is True)
            self.send_json(HTTPStatus.OK, {"template": saved, "templates": library.list()})
        elif action == "delete":
            library.delete(str(body.get("id") or ""))
            self.send_json(HTTPStatus.OK, {"templates": library.list()})
        elif action == "export":
            value = body.get("template")
            if isinstance(value, dict):
                value = {key: item for key, item in value.items() if key != "builtin"}
            template = templates.clean(value)
            text = json.dumps(template, indent=1, ensure_ascii=False)
            folder = Path(self.server.default_export_dir or self.store.data_dir / "exports")  # type: ignore[attr-defined]

            def write(temporary: str) -> None:
                Path(temporary).write_text(text, encoding="utf-8")

            saved = save_to_user_folder(folder, f"{template['name']} codes", ".json", write, fallback="VizorPlay codes")
            token = uuid.uuid4().hex
            self.server.saved_clips[token] = saved  # type: ignore[attr-defined]
            self.send_json(HTTPStatus.OK, {"saved": {"name": saved.name, "folder": str(saved.parent), "id": token}})
        else:
            raise ValueError("Unknown code panel action")

    def analysis_project(self, project_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", project_id or ""):
            raise ValueError("Open a project before using the analytical workspace.")
        project = self.store.get(project_id)
        if not project:
            raise ValueError("Project not found")
        project = analysis_view(project)
        if not project.get("csv_path") or not Path(project["csv_path"]).is_file():
            raise ValueError("Scrape or import a match before opening an analytical workspace.")
        return project

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
        if suffix != ".csv" and suffix not in VIDEO_SUFFIXES:
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
                    self._body_read = getattr(self, "_body_read", 0) + len(chunk)
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
                if has_codes(self.store, project_id):
                    project = write_coded_table(self.store, project)
                self.send_json(HTTPStatus.OK, {"match": {**project, **load_event_rows(str(project["csv_path"]))}})
            else:
                token = uuid.uuid4().hex
                self.media_files[token] = destination
                self.send_json(HTTPStatus.OK, {"file": {"name": filename, "path": str(destination), "size": length, "url": f"/api/media/{token}"}})
        finally:
            if temporary.exists():
                temporary.unlink()

    def save_image(self) -> None:
        """A picture made in the page (chart PNG/GIF, editor screenshot PNG/JPEG), saved to the user's folder.
        The desktop windows ignore <a download>, so the page sends the bytes here."""
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > IMAGE_LIMIT:
            raise ValueError("Pictures must be under 50 MB.")
        data = self.rfile.read(length)
        self._body_read = getattr(self, "_body_read", 0) + len(data)
        if len(data) != length:
            raise ValueError("The picture did not arrive in full; nothing was saved.")
        suffix = image_suffix(data)
        name = Path(unquote(self.headers.get("X-File-Name", ""))).name
        folder = Path(self.server.default_export_dir or self.store.data_dir / "exports")  # type: ignore[attr-defined]

        def write(temporary: str) -> None:
            with open(temporary, "wb") as output:
                output.write(data)

        saved = save_to_user_folder(folder, name, suffix, write, fallback="VizorPlay chart")
        token = uuid.uuid4().hex
        self.server.saved_clips[token] = saved  # type: ignore[attr-defined]
        self.send_json(HTTPStatus.OK, {"saved": {"name": saved.name, "folder": str(saved.parent), "id": token}})

    @property
    def editor_clips(self) -> EditorClips:
        return self.server.editor_clips  # type: ignore[attr-defined]

    def scratch_clip(self, token: str) -> Path | None:
        """A clip the engine cut for watching (never a path named by the request)."""
        source = self.media_files.get(token)
        scratch = {(self.store.data_dir / "previews").resolve(), (self.store.data_dir / "analysis-clips").resolve()}
        if source is None or not source.is_file() or source.resolve().parent not in scratch:
            return None
        return source

    def annotate_clip(self, body: dict[str, Any]) -> None:
        """Copy a watched clip into the project so the analyst editor can open it."""
        source = self.scratch_clip(str(body.get("media") or ""))
        if source is None:
            self.send_post_error(HTTPStatus.NOT_FOUND, "That clip is no longer available. Watch it again, then annotate it.")
            return
        project_id = str(body.get("project_id") or "")
        if self.store.get(project_id) is None:
            raise ValueError("Open a saved project before annotating a clip.")
        session_id = body.get("session_id")
        if session_id is not None and not (isinstance(session_id, str) and SESSION_ID.match(session_id)):
            raise ValueError("Invalid annotate session.")
        if session_id is not None and not self.editor_clips.has_session(project_id, session_id):
            self.send_post_error(HTTPStatus.NOT_FOUND, "That annotate session is not in the project any more.")
            return
        clip = self.editor_clips.import_clip(project_id, source, str(body.get("name") or ""))
        try:
            # Several clips sent together share one session; a single clip starts its own.
            session = self.editor_clips.add_to_session(project_id, clip["id"], session_id,
                                                       str(body.get("session_name") or clip["name"]))
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        self.send_json(HTTPStatus.CREATED, {"clip": clip, "session": session})

    def editor_sessions(self, path: str, body: dict[str, Any] | None) -> None:
        """The project's annotate sessions (GET), or rename / delete a session, or remove one clip (POST)."""
        parts = path.split("/")
        project_id = parts[3] if len(parts) > 3 else ""
        action = parts[4] if len(parts) == 5 else None
        if len(parts) not in (4, 5) or self.store.get(project_id) is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Open a saved project first."})
            return
        clips = self.editor_clips
        try:
            if body is None and action is None:
                self.send_json(HTTPStatus.OK, {"sessions": clips.sessions(project_id)})
                return
            if body is None:
                raise ValueError("Unknown annotate session request")
            session_id = str(body.get("session_id") or "")
            clip_id = str(body.get("clip_id") or "")
            if action == "rename":
                if not SESSION_ID.match(session_id):
                    raise ValueError("Invalid annotate session.")
                clips.rename_session(project_id, session_id, str(body.get("name") or ""))
            elif action == "delete":
                if not SESSION_ID.match(session_id):
                    raise ValueError("Invalid annotate session.")
                clips.remove_session(project_id, session_id)
            elif action == "remove-clip":
                if not CLIP_ID.match(clip_id):
                    raise ValueError("Invalid clip id.")
                clips.remove_clip(project_id, clip_id)
            else:
                raise ValueError("Unknown annotate session request")
        except LookupError as error:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        self.send_json(HTTPStatus.OK, {"sessions": clips.sessions(project_id)})

    def editor_parts(self, path: str) -> tuple[str, str]:
        parts = path.split("/")
        if len(parts) != 5:
            raise ValueError("Unknown editor request")
        return parts[3], parts[4]

    def editor_clip(self) -> None:
        """The clip, its video link and its drawings."""
        project_id, clip_id = self.editor_parts(urlparse(self.path).path)
        try:
            record, video = self.editor_clips.get(project_id, clip_id)
        except LookupError as error:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        token = uuid.uuid5(uuid.NAMESPACE_URL, str(video.resolve())).hex
        self.media_files[token] = video
        self.send_json(HTTPStatus.OK, {
            "clip": record,
            "url": f"/api/media/{token}",
            "annotations": self.editor_clips.load_annotations(project_id, clip_id),
            "changed": self.editor_clips.changed(record, video),
        })

    @property
    def tracking_jobs(self) -> Any:
        """Created on first use, so OpenCV is not loaded until someone follows a player."""
        server = self.server
        with server.tracking_lock:  # type: ignore[attr-defined]
            if server.tracking_jobs is None:  # type: ignore[attr-defined]
                from telestration.tracker import TrackingJobs
                server.tracking_jobs = TrackingJobs()  # type: ignore[attr-defined]
            return server.tracking_jobs  # type: ignore[attr-defined]

    def start_tracking(self, path: str, body: dict[str, Any]) -> None:
        """Follow a player from `from_frame` (where they are `box`) to `to_frame`, in the background."""
        parts = path.split("/")
        if len(parts) != 6:
            raise ValueError("Unknown editor request")
        try:
            record, video = self.editor_clips.get(parts[3], parts[4])
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        start, end = body.get("from_frame"), body.get("to_frame")
        for value in (start, end):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < record["frames"]:
                raise ValueError("Tracking frames must be frames of the clip.")
        if end < start:
            raise ValueError("Tracking cannot end before it starts.")
        if end - start > MAX_TRACK_FRAMES:
            raise ValueError("Follow a player for up to 2 minutes at a time.")
        from telestration.annotations import clean_box
        from telestration import tracker
        box = clean_box(body.get("box"), "The player box")
        # The player's next keyframe, just after the span: tracked back from there and blended (M5).
        end_box = None
        if body.get("to_box") is not None:
            if end + 1 >= record["frames"]:
                raise ValueError("The next keyframe must be a frame of the clip.")
            end_box = clean_box(body.get("to_box"), "The next keyframe's box")
        ffmpeg = _find_ffmpeg()
        tracker.make_tracker()  # refuse now, not in the background, if OpenCV is missing
        job = self.tracking_jobs.start(
            lambda cancel, progress: tracker.track_span(ffmpeg, video, record, start, end, box, cancel, progress,
                                                        end_box=end_box))
        self.send_json(HTTPStatus.ACCEPTED, {"job": job})

    def tracking_job(self, job_id: str, cancel: bool = False) -> None:
        if not re.fullmatch(r"[a-f0-9]{16}", job_id or ""):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown tracking job."})
            return
        job = self.tracking_jobs.cancel(job_id) if cancel else self.tracking_jobs.get(job_id)
        if job is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown tracking job."})
            return
        self.send_json(HTTPStatus.OK, {"job": job})

    @property
    def models_folder(self) -> Path:
        """Optional model downloads live with the app's data, never in a folder the page names."""
        return self.store.data_dir / "models"

    def editor_models(self) -> None:
        from telestration import players
        self.send_json(HTTPStatus.OK, {"players": players.status(self.models_folder)})

    def install_player_finder(self) -> None:
        """Download the player finder (fixed address, checked against its SHA-256) as a job."""
        from telestration import players
        current = players.status(self.models_folder)
        if current["installed"]:
            self.send_json(HTTPStatus.OK, {"model": current})
            return
        server, jobs, folder = self.server, self.tracking_jobs, self.models_folder
        with server.tracking_lock:  # type: ignore[attr-defined]  # one download at a time
            running = getattr(server, "model_install_job", None)
            job = jobs.get(running) if running else None
            if job is None or job["status"] != "running":
                job = jobs.start(lambda cancel, progress: players.install(folder, cancel, progress))
                server.model_install_job = job["id"]  # type: ignore[attr-defined]
        self.send_json(HTTPStatus.ACCEPTED, {"job": job})

    def find_players(self, path: str, body: dict[str, Any]) -> None:
        """The players on one frame of an editor clip, in the background (board from this frame)."""
        parts = path.split("/")
        if len(parts) != 6:
            raise ValueError("Unknown editor request")
        try:
            record, video = self.editor_clips.get(parts[3], parts[4])
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        frame = body.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < record["frames"]:
            raise ValueError("Find players on a frame of the clip.")
        from telestration import players
        state = players.status(self.models_folder)
        if not state["installed"]:
            self.send_json(HTTPStatus.CONFLICT, {"error": "Download the player finder first.", "model": state})
            return
        try:
            import cv2  # noqa: F401  # refuse now, not in the background, if OpenCV is missing
        except ImportError as error:
            raise RuntimeError("Finding players needs OpenCV, which is not installed.") from error
        ffmpeg = _find_ffmpeg()
        folder = self.models_folder
        job = self.tracking_jobs.start(
            lambda cancel, progress: players.find_players(ffmpeg, video, record, frame, folder, cancel, progress))
        self.send_json(HTTPStatus.ACCEPTED, {"job": job})

    def save_editor_annotations(self, path: str, body: dict[str, Any]) -> None:
        project_id, clip_id = self.editor_parts(path)
        try:
            saved = self.editor_clips.save_annotations(project_id, clip_id, body.get("annotations"))
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        self.send_json(HTTPStatus.OK, {"annotations": saved})

    @property
    def editor_exports(self) -> Any:
        """Created on first use, like tracking, so the export code loads only when needed."""
        server = self.server
        with server.tracking_lock:  # type: ignore[attr-defined]
            if server.editor_exports is None:  # type: ignore[attr-defined]
                from telestration.export import ExportSessions
                server.editor_exports = ExportSessions(self.store.data_dir / "editor-exports")  # type: ignore[attr-defined]
            return server.editor_exports  # type: ignore[attr-defined]

    def start_export(self, path: str) -> None:
        """Open an export of the clip as last saved; the page then sends its overlays."""
        parts = path.split("/")
        if len(parts) != 6:
            raise ValueError("Unknown editor request")
        try:
            record, video = self.editor_clips.get(parts[3], parts[4])
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        document = self.editor_clips.load_annotations(parts[3], parts[4])
        session = self.editor_exports.create(parts[3], parts[4], record, video, document)
        self.send_json(HTTPStatus.CREATED, {"export": session})

    def receive_overlays(self, session_id: str) -> None:
        """A batch of overlays the editor drew (telestration.export.unpack_batch)."""
        from telestration.export import BATCH_LIMIT
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > BATCH_LIMIT:
            raise ValueError("Send overlays in batches under 64 MB.")
        data = self.rfile.read(length)
        self._body_read = getattr(self, "_body_read", 0) + len(data)
        if len(data) != length:
            raise ValueError("The overlays did not arrive in full.")
        try:
            count = self.editor_exports.add_batch(session_id, data)
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        self.send_json(HTTPStatus.OK, {"received": count})

    def render_export(self, session_id: str, body: dict[str, Any]) -> None:
        """Burn the drawings into the clip in the background; poll it as an editor job."""
        from telestration import export
        try:
            session = self.editor_exports.take(session_id)
        except LookupError as error:
            self.send_post_error(HTTPStatus.NOT_FOUND, str(error))
            return
        ffmpeg = _find_ffmpeg()
        folder = Path(self.server.default_export_dir or self.store.data_dir / "exports")  # type: ignore[attr-defined]
        name = str(body.get("name") or "")[:160]
        exports = self.editor_exports
        saved_clips = self.server.saved_clips  # type: ignore[attr-defined]

        def register(saved: Path) -> str:
            token = uuid.uuid4().hex
            saved_clips[token] = saved
            return token

        def work(cancel: threading.Event, progress: Callable[[int, int], None]) -> dict[str, Any]:
            try:
                return export.run_export(ffmpeg, session, folder, name, save_to_user_folder, register, cancel, progress)
            finally:
                exports.discard(session_id)

        job = self.tracking_jobs.start(work)
        self.send_json(HTTPStatus.ACCEPTED, {"job": job})

    def live_clip(self, project: dict[str, Any], body: dict[str, Any]) -> None:
        """POST /api/projects/<id>/live/clip {start, end, name}: a clip cut from the recording
        while it records (L2), saved to the user's export folder like any other clip."""
        if set(body) - {"start", "end", "name"}:
            raise ValueError("Send a clip as start, end and name.")
        folder = Path(self.server.default_export_dir or self.store.data_dir / "exports")  # type: ignore[attr-defined]
        span: list[tuple[float, float]] = []

        def write(temporary: str) -> None:
            span.append(self.live.clip(project["id"], body.get("start"), body.get("end"), temporary))

        name = str(body.get("name") or "")[:100]
        saved = save_to_user_folder(folder, f"{project.get('project_name') or 'Live'} {name}".strip(), ".mp4", write)
        token = uuid.uuid4().hex
        self.server.saved_clips[token] = saved  # type: ignore[attr-defined]
        self.send_json(HTTPStatus.OK, {"saved": {"name": saved.name, "folder": str(saved.parent), "id": token},
                                       "start": span[0][0], "end": span[0][1]})

    def send_live_file(self, path: str) -> None:
        """/api/live/<project>/<partNN>/<init.mp4|seg_NNNNN.m4s>: nothing else in the folder is served."""
        parts = path.split("/")
        if len(parts) != 6 or not LIVE_PART.match(parts[4]) or not LIVE_FILE.match(parts[5]):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            data = (self.live.folder(parts[3]) / parts[4] / parts[5]).read_bytes()
        except (ValueError, OSError):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "That part of the recording is not available"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
            self.reply_error(HTTPStatus.BAD_REQUEST, str(error))
        except OSError as error:
            self.reply_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))

    def reply_error(self, status: HTTPStatus, message: str, post: bool = False) -> None:
        """Send an error reply unless the client has already disconnected."""
        try:
            if post:
                self.send_post_error(status, message)
            else:
                self.send_json(status, {"error": message})
        except ConnectionError:
            self.close_connection = True

    def handle_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/snapshots":
            self.send_json(HTTPStatus.OK, {"snapshots": self.store.snapshots()})
            return
        if path == "/api/analysis/config":
            from analysis_core import TABS, VIEWS
            self.send_json(HTTPStatus.OK, {"views": {view: {"label": label, "tabs": TABS[view]}
                                                     for view, label in VIEWS.items()}})
            return
        if path == "/api/analysis/summary":
            project = self.analysis_project(parse_qs(urlparse(self.path).query).get("project", [""])[0])
            frames = self.server.analysis_frames.get(project["csv_path"])  # type: ignore[attr-defined]
            self.send_json(HTTPStatus.OK, {"summary": frames.summary(),
                                           "analysis_state": project.get("analysis_state", {})})
            return
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "version": "1.0.0", "pid": os.getpid(), "parent_pid": os.getppid(),
                "desktop_owner_pid": getattr(self.server, "desktop_owner_pid", None)})
            return
        if path == "/api/folders/output/default":
            self.send_json(HTTPStatus.OK, {"path": str(self.server.default_export_dir or "")})  # type: ignore[attr-defined]
            return
        if path == "/api/update":
            self.send_json(HTTPStatus.OK, {"update": self.server.update_status.get()})  # type: ignore[attr-defined]
            return
        if path == INSTALL_UPDATE_PATH:
            # The desktop shell intercepts this navigation and installs the
            # update. Anywhere else, No Content keeps the page where it is.
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/matches":
            self.send_json(HTTPStatus.OK, {"matches": self.store.list()})
            return
        if path == "/api/projects":
            self.send_json(HTTPStatus.OK, {"projects": self.store.list(), "directory": str(self.store.data_dir / "projects")})
            return
        if path == "/api/code-templates":
            self.send_json(HTTPStatus.OK, {"templates": self.code_templates.list()})
            return
        if path == "/api/live/capabilities":
            self.send_json(HTTPStatus.OK, self.live.capabilities())
            return
        if path.startswith("/api/live/"):
            self.send_live_file(path)
            return
        if path.startswith("/api/projects/") and path.endswith("/live"):
            parts = path.split("/")
            if len(parts) != 5 or self.store.get(parts[3]) is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Project not found"})
                return
            after = parse_qs(urlparse(self.path).query).get("after", ["0"])[0]
            self.send_json(HTTPStatus.OK, {"live": self.live.status(parts[3], int(after) if after.isdigit() else 0)})
            return
        if path.startswith("/api/projects/") and path.endswith("/codes"):
            parts = path.split("/")
            try:
                if len(parts) != 5:
                    raise ValueError("Unknown project action")
                self.project_codes(parts[3], None)
            except ValueError as error:
                self.send_json(HTTPStatus.NOT_FOUND if str(error) == "Project not found" else HTTPStatus.BAD_REQUEST,
                               {"error": str(error)})
            return
        if path.startswith("/api/projects/"):
            project = self.store.get(path.rsplit("/", 1)[-1])
            self.send_json(HTTPStatus.OK if project else HTTPStatus.NOT_FOUND, {"project": project} if project else {"error": "Project not found"})
            return
        if path.startswith("/api/media/"):
            self.send_media(path.rsplit("/", 1)[-1])
            return
        if path.startswith("/api/editor-sessions/"):
            self.editor_sessions(path, None)
            return
        if path.startswith("/api/editor/"):
            self.editor_clip()
            return
        if path.startswith("/api/editor-jobs/"):
            self.tracking_job(path.split("/")[-1])
            return
        if path == "/api/editor-models":
            self.editor_models()
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
        self._body_read = 0
        try:
            self.validate_local_request()
            if path == "/api/files/upload":
                self.receive_upload()
                return
            if path == "/api/images/save":
                self.save_image()
                return
            if path.startswith("/api/editor-exports/") and path.endswith("/overlays"):
                self.receive_overlays(path.split("/")[-2])
                return
            body = self.read_json()
            if path == "/api/open-site":
                self.send_json(HTTPStatus.OK, {"opened": update_check.open_source_site(str(body.get("site") or ""))})
                return
            if path == "/api/update/open-release":
                self.send_json(HTTPStatus.OK, {"opened": update_check.open_release_page()})
                return
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
            if path.startswith("/api/analysis/"):
                from analysis_core import validate_tab
                parts = path.split("/")
                if len(parts) not in {5, 6} or (len(parts) == 6 and parts[5] != "clip"):
                    raise ValueError("Unknown analytical tab")
                validate_tab(parts[3], parts[4])
                project = self.analysis_project(str(body.get("project_id") or ""))
                handler = NATIVE_TABS.get((parts[3], parts[4]))
                if handler is None:
                    raise ValueError("Unknown analytical tab")
                controls = body.get("controls") if isinstance(body.get("controls"), dict) else {}
                if handler.get("tactical"):
                    self.send_json(HTTPStatus.OK, self.tactical_request(parts[4], project, controls, body, len(parts) == 6))
                    return
                frames = self.server.analysis_frames.get(project["csv_path"])  # type: ignore[attr-defined]
                if len(parts) == 6:
                    self.send_json(HTTPStatus.OK, {"file": self.analysis_clip(project, frames, handler, controls, body)})
                    return
                view = handler["view"](frames, controls, light_mode=body.get("theme") != "dark")
                settings = project.get("filter_settings") or {}
                view["clip_defaults"] = {"before": clamp_buffer(settings.get("before_buffer", 5)),
                                         "after": clamp_buffer(settings.get("after_buffer", 8))}
                view["has_video"] = bool(str(project.get("video_path") or "").strip())
                self.send_json(HTTPStatus.OK, {"view": view})
                return
            if path in ("/api/code-templates", "/api/code-templates/delete", "/api/code-templates/export"):
                self.code_template_action(path[len("/api/code-templates/"):] if path.count("/") == 3 else "", body)
                return
            if path.startswith("/api/projects/") and path.endswith("/codes"):
                parts = path.split("/")
                if len(parts) != 5:
                    raise ValueError("Unknown project action")
                self.project_codes(parts[3], body)
                return
            if path.startswith("/api/projects/") and path.rsplit("/", 2)[-2:] in (["live", "start"], ["live", "stop"], ["live", "clip"]):
                parts = path.split("/")
                project = self.store.get(parts[3]) if len(parts) == 6 else None
                if project is None:
                    raise ValueError("Project not found")
                if parts[5] == "clip":
                    self.live_clip(project, body)
                    return
                if parts[5] == "start":
                    if project.get("video_path"):
                        raise ValueError("This project already has a video. Start a new project to record live.")
                    live = self.live.start(parts[3], body.get("source"))
                else:
                    live = self.live.stop(parts[3], project.get("project_name") or "Live recording")
                self.send_json(HTTPStatus.OK, {"live": live})
                return
            if path.startswith("/api/projects/") and path.endswith("/delete"):
                parts = path.split("/")
                if len(parts) != 5:
                    raise ValueError("Unknown project action")
                if parts[3] in self.live.recordings and self.live.recordings[parts[3]].active:
                    raise ValueError("Stop the live recording before deleting this project.")
                self.store.delete(parts[3])
                self.send_json(HTTPStatus.OK, {"deleted": parts[3], "projects": self.store.list()})
                return
            if path.startswith("/api/projects/"):
                project_id = path.rsplit("/", 1)[-1]
                if self.store.get(project_id) is None:
                    raise ValueError("Project not found")
                saved = self.store.upsert({**clean_client_project(body, self.store.get(project_id)), "id": project_id})
                if saved.get("source") in ("coded", "both") and set(body) & {"markers", "video_path", "period_videos",
                                                                              "home_team", "away_team"}:
                    # Coded events are kept in video time: re-time their table to the new kick-offs.
                    saved = write_coded_table(self.store, saved)
                self.send_json(HTTPStatus.OK, {"project": saved})
                return
            if path == "/api/matches":
                saved = self.store.upsert(clean_client_project(body, self.store.get(str(body.get("id") or ""))))
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
                    saved = self.store.upsert({**scraped, "id": project_id, "status": "in_progress",
                                               "preview_windows": [], "preview_range": {}})
                    if has_codes(self.store, project_id):
                        saved = write_coded_table(self.store, saved)  # a new feed: merge the codes into it again
                    scraped = {**saved, "events": events}
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
                owners = [item for item in self.store.list()
                          if item.get("csv_path") and Path(item["csv_path"]).resolve() == Path(csv_path).resolve()]
                if not owners:
                    raise ValueError("Open event data belonging to a saved project.")
                rows = load_event_rows(csv_path)
                rows.update(repair_saved_score(self.store, owners[0], csv_path))
                self.send_json(HTTPStatus.OK, rows)
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
                video_encoder = str(body.get("video_encoder") or "auto")
                if video_encoder not in {"auto", "software"}:
                    raise ValueError("Choose automatic or software encoding.")
                preview = render_preview_clip(
                    video_for_period(match, int(body.get("period") or 1)),
                    start,
                    end,
                    self.store.data_dir / "previews",
                    max(16, min(30, int(body.get("video_crf") or 20))),
                    encoder_preset,
                    audio_bitrate,
                    video_encoder,
                )
                prune_files(preview.parent, keep=20)
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
                config = build_clip_config(match, options, self.store.data_dir, self.server.default_export_dir)  # type: ignore[attr-defined]
                job = self.jobs.start(config)
                self.send_json(HTTPStatus.ACCEPTED, {"job": job})
                return
            if path == "/api/editor/clips":
                self.annotate_clip(body)
                return
            if path.startswith("/api/editor-sessions/"):
                self.editor_sessions(path, body)
                return
            if path.startswith("/api/editor/") and path.endswith("/track"):
                self.start_tracking(path, body)
                return
            if path.startswith("/api/editor/") and path.endswith("/players"):
                self.find_players(path, body)
                return
            if path == "/api/editor-models/players":
                self.install_player_finder()
                return
            if path.startswith("/api/editor/") and path.endswith("/export"):
                self.start_export(path)
                return
            if path.startswith("/api/editor-exports/") and path.endswith("/render"):
                self.render_export(path.split("/")[-2], body)
                return
            if path.startswith("/api/editor-exports/") and path.endswith("/cancel"):
                self.send_json(HTTPStatus.OK, {"discarded": self.editor_exports.discard(path.split("/")[-2])})
                return
            if path.startswith("/api/editor-jobs/") and path.endswith("/cancel"):
                self.tracking_job(path.split("/")[-2], cancel=True)
                return
            if path.startswith("/api/editor/"):
                self.save_editor_annotations(path, body)
                return
            if path.startswith("/api/media/") and path.endswith("/save"):
                # Only a clip the engine cut for watching; the request names no paths.
                source = self.scratch_clip(path.split("/")[-2])
                if source is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "That clip is no longer available. Watch it again, then save it."})
                    return
                folder = Path(self.server.default_export_dir or self.store.data_dir / "exports")  # type: ignore[attr-defined]
                saved = save_clip_copy(source, folder, str(body.get("name") or ""))
                token = uuid.uuid4().hex
                self.server.saved_clips[token] = saved  # type: ignore[attr-defined]
                self.send_json(HTTPStatus.OK, {"saved": {"name": saved.name, "folder": str(saved.parent), "id": token}})
                return
            if path.startswith("/api/saved/") and path.endswith("/reveal"):
                saved = self.server.saved_clips.get(path.split("/")[-2])  # type: ignore[attr-defined]
                if saved is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "No saved clip to show"})
                    return
                user_folders.reveal_folder(saved.parent)
                self.send_json(HTTPStatus.OK, {"opened": True, "folder": str(saved.parent)})
                return
            if path.startswith("/api/jobs/") and path.endswith("/reveal"):
                # Only a finished job's own output folder; no paths come from the request.
                job = self.jobs.get(path.split("/")[-2])
                if job is None or job.get("status") != "complete" or job.get("dry_run"):
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "No finished export to show"})
                    return
                user_folders.reveal_folder(Path(job["output_dir"]))
                self.send_json(HTTPStatus.OK, {"opened": True, "folder": str(job["output_dir"])})
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
            self.reply_error(HTTPStatus.BAD_REQUEST, str(error), post=True)
        except Exception as error:
            self.reply_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error), post=True)

    def log_message(self, message: str, *args: Any) -> None:
        print(f"[clipmaker] {self.address_string()} {message % args}")


class LazyFrameCache:
    """Defers importing pandas until an analysis request arrives."""

    def __init__(self):
        self._cache = None
        self._lock = threading.Lock()

    def get(self, csv_path: str):
        with self._lock:
            if self._cache is None:
                from analysis_core import FrameCache
                self._cache = FrameCache()
        return self._cache.get(csv_path)


class EngineServer(ThreadingHTTPServer):
    # A page load opens a dozen connections at once. The standard backlog of 5
    # makes Windows refuse the extra ones outright (Linux and macOS queue them),
    # which left a reloaded page without its engine connection.
    request_queue_size = 128

    def server_bind(self) -> None:
        # HTTPServer.server_bind names the server with socket.getfqdn(), a
        # reverse lookup that can search the local network. On macOS that makes
        # the system ask the user to let "Python" find devices on local networks.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def create_server(host: str, port: int, data_dir: Path) -> ThreadingHTTPServer:
    server = EngineServer((host, port), ClipMakerHandler)
    server.match_store = MatchStore(data_dir)  # type: ignore[attr-defined]
    server.match_data_dir = data_dir / "match-data"  # type: ignore[attr-defined]
    server.jobs = JobManager()  # type: ignore[attr-defined]
    server.update_status = update_check.UpdateStatus(desktop=False)  # type: ignore[attr-defined]
    server.media_files = {}  # type: ignore[attr-defined]
    server.saved_clips = {}  # type: ignore[attr-defined]  # id -> clip saved to the user's folder
    server.analysis_frames = LazyFrameCache()  # type: ignore[attr-defined]
    server.default_export_dir = None  # type: ignore[attr-defined]  # main() sets the user's videos folder
    server.editor_clips = EditorClips(data_dir, _find_ffmpeg)  # type: ignore[attr-defined]
    server.tracking_jobs = None  # type: ignore[attr-defined]  # see Handler.tracking_jobs
    server.tracking_lock = threading.Lock()  # type: ignore[attr-defined]
    server.editor_exports = None  # type: ignore[attr-defined]  # see Handler.editor_exports
    store = server.match_store

    def recording_folder() -> Path:
        # Next to the user's exports (Videos/VizorPlay/Recordings), so the match video is theirs to keep.
        return Path(server.default_export_dir or data_dir / "exports") / "Recordings"

    def use_recording(project_id: str, path: Path, gaps: list[dict[str, float]]) -> None:
        project = store.get(project_id)
        if project is None or project.get("video_path"):
            return  # deleted, or given another video meanwhile: the file stays where it was saved
        saved = store.upsert({"id": project_id, "video_path": str(path), "video_name": path.name, "live_gaps": gaps})
        if saved.get("source") in ("coded", "both"):
            # Codes made while it recorded (L2) are in recording time, which is the joined video's time.
            write_coded_table(store, saved)

    server.live = LiveRecordings(data_dir / "live", _find_ffmpeg, recording_folder, use_recording)  # type: ignore[attr-defined]
    return server


def _find_ffmpeg() -> str:
    import video_encoder
    return video_encoder.find_ffmpeg()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / ".clipmaker-data")
    args = parser.parse_args()
    owner = os.environ.get("VIZORPLAY_OWNER_PID")
    owner_pid = int(owner) if owner else None
    if owner_pid is not None and (owner_pid <= 0 or owner_pid == os.getpid()):
        raise ValueError("Desktop owner must identify another live process")
    server = create_server(args.host, args.port, args.data_dir.resolve())
    server.desktop_owner_pid = owner_pid
    # Exports default to Videos/VizorPlay (Movies on macOS); tests point this elsewhere.
    override = os.environ.get("VIZORPLAY_EXPORT_DIR")
    server.default_export_dir = Path(override).resolve() if override else user_folders.default_export_dir()
    server.update_status = update_check.UpdateStatus(desktop=owner_pid is not None)
    if owner_pid is not None:
        watch_process_owner(owner_pid, server.shutdown)
    print(f"VizorPlay shared UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.live.close()  # its segments stay on disk and can be saved next time
        if not server.jobs.close():
            print("Export workers did not finish within the shutdown deadline", file=sys.stderr)
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
