"""
clipmaker_core.py  â€”  Shared backend logic for ClipMaker v1.2
Imported by ClipMaker.py (Home) and pages/1_Filtering.py
"""

import os
import threading
import time
import json
import pandas as pd

_FOOTBALL_GLOSSARY_CACHE = None

# =============================================================================
# PERIOD / TIMESTAMP HELPERS
# =============================================================================

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "FirstPeriodOfExtraTime": 3, "SecondPeriodOfExtraTime": 4,
    "PenaltyShootout": 5,
    1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
}

DEFAULT_FOOTBALL_GLOSSARY = {
    "skip_words": [],
    "skip_phrases": [],
    "intent_aliases": {},
}

INTENT_FLAG_TO_BOOL_COL = {
    "corners_only": "is_corner",
    "freekicks_only": "is_freekick",
    "headers_only": "is_header",
    "big_chances_only": "is_big_chance_shot",
    "big_chances_created_only": "is_big_chance",
    "crosses_only": "is_cross",
    "key_passes_only": "is_key_pass",
    "through_balls_only": "is_through_ball",
    "long_balls_only": "is_long_ball",
    "switches_only": "is_switch_of_play",
    "diagonals_only": "is_diagonal_long_ball",
    "fast_break_only": "is_fast_break",
    "touch_in_box_only": "is_touch_in_box",
    "box_entry_pass_only":          "is_box_entry_pass",
    "deep_completion_only":         "is_deep_completion",
    "box_entry_carry_only":         "is_box_entry_carry",
    "final_third_entry_pass_only":  "is_final_third_entry_pass",
    "final_third_entry_carry_only": "is_final_third_entry_carry",
}


def load_football_glossary():
    global _FOOTBALL_GLOSSARY_CACHE
    if _FOOTBALL_GLOSSARY_CACHE is not None:
        return _FOOTBALL_GLOSSARY_CACHE

    glossary = {
        "skip_words": list(DEFAULT_FOOTBALL_GLOSSARY["skip_words"]),
        "skip_phrases": list(DEFAULT_FOOTBALL_GLOSSARY["skip_phrases"]),
        "intent_aliases": dict(DEFAULT_FOOTBALL_GLOSSARY["intent_aliases"]),
    }

    glossary_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "football_glossary.json")
    try:
        with open(glossary_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        glossary["skip_words"].extend(loaded.get("skip_words", []))
        glossary["skip_phrases"].extend(loaded.get("skip_phrases", []))
        for key, phrases in loaded.get("intent_aliases", {}).items():
            glossary["intent_aliases"].setdefault(key, [])
            glossary["intent_aliases"][key].extend(phrases or [])
    except Exception:
        pass

    glossary["skip_words"] = sorted({str(v).strip().lower() for v in glossary["skip_words"] if str(v).strip()})
    glossary["skip_phrases"] = sorted({str(v).strip().lower() for v in glossary["skip_phrases"] if str(v).strip()})
    normalized_aliases = {}
    for key, phrases in glossary["intent_aliases"].items():
        normalized_aliases[key] = sorted({str(v).strip().lower() for v in phrases if str(v).strip()})
    glossary["intent_aliases"] = normalized_aliases

    _FOOTBALL_GLOSSARY_CACHE = glossary
    return glossary


def glossary_skip_words():
    return set(load_football_glossary().get("skip_words", []))


def glossary_skip_phrases():
    return set(load_football_glossary().get("skip_phrases", []))


def query_has_intent_alias(query_text, intent_key):
    q = (query_text or "").lower()
    aliases = load_football_glossary().get("intent_aliases", {}).get(intent_key, [])
    for alias in aliases:
        if alias and alias in q:
            return True
    return False

def to_seconds(timestamp):
    if not isinstance(timestamp, str):
        timestamp = str(timestamp)
    parts_raw = timestamp.strip().split(":")
    try:
        parts = [int(float(p)) for p in parts_raw]
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid timestamp: '{timestamp}' — use MM:SS or HH:MM:SS") from exc
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid timestamp: '{timestamp}' — use MM:SS or HH:MM:SS")

def assign_periods(df, period_column, fallback_row):
    if period_column:
        if period_column not in df.columns:
            raise ValueError(f"Column '{period_column}' not found. Available: {list(df.columns)}")
        df["resolved_period"] = df[period_column].map(PERIOD_MAP)
        unknown = df["resolved_period"].isna()
        if unknown.any():
            bad = df[unknown][period_column].unique()
            df = df[~unknown].copy()
        if df.empty:
            raise ValueError(f"No events remaining after dropping unrecognised periods.")
        df["resolved_period"] = df["resolved_period"].astype(int)
        return df
    if fallback_row is not None:
        df = df.reset_index(drop=True)
        df["resolved_period"] = (df.index >= fallback_row).astype(int) + 1
        return df
    raise ValueError("No period column or fallback row set.")

def match_clock_to_video_time(minute, second, period, period_start, period_offset):
    if period not in period_start:
        raise ValueError(f"Period {period} not in PERIOD_START_IN_VIDEO.")
    offset_min, offset_sec = period_offset[period]
    elapsed = (minute * 60 + second) - (offset_min * 60 + offset_sec)
    if elapsed < 0:
        raise ValueError(f"Negative elapsed at {minute}:{second:02d} P{period}.")
    return period_start[period] + elapsed

def monitor_file_progress(out_path, total_frames, fps, progress_queue, stop_event):
    for _ in range(20):
        if os.path.exists(out_path):
            break
        time.sleep(0.5)
    estimated_bytes = (total_frames / max(fps, 1)) * 250_000
    start_time = time.time()
    while not stop_event.is_set():
        try:
            current_bytes = os.path.getsize(out_path)
            frac = min(current_bytes / estimated_bytes, 0.99)
            current_frame = int(frac * total_frames)
            elapsed = time.time() - start_time
            progress_queue.put({
                "current": current_frame,
                "total": total_frames,
                "elapsed": elapsed,
                "phase": "assembly"
            })
        except Exception:
            pass
        time.sleep(0.5)

def merge_overlapping_windows(windows, min_gap):
    if not windows:
        return []
    merged = [list(windows[0])]
    for start, end, label, period in windows[1:]:
        prev = merged[-1]
        if start <= prev[1] + min_gap and period == prev[3]:
            prev[1] = max(prev[1], end)
            prev[2] = prev[2] + " + " + label
        else:
            merged.append([start, end, label, period])
    return [tuple(w) for w in merged]

def _effective_pitch_zone_series(df):
    """Return a Series of pitch zones relative to the away team's attacking direction.
    WhoScored's absolute y=0 is the away team's right touchline, so all events
    (both teams) must be mirrored (100 - y) to label zones from the away team's
    attacking perspective â€” the consistent reference frame used throughout.
    Falls back to the stored pitch_zone column if coordinate columns are absent."""
    from whoscored_scraper import _pitch_zone as _pz
    if all(c in df.columns for c in ["y", "team", "homeTeam"]):
        y_num = pd.to_numeric(df["y"], errors="coerce")
        flip_mask = df["homeTeam"].notna() & (df["homeTeam"] != "")
        effective_y = y_num.where(~flip_mask, 100 - y_num)
        return effective_y.apply(lambda v: _pz(v) if pd.notna(v) else "")
    if "pitch_zone" in df.columns:
        return df["pitch_zone"]
    return pd.Series([""] * len(df), index=df.index)


def ensure_computed_event_flags(df):
    """Backfill computed event flags for older CSVs that predate new columns."""
    if df is None or len(df) == 0:
        return df

    if (
        "is_switch_of_play" not in df.columns
        and all(c in df.columns for c in ["y", "endY", "is_long_ball"])
    ):
        from whoscored_scraper import _is_switch_of_play as _switch_of_play

        long_mask = df["is_long_ball"].astype(str).str.lower().isin(["true", "1", "yes"])
        start_y = pd.to_numeric(df["y"], errors="coerce")
        end_y = pd.to_numeric(df["endY"], errors="coerce")
        home_team = df["homeTeam"] if "homeTeam" in df.columns else pd.Series([""] * len(df), index=df.index)

        df["is_switch_of_play"] = [
            bool(is_long and pd.notna(sy) and pd.notna(ey) and _switch_of_play(sy, ey, ht))
            for is_long, sy, ey, ht in zip(long_mask.tolist(), start_y.tolist(), end_y.tolist(), home_team.fillna("").tolist())
        ]

    if (
        "is_diagonal_long_ball" not in df.columns
        and all(c in df.columns for c in ["x", "y", "endX", "endY", "is_long_ball"])
    ):
        from whoscored_scraper import _is_diagonal_long_ball as _diagonal_long_ball

        long_mask = df["is_long_ball"].astype(str).str.lower().isin(["true", "1", "yes"])
        start_x = pd.to_numeric(df["x"], errors="coerce")
        start_y = pd.to_numeric(df["y"], errors="coerce")
        end_x = pd.to_numeric(df["endX"], errors="coerce")
        end_y = pd.to_numeric(df["endY"], errors="coerce")

        df["is_diagonal_long_ball"] = [
            bool(is_long and pd.notna(sx) and pd.notna(sy) and pd.notna(ex) and pd.notna(ey)
                 and _diagonal_long_ball(sx, sy, ex, ey))
            for is_long, sx, sy, ex, ey in zip(
                long_mask.tolist(), start_x.tolist(), start_y.tolist(), end_x.tolist(), end_y.tolist()
            )
        ]

    if (
        "is_box_entry_pass" not in df.columns
        and all(c in df.columns for c in ["type", "x", "y", "endX", "endY"])
    ):
        from whoscored_scraper import _is_box_entry_pass as _box_entry_pass
        is_pass = df["type"] == "Pass"
        x = pd.to_numeric(df["x"], errors="coerce")
        y = pd.to_numeric(df["y"], errors="coerce")
        end_x = pd.to_numeric(df["endX"], errors="coerce")
        end_y = pd.to_numeric(df["endY"], errors="coerce")
        is_corner  = df["is_corner"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_corner" in df.columns else pd.Series([False] * len(df), index=df.index)
        is_freekick = df["is_freekick"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_freekick" in df.columns else pd.Series([False] * len(df), index=df.index)
        df["is_box_entry_pass"] = [
            bool(ip and pd.notna(sx) and pd.notna(sy) and pd.notna(ex) and pd.notna(ey)
                 and _box_entry_pass(sx, sy, ex, ey, ic, ifk))
            for ip, sx, sy, ex, ey, ic, ifk in zip(
                is_pass.tolist(), x.tolist(), y.tolist(), end_x.tolist(), end_y.tolist(),
                is_corner.tolist(), is_freekick.tolist()
            )
        ]

    if (
        "is_deep_completion" not in df.columns
        and all(c in df.columns for c in ["type", "endX", "endY", "outcomeType"])
    ):
        from whoscored_scraper import _is_deep_completion as _deep_completion
        is_pass  = df["type"] == "Pass"
        end_x    = pd.to_numeric(df["endX"], errors="coerce")
        end_y    = pd.to_numeric(df["endY"], errors="coerce")
        is_cross   = df["is_cross"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_cross" in df.columns else pd.Series([False] * len(df), index=df.index)
        is_corner  = df["is_corner"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_corner" in df.columns else pd.Series([False] * len(df), index=df.index)
        is_freekick = df["is_freekick"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_freekick" in df.columns else pd.Series([False] * len(df), index=df.index)
        outcome  = df["outcomeType"].fillna("")
        df["is_deep_completion"] = [
            bool(ip and pd.notna(ex) and pd.notna(ey)
                 and _deep_completion(ex, ey, ic, ico, ifk, oc))
            for ip, ex, ey, ic, ico, ifk, oc in zip(
                is_pass.tolist(), end_x.tolist(), end_y.tolist(), is_cross.tolist(),
                is_corner.tolist(), is_freekick.tolist(), outcome.tolist()
            )
        ]

    if (
        "is_box_entry_carry" not in df.columns
        and all(c in df.columns for c in ["type", "x", "y", "endX", "endY"])
    ):
        from whoscored_scraper import _is_box_entry_carry as _box_entry_carry
        is_carry = df["type"] == "Carry"
        x     = pd.to_numeric(df["x"], errors="coerce")
        y     = pd.to_numeric(df["y"], errors="coerce")
        end_x = pd.to_numeric(df["endX"], errors="coerce")
        end_y = pd.to_numeric(df["endY"], errors="coerce")
        df["is_box_entry_carry"] = [
            bool(ic and pd.notna(sx) and pd.notna(sy) and pd.notna(ex) and pd.notna(ey)
                 and _box_entry_carry(sx, sy, ex, ey))
            for ic, sx, sy, ex, ey in zip(
                is_carry.tolist(), x.tolist(), y.tolist(), end_x.tolist(), end_y.tolist()
            )
        ]

    if (
        "is_final_third_entry_pass" not in df.columns
        and all(c in df.columns for c in ["type", "x", "endX"])
    ):
        from whoscored_scraper import _is_final_third_entry_pass as _ft_entry_pass
        is_pass  = df["type"] == "Pass"
        x        = pd.to_numeric(df["x"], errors="coerce")
        end_x    = pd.to_numeric(df["endX"], errors="coerce")
        is_corner  = df["is_corner"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_corner" in df.columns else pd.Series([False] * len(df), index=df.index)
        is_freekick = df["is_freekick"].astype(str).str.lower().isin(["true", "1", "yes"]) if "is_freekick" in df.columns else pd.Series([False] * len(df), index=df.index)
        df["is_final_third_entry_pass"] = [
            bool(ip and pd.notna(sx) and pd.notna(ex)
                 and _ft_entry_pass(sx, ex, ic, ifk))
            for ip, sx, ex, ic, ifk in zip(
                is_pass.tolist(), x.tolist(), end_x.tolist(),
                is_corner.tolist(), is_freekick.tolist()
            )
        ]

    if (
        "is_final_third_entry_carry" not in df.columns
        and all(c in df.columns for c in ["type", "x", "endX"])
    ):
        from whoscored_scraper import _is_final_third_entry_carry as _ft_entry_carry
        is_carry = df["type"] == "Carry"
        x        = pd.to_numeric(df["x"], errors="coerce")
        end_x    = pd.to_numeric(df["endX"], errors="coerce")
        df["is_final_third_entry_carry"] = [
            bool(ic and pd.notna(sx) and pd.notna(ex)
                 and _ft_entry_carry(sx, ex))
            for ic, sx, ex in zip(
                is_carry.tolist(), x.tolist(), end_x.tolist()
            )
        ]

    return df


def apply_filters(df, config, log=None):
    df = ensure_computed_event_flags(df)
    original = len(df)

    if config.get("filter_types"):
        selected = config["filter_types"]
        if selected:
            before = len(df)
            available = df["type"].unique().tolist() if "type" in df.columns else []
            df = df[df["type"].isin(selected)]
            if log and len(df) == 0 and before > 0:
                log(f"  [WARN] filter_types={selected} matched 0/{before} events. Available types: {available[:15]}")

    if config.get("progressive_only"):
        prog_cols = [c for c in ["prog_pass", "prog_carry"] if c in df.columns]
        if prog_cols:
            mask = df[prog_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
            filtered = df[(mask > 0).any(axis=1)]
            if len(filtered) > 0:
                df = filtered
            elif log:
                log("  [WARN] progressive_only matched 0 events â€” ignoring flag")

    # Dedicated OR logic: all shots + key passes only (used by Attacking Chaos preset)
    if config.get("shots_and_key_passes_only") and "type" in df.columns and "is_key_pass" in df.columns:
        _shot_type_set = {"SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost", "BlockedShot", "AttemptSaved", "Attempt"}
        _shot_mask = df["type"].isin(_shot_type_set)
        _kp_mask   = (df["type"] == "Pass") & df["is_key_pass"].astype(str).str.lower().isin(["true", "1", "yes"])
        df = df[_shot_mask | _kp_mask]

    def _apply_qualifier(df, col):
        """Apply a qualifier filter strictly to rows where the qualifier is true."""
        is_true = df[col].astype(str).str.lower().isin(["true", "1", "yes"])
        if not is_true.any():
            return df  # qualifier has no True values â€” ignore it
        return df[is_true]

    if config.get("key_passes_only") and not config.get("shots_and_key_passes_only") and "is_key_pass" in df.columns:
        df = _apply_qualifier(df, "is_key_pass")

    # Special case: if both corners_only and freekicks_only are set, use OR logic
    if config.get("corners_only") and config.get("freekicks_only"):
        if "is_corner" in df.columns and "is_freekick" in df.columns:
            mask_corner = df["is_corner"].astype(str).str.lower().isin(["true", "1", "yes"])
            mask_freekick = df["is_freekick"].astype(str).str.lower().isin(["true", "1", "yes"])
            if (mask_corner | mask_freekick).any():
                df = df[mask_corner | mask_freekick]
    else:
        for flag, col in [
            ("crosses_only",             "is_cross"),
            ("long_balls_only",          "is_long_ball"),
            ("switches_only",            "is_switch_of_play"),
            ("diagonals_only",           "is_diagonal_long_ball"),
            ("through_balls_only",       "is_through_ball"),
            ("corners_only",             "is_corner"),
            ("freekicks_only",           "is_freekick"),
            ("headers_only",             "is_header"),
            ("big_chances_only",         "is_big_chance_shot"),
            ("big_chances_created_only", "is_big_chance"),
            ("own_goals_only",           "is_own_goal"),
            ("gk_saves_only",            "is_gk_save"),
            ("penalties_only",           "is_penalty"),
            ("volleys_only",             "is_volley"),
            ("chipped_only",             "is_chipped"),
            ("direct_from_corner_only",  "is_direct_from_corner"),
            ("left_foot_only",           "is_left_foot"),
            ("right_foot_only",          "is_right_foot"),
            ("fast_break_only",          "is_fast_break"),
            ("touch_in_box_only",        "is_touch_in_box"),
            ("assist_throughball_only",  "is_assist_throughball"),
            ("assist_cross_only",        "is_assist_cross"),
            ("assist_corner_only",       "is_assist_corner"),
            ("assist_freekick_only",     "is_assist_freekick"),
            ("intentional_assists_only", "is_intentional_assist"),
            ("yellow_cards_only",        "is_yellow_card"),
            ("red_cards_only",           "is_red_card"),
            ("second_yellow_only",       "is_second_yellow"),
            ("nutmegs_only",             "is_nutmeg"),
            ("success_in_box_only",      "is_success_in_box"),
            ("box_entry_pass_only",          "is_box_entry_pass"),
            ("deep_completion_only",         "is_deep_completion"),
            ("box_entry_carry_only",         "is_box_entry_carry"),
            ("final_third_entry_pass_only",  "is_final_third_entry_pass"),
            ("final_third_entry_carry_only", "is_final_third_entry_carry"),
        ]:
            if config.get(flag) and col in df.columns:
                df = _apply_qualifier(df, col)

    if config.get("successful_only") and "outcomeType" in df.columns:
        df = df[df["outcomeType"] == "Successful"]
    if config.get("unsuccessful_only") and "outcomeType" in df.columns:
        df = df[df["outcomeType"] == "Unsuccessful"]

    if config.get("xt_min") is not None and "xT" in df.columns:
        xt_min = config["xt_min"]
        if xt_min > 0:
            df = df[pd.to_numeric(df["xT"], errors="coerce").fillna(0) >= xt_min]

    if config.get("minute_min") is not None and "minute" in df.columns:
        df = df[pd.to_numeric(df["minute"], errors="coerce").fillna(0) >= config["minute_min"]]
    if config.get("minute_max") is not None and "minute" in df.columns:
        df = df[pd.to_numeric(df["minute"], errors="coerce").fillna(0) <= config["minute_max"]]

    if config.get("top_n") and "xT" in df.columns:
        n = config["top_n"]
        df = df.copy()
        df["_xt_num"] = pd.to_numeric(df["xT"], errors="coerce").fillna(0)
        df = df.nlargest(n, "_xt_num").drop(columns=["_xt_num"])

    if config.get("pitch_zone_filter"):
        zone_series = _effective_pitch_zone_series(df)
        zone_filter = config["pitch_zone_filter"]
        combined_pitch_zones = {
            "Entire Left Side": ["Left Wing", "Left Half Space"],
            "Entire Right Side": ["Right Wing", "Right Half Space"],
        }
        if zone_filter in combined_pitch_zones:
            df = df[zone_series.isin(combined_pitch_zones[zone_filter])]
        else:
            df = df[zone_series == zone_filter]

    if config.get("depth_zone_filter") and "depth_zone" in df.columns:
        df = df[df["depth_zone"] == config["depth_zone_filter"]]

    return df, original - len(df)


# =============================================================================
# MAIN CLIP-MAKER ENGINE
# =============================================================================

def run_clip_maker(config, log_queue, progress_queue):
    def log(msg):
        log_queue.put({"type": "log", "msg": msg})
    def prog(current, total, elapsed):
        progress_queue.put({"current": current, "total": total, "elapsed": elapsed})

    try:
        df = pd.read_csv(config["data_file"])
        for col in ["minute", "second", "type"]:
            if col not in df.columns:
                raise ValueError(f"CSV missing column: '{col}'")

        split_video = config.get("split_video", False)

        period_start = {
            1: to_seconds(config["half1_time"]),
            2: to_seconds(config["half2_time"]),
        }
        if config["half3_time"].strip():
            period_start[3] = to_seconds(config["half3_time"])
        if config["half4_time"].strip():
            period_start[4] = to_seconds(config["half4_time"])
        if config.get("half5_time", "").strip():
            period_start[5] = to_seconds(config["half5_time"])

        period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0), 5: (120, 0)}

        fallback = config["fallback_row"]
        period_col = config["period_column"] or None
        df = assign_periods(df, period_col, fallback)

        half_filter = config.get("half_filter", "Both halves")
        if half_filter == "1st half only":
            df = df[df["resolved_period"] == 1]
            log("Filtering to 1st half only.")
        elif half_filter == "2nd half only":
            df = df[df["resolved_period"] == 2]
            log("Filtering to 2nd half only.")

        # Log active filters for debugging
        active_filters = []
        if config.get("filter_types"):
            active_filters.append(f"types={config['filter_types']}")
        for flag in ["key_passes_only", "crosses_only", "through_balls_only",
                      "corners_only", "freekicks_only", "headers_only",
                      "big_chances_only", "long_balls_only", "own_goals_only",
                      "successful_only", "unsuccessful_only", "progressive_only",
                      "penalties_only", "volleys_only", "chipped_only",
                      "direct_from_corner_only", "left_foot_only", "right_foot_only",
                      "fast_break_only", "touch_in_box_only",
                      "assist_throughball_only", "assist_cross_only",
                      "assist_corner_only", "assist_freekick_only",
                      "intentional_assists_only", "yellow_cards_only",
                      "red_cards_only", "second_yellow_only",
                      "nutmegs_only", "success_in_box_only"]:
            if config.get(flag):
                active_filters.append(flag)
        if active_filters:
            log(f"Active filters: {', '.join(active_filters)}")

        df, filtered_count = apply_filters(df, config, log=log)
        if filtered_count > 0:
            log(f"Filters removed {filtered_count} events.")

        timestamps = []
        for _, row in df.iterrows():
            try:
                ts = match_clock_to_video_time(
                    int(row["minute"]), int(row["second"]),
                    int(row["resolved_period"]), period_start, period_offset
                )
                timestamps.append(ts)
            except ValueError as e:
                log(f"  WARNING: {e}")
                timestamps.append(None)

        df["video_timestamp"] = timestamps
        df = df.dropna(subset=["video_timestamp"]).sort_values("video_timestamp")

        raw_windows = []
        for _, row in df.iterrows():
            ts = row["video_timestamp"]
            period = int(row["resolved_period"])
            label = f"{row['type']} @ {int(row['minute'])}:{int(row['second']):02d} (P{period})"
            raw_windows.append((ts - config["before_buffer"], ts + config["after_buffer"], label, period))

        windows = merge_overlapping_windows(raw_windows, config["min_gap"])
        log(f"Found {len(df)} events â†’ {len(windows)} clips after merging.\n")

        if config["dry_run"]:
            for i, (s, e, lbl, p) in enumerate(windows, 1):
                log(f"  Clip {i:02d}: {s:.1f}s â€“ {e:.1f}s  ({e-s:.0f}s)  |  {lbl}")
            log("\n[OK] DRY RUN complete.")
            log_queue.put({"type": "done"})
            return

        def get_ffmpeg_binary():
            import shutil
            cmd = shutil.which("ffmpeg")
            if cmd:
                return cmd
            try:
                from moviepy.config import FFMPEG_BINARY
                if os.path.exists(FFMPEG_BINARY):
                    return FFMPEG_BINARY
            except Exception:
                pass
            raise ValueError("FFmpeg not found. Please ensure FFmpeg is installed.")

        def get_video_duration(path, ffmpeg_bin):
            import subprocess, re
            r = subprocess.run([ffmpeg_bin, "-i", path], capture_output=True, text=True)
            output = r.stdout + r.stderr
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", output)
            if not m:
                raise ValueError(f"Could not determine duration of {path}")
            return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

        def cut_clip_ffmpeg(ffmpeg_bin, src_path, start, end, out_path):
            import subprocess
            duration = end - start
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", str(start),
                "-i", src_path,
                "-t", str(duration),
                "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-threads", "0",
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                out_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise ValueError(f"FFmpeg error cutting clip: {result.stderr[-500:]}")

        def cut_and_concat_ffmpeg(ffmpeg_bin, clip_specs, out_path, progress_queue, start_time):
            import subprocess, tempfile
            tmp_dir = tempfile.mkdtemp()
            tmp_files = []
            total = len(clip_specs)

            for i, (src, start, end) in enumerate(clip_specs, 1):
                tmp_path = os.path.join(tmp_dir, f"part_{i:04d}.mp4")
                if start is None and end is None:
                    import shutil as _shutil
                    _shutil.copy2(src, tmp_path)
                else:
                    cut_clip_ffmpeg(ffmpeg_bin, src, start, end, tmp_path)
                tmp_files.append(tmp_path)
                elapsed = time.time() - start_time
                progress_queue.put({"current": i, "total": total, "elapsed": elapsed, "phase": "clips"})

            list_path = os.path.join(tmp_dir, "concat.txt")
            with open(list_path, "w", encoding="utf-8") as f:
                for p in tmp_files:
                    p_safe = p.replace(os.sep, "/")
                    f.write(f"file '{p_safe}'\n")

            cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                out_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise ValueError(f"FFmpeg concat error: {result.stderr[-500:]}")

            for p in tmp_files:
                try: os.remove(p)
                except: pass
            try: os.remove(list_path)
            except: pass
            try: os.rmdir(tmp_dir)
            except: pass

        log("Loading video...")
        ffmpeg_bin = get_ffmpeg_binary()
        video1_path = config["video_file"].strip().strip("\"'")
        video1_duration = get_video_duration(video1_path, ffmpeg_bin)
        log(f"  Video 1 duration: {video1_duration:.2f}s")

        if split_video and config.get("video2_file"):
            video2_path_str = config["video2_file"].strip().strip("\"'")
            video2_duration = get_video_duration(video2_path_str, ffmpeg_bin)
            log(f"  Video 2 duration: {video2_duration:.2f}s")
            log("  Two-file mode: 1st half from file 1, 2nd half from file 2.")
        else:
            video2_path_str = None
            video2_duration = None

        def get_src_and_duration(period):
            if split_video and video2_path_str and period >= 2:
                return video2_path_str, video2_duration
            return video1_path, video1_duration

        out_dir = config["output_dir"]
        os.makedirs(out_dir, exist_ok=True)

        total_clips = len(windows)
        start_time = time.time()
        if config["individual_clips"]:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # Build clip spec list first
            clip_specs_indiv = []
            for i, (start, end, label, period) in enumerate(windows, 1):
                src, src_dur = get_src_and_duration(period)
                s = max(0, start)
                e = min(src_dur, end)
                if e <= s:
                    log(f"  SKIPPED clip {i:02d}: outside video duration {src_dur:.1f}s")
                    continue
                actions = [pt.split(" @")[0].strip() for pt in label.split(" + ")]
                dominant = max(set(actions), key=actions.count).replace(" ", "_")
                filename = f"{i:02d}_{dominant}.mp4"
                filepath = os.path.join(out_dir, filename)
                clip_specs_indiv.append((i, src, s, e, label, filepath))

            saved = []
            completed_count = [0]

            def _cut_one(spec):
                i, src, s, e, label, filepath = spec
                cut_clip_ffmpeg(ffmpeg_bin, src, s, e, filepath)
                return spec

            log(f"  Cutting {len(clip_specs_indiv)} clips in parallel (up to 4 workers)...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(_cut_one, spec): spec for spec in clip_specs_indiv}
                for fut in as_completed(futures):
                    spec = futures[fut]
                    i, src, s, e, label, filepath = spec
                    try:
                        fut.result()
                    except Exception as ex:
                        log(f"  ERROR clip {i:02d}: {ex}")
                        continue

                    completed_count[0] += 1
                    log(f"  Rendered {i:02d}/{total_clips}: {os.path.basename(filepath)}")

                    saved.append(filepath)
                    prog(completed_count[0], total_clips, time.time() - start_time)

            log(f"\n\u2713 {len(saved)} clips saved to: {os.path.abspath(out_dir)}/")
        else:
            clip_specs = []
            for i, (start, end, label, period) in enumerate(windows, 1):
                src, src_dur = get_src_and_duration(period)
                s = max(0, start)
                e = min(src_dur, end)
                if e <= s:
                    log(f"  SKIPPED clip {i:02d}: outside video duration {src_dur:.1f}s")
                    continue
                clip_specs.append((src, s, e))

            if not clip_specs:
                log("\n[ERR] No matching events found â€” nothing to clip.")
                progress_queue.put({"error": "No matching events found. Try a different filter or check your CSV data."})
                return

            total_dur = sum(e - s for _, s, e in clip_specs)
            log(f"Assembling {len(clip_specs)} clips ({total_dur:.1f}s)...")
            out_path = os.path.join(out_dir, config["output_filename"])

            assembly_start = time.time()
            stop_event = threading.Event()
            fps_est = 25
            total_frames = int(total_dur * fps_est)
            monitor_thread = threading.Thread(
                target=monitor_file_progress,
                args=(out_path, total_frames, fps_est, progress_queue, stop_event),
                daemon=True
            )
            monitor_thread.start()
            cut_and_concat_ffmpeg(ffmpeg_bin, clip_specs, out_path, progress_queue, assembly_start)
            stop_event.set()
            monitor_thread.join()
            log(f"\n\u2713 Saved to: {out_path}")

        log_queue.put({"type": "done"})

    except Exception as e:
        log(f"\n[ERR] ERROR: {e}")
        log_queue.put({"type": "error"})


# =============================================================================
# AI â€” GROQ PROXY
# =============================================================================

GROQ_PROXY_URL = "https://groq-proxy-eight.vercel.app/api/chat"

GROQ_CHAT_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "moonshotai/kimi-k2-instruct",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
]

def ping_proxy():
    import urllib.request
    try:
        req = urllib.request.Request(
            GROQ_PROXY_URL,
            data=json.dumps({
                "model": GROQ_CHAT_MODELS[0],
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "temperature": 0
            }).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "ClipMaker/1.2"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass

def call_llm(system_prompt, user_message):
    import urllib.request, urllib.error, random, time as _time
    preferred = GROQ_CHAT_MODELS[0]
    rest = GROQ_CHAT_MODELS[1:]
    random.shuffle(rest)
    models_to_try = [preferred] + rest

    last_error = None
    for model in models_to_try:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message}
            ],
            "max_tokens": 1000,
            "temperature": 0
        }).encode()
        req = urllib.request.Request(
            GROQ_PROXY_URL,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "ClipMaker/1.2"},
            method="POST"
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                if e.code == 429 or "rate_limit" in body.lower():
                    last_error = f"Rate limit on {model}"
                    break
                raise ValueError(f"Proxy/API error {e.code} on {model}: {body[:300]}")
            except Exception as e:
                last_error = str(e)
                if attempt < 1:
                    _time.sleep(2)
                    continue
                break

    raise ValueError("Could not reach the AI server after multiple attempts. Check your internet connection and try again.")


def read_csv_safe(path):
    # Cache by (path, modification time) so the cache busts if the file changes
    try:
        _mtime = os.path.getmtime(path)
    except OSError:
        _mtime = 0
    return _read_csv_cached(path, _mtime)

@__import__("functools").lru_cache(maxsize=16)
def _read_csv_cached(path, _mtime):
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1")

    bool_cols = [c for c in df.columns if c.startswith("is_") or c in ("prog_pass", "prog_carry")]
    for col in bool_cols:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip().str.upper().map(
                {"TRUE": True, "FALSE": False, "1": True, "0": False, "YES": True, "NO": False}
            ).fillna(False).astype(bool)
    df = ensure_computed_event_flags(df)
    return df


def fuzzy_correct_player(name, df):
    from difflib import SequenceMatcher
    import unicodedata, re

    def _strip(s):
        return "".join(c for c in unicodedata.normalize("NFD", str(s))
                       if unicodedata.category(c) != "Mn").lower().strip()

    def _clean(s):
        """Strip accents, possessives, trailing plurals, and punctuation."""
        s = _strip(s)
        s = re.sub(r"[''`]s[CLR]\b", "", s)       # possessive 's
        s = re.sub(r"[^a-z0-9\s]", "", s)     # non-alphanumeric
        return s.strip()

    if "playerName" not in df.columns:
        return None, None

    # Skip common football/query terms â€” single words AND multi-word phrases
    SKIP_WORDS = {
        "show", "shots", "shot", "passes", "pass", "goals", "goal", "saves",
        "save", "tackle", "tackles", "cards", "card", "fouls", "foul",
        "cross", "crosses", "header", "headers", "corner", "corners",
        "dribble", "dribbles", "carry", "carries", "touch", "touches",
        "block", "blocks", "interception", "interceptions", "clearance", "clearances",
        "claim", "claims", "keeper", "goalkeeper", "gk",
        "recovery", "recoveries", "duel", "duels", "challenge", "challenges",
        "dispossessed", "offside", "penalty", "penalties",
        "punch", "punches", "substitution", "substitutions", "sub", "subs",
        "pickup", "sweeper", "set", "piece", "pieces", "setpiece", "setpieces",
        "first", "second", "half", "halves", "both", "team", "teams",
        "player", "players", "all", "the", "for", "from", "with",
        "most", "many", "how", "who", "what", "which", "where", "when",
        "that", "this", "make", "clips", "clip", "reel", "highlight",
        "successful", "unsuccessful", "failed", "completed", "missed",
        "long", "short", "ball", "balls", "free", "kick", "kicks",
        "chance", "chances", "big", "key", "through", "progressive",
        "and", "not", "only", "every", "each", "any", "some",
        "take", "ons", "aerial", "aerials", "minutes", "minute",
        "events", "event", "data", "about", "before", "after",
        "had", "has", "have", "did", "does", "was", "were", "been",
        "got", "get", "made", "gave", "give", "won", "lost",
        "best", "worst", "more", "less", "than",
    }

    SKIP_PHRASES = {
        "show me", "me all", "all through", "through balls", "through ball",
        "key passes", "key pass", "take ons", "take on", "long balls",
        "long ball", "free kicks", "free kick", "big chances", "big chance",
        "all key", "all long", "all free", "all big",
        "show all", "me show", "make clips", "ask about",
        "set piece", "set pieces",
    }

    SKIP_WORDS |= glossary_skip_words()
    SKIP_PHRASES |= glossary_skip_phrases()

    name_cleaned = _clean(name)
    if not name_cleaned or len(name_cleaned) < 2:
        return None, None
    if name_cleaned in SKIP_WORDS or name_cleaned in SKIP_PHRASES:
        return None, None
    # Also check if ALL words in the input are skip words
    words = name_cleaned.split()
    if all(w in SKIP_WORDS for w in words):
        return None, None

    # Dynamically skip team names from the data
    if "team" in df.columns:
        team_words = set()
        for t in df["team"].dropna().unique():
            for w in _clean(t).split():
                if len(w) >= 3:
                    team_words.add(w)
            team_words.add(_clean(t))
        if name_cleaned in team_words:
            return None, None
        if all(w in (SKIP_WORDS | team_words) for w in words):
            return None, None

    all_players  = df["playerName"].dropna().unique().tolist()
    all_cleaned  = [_clean(p) for p in all_players]

    is_multi_word = len(words) > 1

    # 1. Exact full-string substring match (e.g. "enzo" in "enzo fernandez")
    for i, pc in enumerate(all_cleaned):
        if name_cleaned in pc or pc in name_cleaned:
            return all_players[i], name

    # 2. Word-level match: input word matches a word in the player name
    #    Skip words in SKIP_WORDS even when part of a multi-word input
    for i, pc in enumerate(all_cleaned):
        parts = pc.split()
        for np_ in words:
            if len(np_) < 3 or np_ in SKIP_WORDS:
                continue
            for pp in parts:
                if np_ == pp:
                    return all_players[i], name
                # Substring within a name part only if input is 5+ chars
                if len(np_) >= 5 and (np_ in pp or pp in np_):
                    return all_players[i], name

    # 3. Strip trailing 's' for plurals (e.g. "hills" â†’ "hill")
    for w in words:
        if w in SKIP_WORDS:
            continue
        if w.endswith("s") and len(w) > 3:
            singular = w[:-1]
            if singular in SKIP_WORDS:
                continue
            for i, pc in enumerate(all_cleaned):
                parts = pc.split()
                for part in parts:
                    if singular == part:
                        return all_players[i], name

    # 4. Fuzzy match with strict thresholds
    #    Filter out skip words from input before comparing
    non_skip_words = [w for w in words if w not in SKIP_WORDS and len(w) >= 3]
    if not non_skip_words:
        return None, None

    search_term = " ".join(non_skip_words)
    best_player = None
    best_ratio  = 0

    for i, pc in enumerate(all_cleaned):
        if is_multi_word:
            # Multi-word: compare cleaned search term against full player name
            ratio = SequenceMatcher(None, search_term, pc).ratio()
        else:
            # Single word: compare against full name AND individual parts
            ratio = SequenceMatcher(None, search_term, pc).ratio()
            for part in pc.split():
                if len(part) >= 3:
                    part_ratio = SequenceMatcher(None, search_term, part).ratio()
                    ratio = max(ratio, part_ratio)

        if ratio > best_ratio:
            best_ratio  = ratio
            best_player = all_players[i]

    # Stricter thresholds to avoid false positives
    # Short inputs (<=4 chars) need very high similarity to match
    if len(search_term) <= 3:
        return None, None  # 3-char inputs must match via exact/substring, never fuzzy
    min_ratio = 0.7 if len(search_term) <= 5 else 0.6
    if best_player and best_ratio >= min_ratio:
        return best_player, name

    return None, None


def query_data(question, df):
    """Hybrid query engine: deterministic pre-filtering + LLM reads the data.
    Filters the CSV by player/team/half/type/boolean using regex, then sends
    the filtered data to the LLM to answer the question in plain English."""
    import re, unicodedata

    df = ensure_computed_event_flags(df)
    q = question.lower().strip()

    # â”€â”€ 1. Detect boolean filters (through balls, key passes, etc.) â”€â”€
    BOOL_PATTERNS = {
        "is_through_ball":       [r"\bthrough\s*ball"],
        "is_long_ball":          [r"\blong\s*ball"],
        "is_key_pass":           [r"\bkey\s*pass", r"\bchance[sd][CLR]\s*creat", r"\bcreat\w*\b.*\bchance"],
        "is_cross":              [r"\bcrosses?\b"],
        "is_header":             [r"\bheader"],
        "is_corner":             [r"\bcorner"],
        "is_freekick":           [r"\bfree\s*kick"],
        "is_switch_of_play":          [r"\bswitch(?:es)?\s+of\s+play\b", r"\bswitch(?:es)?\b"],
        "is_diagonal_long_ball":      [r"\bdiagonal(?:s)?\b", r"\blong\s+diagonal(?:s)?\b", r"\braking\s+diagonal(?:s)?\b"],
        "is_box_entry_pass":          [r"\bbox\s*entry\s*pass", r"\bpass(?:es)?\s+into\s+(?:the\s+)?box", r"\bpass(?:es)?\s+(?:that\s+)?enter(?:s|ing)?\s+(?:the\s+)?box"],
        "is_deep_completion":         [r"\bdeep\s*completion"],
        "is_box_entry_carry":         [r"\bbox\s*entry\s*carr(?:y|ies)", r"\bcarr(?:y|ies)\s+into\s+(?:the\s+)?box", r"\bcarr(?:y|ies)\s+(?:that\s+)?enter(?:s|ing)?\s+(?:the\s+)?box"],
        "is_final_third_entry_pass":  [r"\bfinal\s*third\s*entry\s*pass", r"\bpass(?:es)?\s+into\s+(?:the\s+)?final\s+third", r"\bfinal\s*third\s+pass\s*entr"],
        "is_final_third_entry_carry": [r"\bfinal\s*third\s*entry\s*carr", r"\bcarr(?:y|ies)\s+into\s+(?:the\s+)?final\s+third", r"\bfinal\s*third\s+carr(?:y|ies)\s*entr"],
        "is_big_chance_shot":    [r"\bbig\s*chance"],
        "is_big_chance":         [r"\bbig\s*chance[sd][CLR]\s*creat", r"\bcreat\w*\b.*\bbig\s*chance"],
        "is_gk_save":            [r"\bgk\s*save", r"\bkeeper\s*save"],
        "is_penalty":            [r"\bpenalty\s*kick|\bspot\s*kick|\bpenalty\s*shot"],
        "is_volley":             [r"\bvolley"],
        "is_chipped":            [r"\bchip(ped)?\b|\blob(bed)?\b"],
        "is_direct_from_corner": [r"\bdirect\s*from\s*corner|\bcorner\s*goal"],
        "is_left_foot":          [r"\bleft\s*foot|\bleft\s*footed"],
        "is_right_foot":         [r"\bright\s*foot|\bright\s*footed"],
        "is_fast_break":         [r"\bfast\s*break|\bcounter\s*attack|\bon\s*the\s*break"],
        "is_touch_in_box":       [r"\btouch\s*in\s*(the\s*)?box|\bin\s*the\s*box"],
        "is_assist_throughball": [r"\bassist.*through\s*ball|\bthrough\s*ball.*assist"],
        "is_assist_cross":       [r"\bassist.*cross|\bcross.*assist"],
        "is_assist_corner":      [r"\bassist.*corner|\bcorner.*assist"],
        "is_assist_freekick":    [r"\bassist.*free\s*kick|\bfree\s*kick.*assist"],
        "is_intentional_assist": [r"\bintentional\s*assist|\bdeliberate\s*assist"],
        "is_yellow_card":        [r"\byellow\s*card|\bbooked"],
        "is_red_card":           [r"\bred\s*card|\bsent\s*off|\bsending\s*off"],
        "is_second_yellow":      [r"\bsecond\s*yellow|\bdouble\s*yellow"],
        "is_nutmeg":             [r"\bnutmeg"],
        "is_success_in_box":     [r"\bsuccess.*in\s*(the\s*)?box|\btake.?on.*in\s*(the\s*)?box"],
    }

    TYPE_PATTERNS = {
        "shots":          (r"\bshot", ["MissedShot", "SavedShot", "Goal", "ShotOnPost", "BlockedShot"]),
        "goals":          (r"\bgoal", ["Goal"]),
        "passes":         (r"\bpasses?\b", ["Pass"]),
        "tackles":        (r"\btackle", ["Tackle"]),
        "take_ons":       (r"\btake\s*on|\bdribble", ["TakeOn"]),
        "aerials":        (r"\baerial", ["Aerial"]),
        "carries":        (r"\bcarr(y|ies)\b", ["Carry"]),
        "clearances":     (r"\bclearance", ["Clearance"]),
        "interceptions":  (r"\bintercept", ["Interception"]),
        "fouls":          (r"\bfoul", ["Foul"]),
        "saves":          (r"\bsaves?\b(?!d)", ["Save"]),
        "cards":          (r"\bcard|\byellow|\bred\b", ["Card"]),
        "blocks":         (r"\bblocks?\b", ["Block", "BlockedPass", "BlockedShot"]),
        "recoveries":     (r"\brecovery|\brecoveries|\brecover", ["BallRecovery"]),
        "duels":          (r"\bduel", ["Tackle", "TakeOn", "Aerial", "Challenge", "ShieldBallOpp"]),
        "challenges":     (r"\bchallenge", ["Challenge"]),
        "ball_touches":   (r"\bball\s*touch|\btouches?\b", ["BallTouch"]),
        "dispossessed":   (r"\bdispossess", ["Dispossessed"]),
        "offside":        (r"\boffside", ["OffsideGiven", "OffsidePass", "OffsideProvoked"]),
        "penalty":        (r"\bpenalt(y|ies)", ["PenaltyFaced"]),
        "punch":          (r"\bpunches?\b", ["Punch"]),
        "substitutions":  (r"\bsubs?(titutions?)?\b|\bcoming\s*on|\bcoming\s*off", ["SubstitutionOn", "SubstitutionOff"]),
        "keeper_actions": (r"\bgoalkeeper\b|\bkeeper\b(?!\s*save)|\bgk\b", ["Claim", "KeeperPickup", "KeeperSweeper", "Punch"]),
        "claims":         (r"\bclaim", ["Claim"]),
        "keeper_pickup":  (r"\bkeeper\s*pick\s*up|\bpick\s*up\b", ["KeeperPickup"]),
        "keeper_sweeper": (r"\bsweeper\b|\bkeeper\s*sweep", ["KeeperSweeper"]),
        "corners_awarded":(r"\bcorner\s*awarded", ["CornerAwarded"]),
    }

    active_bools = {}
    for col, patterns in BOOL_PATTERNS.items():
        if col in df.columns:
            for pat in patterns:
                if re.search(pat, q):
                    active_bools[col] = True
                    break

    for flag_name, col in INTENT_FLAG_TO_BOOL_COL.items():
        if col in df.columns and query_has_intent_alias(q, flag_name):
            active_bools[col] = True

    # "big chances created" matches both â€” "created" is more specific, wins
    if "is_big_chance" in active_bools and "is_big_chance_shot" in active_bools:
        del active_bools["is_big_chance_shot"]

    # "big chances created" also matches is_key_pass via "chance created" â€”
    # if is_big_chance matched, it's more specific, remove is_key_pass
    if "is_big_chance" in active_bools and "is_key_pass" in active_bools:
        del active_bools["is_key_pass"]

    # "set piece(s)" means the restart family, which in this dataset maps to
    # corners and free kicks. Use both flags together so downstream filtering
    # applies OR logic rather than collapsing to unrelated event types.
    if re.search(r"\bset[\s-]*pieces?\b", q) or query_has_intent_alias(q, "set_pieces"):
        if "is_corner" in df.columns:
            active_bools["is_corner"] = True
        if "is_freekick" in df.columns:
            active_bools["is_freekick"] = True

    active_types = []
    for name, (pat, types) in TYPE_PATTERNS.items():
        if re.search(pat, q):
            for t in types:
                if t in df["type"].values:
                    active_types.append(t)

    # â”€â”€ 2. Detect players â”€â”€
    resolved_players = []
    fragments = re.split(r"[''`\s,&+]+", q)
    pairs = [f"{fragments[i]} {fragments[i+1]}" for i in range(len(fragments)-1)]
    seen = set()
    for frag in pairs + fragments:
        if len(frag) < 3:
            continue
        match, _ = fuzzy_correct_player(frag, df)
        if match and match not in seen:
            resolved_players.append(match)
            seen.add(match)

    # â”€â”€ 3. Detect team filter â”€â”€
    teams = df["team"].dropna().unique().tolist() if "team" in df.columns else []
    active_team = None
    for team in teams:
        if team.lower() in q:
            active_team = team
            break

    # â”€â”€ 4. Detect half filter â”€â”€
    active_half = None
    if re.search(r"\b1st\s*half|\bfirst\s*half", q):
        active_half = "FirstHalf"
    elif re.search(r"\b2nd\s*half|\bsecond\s*half", q):
        active_half = "SecondHalf"

    # â”€â”€ 5. Detect outcome filter â”€â”€
    # "won" in "who won the most X" or "won the most X" is an aggregate question,
    # not an outcome filter â€” suppress successful_only in that context.
    _won_is_agg = bool(re.search(r"\bwho\b.*\bwon\b|\bwon\b.*\bmost\b", q))
    successful_only = bool(re.search(r"\bsuccessful\b|\bcompleted\b|\bwin\b", q)) or (
        bool(re.search(r"\bwon\b", q)) and not _won_is_agg
    )
    unsuccessful_only = bool(re.search(r"\bunsuccessful\b|\bfailed\b|\bmissed\b|\blost\b|\blose\b", q))

    # â”€â”€ 6. Apply deterministic filters â”€â”€
    result = df.copy()

    if resolved_players:
        def _sa(s):
            return "".join(c for c in unicodedata.normalize("NFD", str(s))
                           if unicodedata.category(c) != "Mn").lower()
        stripped = [_sa(p) for p in resolved_players]
        result = result[result["playerName"].apply(
            lambda x: _sa(x) in stripped if pd.notna(x) else False)]

    if active_team:
        result = result[result["team"] == active_team]

    if active_half and "period" in result.columns:
        result = result[result["period"] == active_half]

    if {"is_corner", "is_freekick"}.issubset(active_bools.keys()) and all(
        col in result.columns for col in ("is_corner", "is_freekick")
    ):
        mask_corner = result["is_corner"].astype(str).str.lower().isin(["true", "1", "yes"])
        mask_freekick = result["is_freekick"].astype(str).str.lower().isin(["true", "1", "yes"])
        result = result[mask_corner | mask_freekick]
        active_bools.pop("is_corner", None)
        active_bools.pop("is_freekick", None)

    if active_bools:
        for col in active_bools:
            if col in result.columns:
                result = result[result[col].astype(str).str.lower().isin(["true", "1", "yes"])]

    if active_types and not active_bools:
        result = result[result["type"].isin(active_types)]

    if successful_only and "outcomeType" in result.columns:
        result = result[result["outcomeType"] == "Successful"]
    if unsuccessful_only and "outcomeType" in result.columns:
        result = result[result["outcomeType"] == "Unsuccessful"]

    # â”€â”€ 6b. Detect spatial zone filters â”€â”€
    PITCH_ZONE_PATTERNS = [
        (r"\bleft\s*side(\s+of\s+the\s+(pitch|field))?\b",  "Entire Left Side"),
        (r"\bright\s*side(\s+of\s+the\s+(pitch|field))?\b", "Entire Right Side"),
        (r"\bleft\s*half\s*space\b",  "Left Half Space"),
        (r"\bright\s*half\s*space\b", "Right Half Space"),
        (r"\bleft\s*wing\b",          "Left Wing"),
        (r"\bright\s*wing\b",         "Right Wing"),
        (r"\b(center|centre|central)\b", "Centre"),
    ]
    DEPTH_ZONE_PATTERNS = [
        (r"\bdefensive\s*third\b",            "Defensive Third"),
        (r"\bmid(dle)?\s*third\b",            "Middle Third"),
        (r"\battacking\s*third\b|\bfinal\s*third\b", "Attacking Third"),
    ]

    if "y" in result.columns or "pitch_zone" in result.columns:
        for pat, zone in PITCH_ZONE_PATTERNS:
            if re.search(pat, q):
                zone_series = _effective_pitch_zone_series(result)
                result = result[zone_series == zone]
                break

    if "depth_zone" in result.columns:
        for pat, zone in DEPTH_ZONE_PATTERNS:
            if re.search(pat, q):
                result = result[result["depth_zone"] == zone]
                break

    # â”€â”€ 7. Build display columns â”€â”€
    DISPLAY_COLS = ["minute", "second", "type", "outcomeType", "playerName",
                    "team", "period"]

    def _display(df_r):
        extra = [c for c in df_r.columns if c.startswith("is_") and df_r[c].any()]
        if "xT" in df_r.columns:
            extra.append("xT")
        cols = [c for c in DISPLAY_COLS + extra if c in df_r.columns]
        return df_r[cols].reset_index(drop=True)

    if result.empty:
        return {"type": "text", "data": "No matching events found."}

    # â”€â”€ 8. Detect special aggregate queries (progressive, xT/dangerous) â”€â”€
    is_progressive = bool(re.search(r"\bprogressive\b|\bprog\b", q))
    is_dangerous = bool(re.search(r"\bdangerous\b|\bthreat\b|\bxt\b", q))

    if is_progressive and "playerName" in result.columns:
        prog_df = result.copy()
        prog_df["_prog"] = (
            pd.to_numeric(prog_df.get("prog_pass", 0), errors="coerce").fillna(0).clip(lower=0) +
            pd.to_numeric(prog_df.get("prog_carry", 0), errors="coerce").fillna(0).clip(lower=0)
        )
        prog_df = prog_df[prog_df["_prog"] > 0]
        if prog_df.empty:
            return {"type": "text", "data": "No progressive events found."}

        is_who_prog = bool(re.search(r"\bwho\b|\bmost\b|\btop\b|\bplayer\b", q))
        if is_who_prog:
            sums = prog_df.groupby("playerName")["_prog"].agg(["sum", "count"])
            sums = sums.sort_values("sum", ascending=False)
            sums["sum"] = sums["sum"].round(1)
            breakdown = sums.reset_index().rename(
                columns={"playerName": "Player", "sum": "Total Distance", "count": "Events"})
            top = breakdown.iloc[0]
            answer = f"{top['Player']} ({top['Total Distance']}m across {int(top['Events'])} events)"
            return {"type": "top_player", "data": answer, "breakdown": breakdown}
        else:
            display_df = _display(prog_df)
            return {"type": "table", "data": display_df, "count": len(display_df)}

    if is_dangerous and "xT" in result.columns and "playerName" in result.columns:
        xt_df = result.copy()
        xt_df["_xt"] = pd.to_numeric(xt_df["xT"], errors="coerce").fillna(0)
        xt_df = xt_df[xt_df["_xt"] > 0]
        if xt_df.empty:
            return {"type": "text", "data": "No events with positive xT found."}

        is_who_xt = bool(re.search(r"\bwho\b|\bmost\b|\btop\b|\bplayer\b", q))
        if is_who_xt:
            sums = xt_df.groupby("playerName")["_xt"].agg(["sum", "count"])
            sums = sums.sort_values("sum", ascending=False)
            sums["sum"] = sums["sum"].round(3)
            breakdown = sums.reset_index().rename(
                columns={"playerName": "Player", "sum": "Total xT", "count": "Events"})
            top = breakdown.iloc[0]
            answer = f"{top['Player']} ({top['Total xT']} xT)"
            return {"type": "top_player", "data": answer, "breakdown": breakdown}
        else:
            display_df = _display(xt_df)
            return {"type": "table", "data": display_df, "count": len(display_df)}

    # â”€â”€ 9. Standard response types â”€â”€
    display_df = _display(result)
    total_rows = len(display_df)

    is_show = bool(re.search(r"\bshow\b|\blist\b|\bgive\b|\bget\b|\bfind\b|\bdisplay\b", q))
    is_who_most = bool(re.search(r"\bwho\b.*\bmost\b|\btop\b|\bmost\b|\bplayer with\b", q))
    is_count = bool(re.search(r"\bhow many\b|\bcount\b|\btotal\b|\bnumber of\b", q))

    if is_who_most:
        counts = result["playerName"].dropna().value_counts()
        breakdown = counts.reset_index().rename(
            columns={"playerName": "Player", "count": "Count"})
        if counts.empty:
            return {"type": "text", "data": "No matching events found."}
        top_name = counts.index[0]
        top_count = counts.iloc[0]
        tied = counts[counts == top_count]
        if len(tied) > 1:
            names = " and ".join(tied.index[:3])
            answer = f"{names} are tied with {top_count} each"
        else:
            answer = f"{top_name} ({top_count})"
        return {"type": "top_player", "data": answer, "breakdown": breakdown}

    if is_count:
        return {"type": "text", "data": str(total_rows)}

    # Default: show the filtered table
    return {"type": "table", "data": display_df, "count": total_rows}


def answer_with_pandas(question, df):
    import unicodedata, re
    cols = list(df.columns)
    unique_types   = df["type"].dropna().unique().tolist() if "type" in df.columns else []
    unique_players = df["playerName"].dropna().unique().tolist() if "playerName" in df.columns else []
    unique_periods = df["period"].dropna().unique().tolist() if "period" in df.columns else []

    def strip_accents(s):
        return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")

    # â”€â”€ Pre-resolve player names from the question â”€â”€
    # Split on spaces and common delimiters, try each fragment
    resolved_players = []
    fragments = re.split(r"[''`\s,&+]+", question.lower())
    # Also try consecutive word pairs (e.g. "joao pedro")
    pairs = [f"{fragments[i]} {fragments[i+1]}" for i in range(len(fragments)-1)]
    seen_matches = set()

    for fragment in pairs + fragments:
        if len(fragment) < 3:
            continue
        match, _ = fuzzy_correct_player(fragment, df)
        if match and match not in seen_matches:
            resolved_players.append(match)
            seen_matches.add(match)

    # â”€â”€ Pre-filter the DataFrame if we found player names â”€â”€
    # This means the LLM doesn't need to handle player matching at all
    df_work = df.copy()
    player_note_for_llm = ""
    if resolved_players:
        stripped_names = [strip_accents(p).lower() for p in resolved_players]
        player_mask = df_work["playerName"].apply(
            lambda x: strip_accents(str(x)).lower() in stripped_names if pd.notna(x) else False
        )
        df_pre = df_work[player_mask]
        if not df_pre.empty:
            df_work = df_pre
            player_note_for_llm = (
                f"\nNOTE: The DataFrame `df` has ALREADY been pre-filtered to only "
                f"contain events for: {', '.join(resolved_players)}. "
                f"Do NOT add any player filter in your code."
            )

    sample = df_work.head(2).to_dict(orient="records")

    MAX_PLAYERS = 25
    player_list = unique_players[:MAX_PLAYERS]
    player_note = f" (showing {MAX_PLAYERS} of {len(unique_players)})" if len(unique_players) > MAX_PLAYERS else ""

    schema = (
        f"Columns: {cols}\n"
        f"Sample rows: {sample}\n"
        f"Total rows: {len(df_work)}\n"
        f"Unique event types (EXACT): {unique_types}\n"
        f"Unique player names (EXACT){player_note}: {player_list}\n"
        f"Unique periods (EXACT): {unique_periods}\n"
        f"prog_pass present: {'prog_pass' in df.columns}\n"
        f"prog_carry present: {'prog_carry' in df.columns}\n"
        f"xT present: {'xT' in df.columns}\n"
        f"pitch_zone values (EXACT): {sorted(df_work['pitch_zone'].dropna().unique().tolist()) if 'pitch_zone' in df_work.columns else 'not present'}\n"
        f"depth_zone values (EXACT): {sorted(df_work['depth_zone'].dropna().unique().tolist()) if 'depth_zone' in df_work.columns else 'not present'}"
        f"{player_note_for_llm}"
    )
    system = """You are a Python/pandas code generator for football data analysis.
Write a single Python expression that answers the question using a DataFrame called `df`.
Return ONLY the expression â€” no imports, no assignments, no markdown, no explanation.
RULES:
- Use EXACT strings from the schema â€” never invent type names
- Player names: use str.contains(..., case=False, na=False) â€” BUT if the NOTE says
  the df is already pre-filtered for players, do NOT add any player filter
- CRITICAL â€” boolean columns must use ==True, never filter by type name:
    crosses            -> df['is_cross']==True
    headers            -> df['is_header']==True
    corners            -> df['is_corner']==True
    freekicks          -> df['is_freekick']==True
    key passes         -> df['is_key_pass']==True
    long balls         -> df['is_long_ball']==True
    through balls      -> df['is_through_ball']==True
    big chances        -> df['is_big_chance_shot']==True
    big chances created -> df['is_big_chance']==True
    penalties          -> df['is_penalty']==True
    volleys            -> df['is_volley']==True
    chipped shots      -> df['is_chipped']==True
    direct from corner -> df['is_direct_from_corner']==True
    left foot          -> df['is_left_foot']==True
    right foot         -> df['is_right_foot']==True
    fast break/counter -> df['is_fast_break']==True
    touch in box       -> df['is_touch_in_box']==True
    assist (through ball) -> df['is_assist_throughball']==True
    assist (cross)     -> df['is_assist_cross']==True
    assist (corner)    -> df['is_assist_corner']==True
    assist (free kick) -> df['is_assist_freekick']==True
    intentional assist -> df['is_intentional_assist']==True
    yellow cards       -> df['is_yellow_card']==True
    red cards          -> df['is_red_card']==True
    second yellow      -> df['is_second_yellow']==True
    nutmegs            -> df['is_nutmeg']==True
    success in box     -> df['is_success_in_box']==True
- shots = ONLY df['type'].isin(['MissedShot','SavedShot','Goal','ShotOnPost','BlockedShot'])
- passes = ONLY df['type']=='Pass'
- saves = ONLY df['type']=='Save'
- CRITICAL â€” ALWAYS combine ALL applicable conditions with &. Never apply a boolean flag alone when other filters are also implied:
    boolean flag + type keyword  -> combine with &:
      "left foot shots"    -> df[(df['is_left_foot']==True) & (df['type'].isin(['MissedShot','SavedShot','Goal','ShotOnPost','BlockedShot']))]
      "right foot goals"   -> df[(df['is_right_foot']==True) & (df['type']=='Goal')]
      "headed passes"      -> df[(df['is_header']==True) & (df['type']=='Pass')]
      "volley goals"       -> df[(df['is_volley']==True) & (df['type']=='Goal')]
      "key pass crosses"   -> df[(df['is_key_pass']==True) & (df['is_cross']==True)]
    boolean flag + boolean flag  -> combine with &:
      "left foot crosses"  -> df[(df['is_left_foot']==True) & (df['is_cross']==True)]
      "headed big chances" -> df[(df['is_header']==True) & (df['is_big_chance_shot']==True)]
      "long ball key passes" -> df[(df['is_long_ball']==True) & (df['is_key_pass']==True)]
    three-way combinations -> chain all with &:
      "left foot shot big chances" -> df[(df['is_left_foot']==True) & (df['is_big_chance_shot']==True) & (df['type'].isin(['MissedShot','SavedShot','Goal','ShotOnPost','BlockedShot']))]
    The rule: every concept in the question maps to a condition; every condition must appear in the final expression joined by &.
- pitch_zone filter: use df['pitch_zone'] == '<exact zone name>' (use EXACT values from schema)
    zones: "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing"
    "left wing shots"         -> df[(df['pitch_zone']=='Left Wing') & (df['type'].isin(['MissedShot','SavedShot','Goal','ShotOnPost','BlockedShot']))]
    "right half space passes" -> df[(df['pitch_zone']=='Right Half Space') & (df['type']=='Pass')]
    "centre crosses"          -> df[(df['pitch_zone']=='Centre') & (df['is_cross']==True)]
- depth_zone filter: use df['depth_zone'] == '<exact zone name>' (use EXACT values from schema)
    zones: "Defensive Third", "Middle Third", "Attacking Third"
    "attacking third crosses" -> df[(df['depth_zone']=='Attacking Third') & (df['is_cross']==True)]
    "middle third passes"     -> df[(df['depth_zone']=='Middle Third') & (df['type']=='Pass')]
- team filter: use df['team'].str.contains(..., case=False, na=False)
- "who had the most X[CLR]" ALWAYS returns .groupby('playerName').size().idxmax()
- "how many X[CLR]" returns a scalar via .shape[0] or .sum()
- When returning a filtered DataFrame, return the FULL filtered df
- If the df is pre-filtered for a player, just filter by event type"""
    user = f"Schema:\n{schema}\n\nQuestion: {question}"
    raw = call_llm(system, user).strip()
    import re as _re
    raw = _re.sub(r"^```[a-zA-Z]*\n[CLR]", "", raw).strip()
    raw = _re.sub(r"```$", "", raw).strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    code = raw
    for line in lines:
        if line.startswith("df"):
            code = line
            break
    code = code.strip().strip("`")
    if code.startswith("python"):
        code = code[6:].strip()

    # Accent-strip both code and data for evaluation
    df_norm = df_work.copy()
    if "playerName" in df_norm.columns:
        df_norm["_orig_playerName"] = df_norm["playerName"]
        df_norm["playerName"] = df_norm["playerName"].apply(
            lambda x: strip_accents(x) if pd.notna(x) else x)
    code_norm = strip_accents(code)

    DISPLAY_COLS = ["minute", "second", "type", "outcomeType", "playerName", "team", "period",
                    "is_key_pass", "is_cross", "is_long_ball", "is_switch_of_play", "is_diagonal_long_ball", "is_through_ball",
                    "is_box_entry_pass", "is_deep_completion", "is_box_entry_carry", "is_final_third_entry_pass", "is_final_third_entry_carry",
                    "is_corner", "is_freekick", "is_header", "is_big_chance",
                    "is_penalty", "is_volley", "is_chipped", "is_direct_from_corner",
                    "is_left_foot", "is_right_foot", "is_fast_break", "is_touch_in_box",
                    "is_assist_throughball", "is_assist_cross", "is_assist_corner",
                    "is_assist_freekick", "is_intentional_assist",
                    "is_yellow_card", "is_red_card", "is_second_yellow",
                    "is_nutmeg", "is_success_in_box", "xT",
                    "pitch_zone", "depth_zone"]

    def _clean_df_result(result):
        # Restore original accented player names if we stripped them
        if "_orig_playerName" in result.columns:
            result["playerName"] = result["_orig_playerName"]
            result = result.drop(columns=["_orig_playerName"])
        drop_cols = ["prog_pass", "prog_carry", "x", "y", "resolved_period",
                     "_xt_num", "video_timestamp", "_orig_playerName"]
        result = result.drop(columns=[c for c in drop_cols if c in result.columns])
        bool_cols = [c for c in result.columns if c.startswith("is_")]
        for c in bool_cols:
            if c in result.columns and not result[c].any():
                result = result.drop(columns=[c])
        result = result.dropna(axis=1, how="all")
        ordered = [c for c in DISPLAY_COLS if c in result.columns]
        extras  = [c for c in result.columns if c not in ordered]
        return result[ordered + extras].reset_index(drop=True)

    try:
        result = eval(code_norm, {"df": df_norm, "pd": pd})
        if isinstance(result, str) and not result.strip():
            return "No matching events found."

        if isinstance(result, pd.DataFrame):
            if result.empty:
                # If we pre-filtered for players but the type filter emptied it,
                # show a helpful message
                if resolved_players:
                    return (f"No matching events found for "
                            f"{', '.join(resolved_players)} with that filter.")
                return "No matching events found."
            return _clean_df_result(result)

        if isinstance(result, pd.Series):
            # If it's a boolean Series, the LLM returned a mask instead of
            # a filtered DataFrame â€” apply it
            if result.dtype == bool or set(result.dropna().unique()).issubset({True, False, 0, 1}):
                filtered = df_norm[result.astype(bool)]
                if filtered.empty:
                    if resolved_players:
                        return (f"No matching events found for "
                                f"{', '.join(resolved_players)} with that filter.")
                    return "No matching events found."
                return _clean_df_result(filtered)
            if result.empty:
                return "No matching events found."
            return (result.reset_index().rename(columns={"index": "player", 0: "count"})
                    if result.index.name else result)

        return str(result) if str(result).strip() else "No matching events found."

    except Exception as e:
        err = str(e)
        if "argmax of an empty sequence" in err or "argmin of an empty sequence" in err:
            teams = df["team"].dropna().unique().tolist() if "team" in df.columns else []
            raise ValueError(
                f"No matching events found â€” the filter returned no data. "
                f"Teams in this CSV: {teams}"
            )
        raise ValueError(f"Could not compute: {err}  [code: {code_norm}]")


BOOL_COL_TO_FLAG = {
    "is_key_pass":           "key_passes_only",
    "is_cross":              "crosses_only",
    "is_long_ball":          "long_balls_only",
    "is_switch_of_play":     "switches_only",
    "is_diagonal_long_ball": "diagonals_only",
    "is_through_ball":       "through_balls_only",
    "is_corner":             "corners_only",
    "is_freekick":           "freekicks_only",
    "is_header":             "headers_only",
    "is_big_chance_shot":    "big_chances_only",
    "is_big_chance":         "big_chances_created_only",
    "is_own_goal":           "own_goals_only",
    "is_penalty":            "penalties_only",
    "is_volley":             "volleys_only",
    "is_chipped":            "chipped_only",
    "is_direct_from_corner": "direct_from_corner_only",
    "is_left_foot":          "left_foot_only",
    "is_right_foot":         "right_foot_only",
    "is_fast_break":         "fast_break_only",
    "is_touch_in_box":       "touch_in_box_only",
    "is_assist_throughball": "assist_throughball_only",
    "is_assist_cross":       "assist_cross_only",
    "is_assist_corner":      "assist_corner_only",
    "is_assist_freekick":    "assist_freekick_only",
    "is_intentional_assist": "intentional_assists_only",
    "is_yellow_card":        "yellow_cards_only",
    "is_red_card":           "red_cards_only",
    "is_second_yellow":      "second_yellow_only",
    "is_nutmeg":                    "nutmegs_only",
    "is_success_in_box":            "success_in_box_only",
    "is_box_entry_pass":            "box_entry_pass_only",
    "is_deep_completion":           "deep_completion_only",
    "is_box_entry_carry":           "box_entry_carry_only",
    "is_final_third_entry_pass":    "final_third_entry_pass_only",
    "is_final_third_entry_carry":   "final_third_entry_carry_only",
}

def parse_filters(instruction, df, available_types):
    import re as _re
    df = ensure_computed_event_flags(df)
    has_xt   = "xT" in df.columns
    has_prog = "prog_pass" in df.columns or "prog_carry" in df.columns
    players  = df["playerName"].dropna().unique().tolist() if "playerName" in df.columns else []
    periods  = df["period"].dropna().unique().tolist() if "period" in df.columns else []
    teams    = df["team"].dropna().unique().tolist() if "team" in df.columns else []

    # Pre-resolve partial player names in the instruction
    resolved_names = []
    words = _re.split(r"[''`\s]+", instruction.lower())
    for fragment in words:
        if len(fragment) < 3:
            continue
        match, _ = fuzzy_correct_player(fragment, df)
        if match:
            resolved_names.append((fragment, match))

    name_hint = ""
    if resolved_names:
        hints = [f'"{orig}" â†’ use player_filter="{matched}"' for orig, matched in resolved_names]
        name_hint = f"\nPlayer name resolution: {'; '.join(hints)}\n"

    active_bool_cols = {
        col: flag for col, flag in BOOL_COL_TO_FLAG.items()
        if col in df.columns and df[col].any()
    }
    bool_flag_docs = "\n".join(
        f'  - Set "{flag}": true for {col.replace("is_","").replace("_"," ")} events'
        for col, flag in active_bool_cols.items()
    )

    system = f"""You are a football video analysis assistant.
Translate the instruction into a JSON config for ClipMaker.
Available event types: {available_types}
Available players: {players[:30]}
Available periods: {periods}
Available teams: {teams}
CSV has xT: {has_xt}
CSV has progressive columns: {has_prog}
{name_hint}
BOOLEAN FLAGS AVAILABLE IN THIS CSV:
{bool_flag_docs}

IMPORTANT RULES:
- "filter_types": ONLY use actual event type names from the available list above
- When user says "actions", "all actions", "all events", or "everything": leave filter_types=[] (empty) to include all event types
- "team_filter": use for team requests
- "player_filter": comma-separated EXACT player names from the available list
- "half_filter": "1st half only", "2nd half only", or "Both halves" â€” NOTE: "right half space" and "left half space" are pitch ZONE terms, NOT halves; always set half_filter="Both halves" unless the user explicitly asks for a specific half of the match
- "successful_only": true when user says "successful" or "completed"
- "unsuccessful_only": true when user says "unsuccessful" or "failed"
- "minute_min" / "minute_max": for time range requests
- For shots: use filter_types=["MissedShot", "SavedShot", "Goal", "ShotOnPost", "BlockedShot"]
- For saves: use filter_types=["Save"]
- For take-ons/dribbles: use filter_types=["TakeOn"]
- For tackles: use filter_types=["Tackle"]
- For aerials: use filter_types=["Aerial"]
- For clearances: use filter_types=["Clearance"]
- For interceptions: use filter_types=["Interception"]
- For fouls: use filter_types=["Foul"]
- For carries: use filter_types=["Carry"]
- For duels: use filter_types=["Tackle", "TakeOn", "Aerial", "Challenge", "ShieldBallOpp"]
- For challenges: use filter_types=["Challenge"]
- For ball touches: use filter_types=["BallTouch"]
- For ball recoveries: use filter_types=["BallRecovery"]
- For dispossessed: use filter_types=["Dispossessed"]
- For offsides: use filter_types=["OffsideGiven", "OffsidePass", "OffsideProvoked"]
- For penalties: use filter_types=["PenaltyFaced"]
- For punches (goalkeeper): use filter_types=["Punch"]
- For substitutions: use filter_types=["SubstitutionOn", "SubstitutionOff"]
- For goalkeeper claims: use filter_types=["Claim"]
- For goalkeeper pickups: use filter_types=["KeeperPickup"]
- For goalkeeper sweeper actions: use filter_types=["KeeperSweeper"]
- "shots" means ALL shot types above â€” never omit any unless the user specifies a subtype
- NEVER invent event type names â€” ONLY use exact names from the available list
- For through balls: set "through_balls_only": true (NOT filter_types)
- For key passes: set "key_passes_only": true (NOT filter_types)
- For crosses: set "crosses_only": true (NOT filter_types)
- For long balls: set "long_balls_only": true (NOT filter_types)
- For switches of play: set "switches_only": true (NOT filter_types)
- For diagonals / long diagonals: set "diagonals_only": true (NOT filter_types)
- For headers: set "headers_only": true (NOT filter_types)
- For corners: set "corners_only": true (NOT filter_types)
- For free kicks: set "freekicks_only": true (NOT filter_types)
- For big chances (the shot itself): set "big_chances_only": true (NOT filter_types)
- For big chances created (the pass that created a big chance): set "big_chances_created_only": true (NOT filter_types)
- For own goals: set "own_goals_only": true and filter_types=["Goal"] (coordinate-based detection)
- For penalties (shot from spot): set "penalties_only": true (NOT filter_types)
- For volleys: set "volleys_only": true (NOT filter_types)
- For chipped/lob shots: set "chipped_only": true (NOT filter_types)
- For goals/shots direct from corner: set "direct_from_corner_only": true (NOT filter_types)
- For left foot actions: set "left_foot_only": true (NOT filter_types)
- For right foot actions: set "right_foot_only": true (NOT filter_types)
- For fast break/counter-attack: set "fast_break_only": true (NOT filter_types)
- For actions with a touch in the box: set "touch_in_box_only": true (NOT filter_types)
- For assists via through ball: set "assist_throughball_only": true (NOT filter_types)
- For assists via cross: set "assist_cross_only": true (NOT filter_types)
- For assists via corner: set "assist_corner_only": true (NOT filter_types)
- For assists via free kick: set "assist_freekick_only": true (NOT filter_types)
- For intentional/deliberate assists: set "intentional_assists_only": true (NOT filter_types)
- For yellow cards: set "yellow_cards_only": true and filter_types=["Card"]
- For red cards: set "red_cards_only": true and filter_types=["Card"]
- For second yellow cards: set "second_yellow_only": true and filter_types=["Card"]
- For nutmegs: set "nutmegs_only": true (NOT filter_types)
- For successful take-ons in the box: set "success_in_box_only": true (NOT filter_types)

Return ONLY valid JSON with these keys (no markdown):
{{
  "filter_types": [],
  "progressive_only": false,
  "xt_min": 0.0,
  "top_n": 0,
  "half_filter": "Both halves",
  "team_filter": "",
  "player_filter": "",
  "before_buffer": 5,
  "after_buffer": 3,
  "individual_clips": false,
  "key_passes_only": false,
  "crosses_only": false,
  "long_balls_only": false,
  "switches_only": false,
  "diagonals_only": false,
  "through_balls_only": false,
  "corners_only": false,
  "freekicks_only": false,
  "headers_only": false,
  "big_chances_only": false,
  "big_chances_created_only": false,
  "own_goals_only": false,
  "penalties_only": false,
  "volleys_only": false,
  "chipped_only": false,
  "direct_from_corner_only": false,
  "left_foot_only": false,
  "right_foot_only": false,
  "fast_break_only": false,
  "touch_in_box_only": false,
  "assist_throughball_only": false,
  "assist_cross_only": false,
  "assist_corner_only": false,
  "assist_freekick_only": false,
  "intentional_assists_only": false,
  "yellow_cards_only": false,
  "red_cards_only": false,
  "second_yellow_only": false,
  "nutmegs_only": false,
  "success_in_box_only": false,
  "deep_completion_only": false,
  "box_entry_pass_only": false,
  "box_entry_carry_only": false,
  "final_third_entry_pass_only": false,
  "final_third_entry_carry_only": false,
  "successful_only": false,
  "unsuccessful_only": false,
  "minute_min": null,
  "minute_max": null,
  "dry_run": false,
  "explanation": ""
}}"""
    raw = call_llm(system, f"Instruction: {instruction}").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # If the response doesn't look like JSON, retry once with a stricter prompt
    if not raw or not raw.startswith("{"):
        # Try to extract JSON from mixed text/JSON response
        import re as _re2
        json_match = _re2.search(r'\{[^{}]*([CLR]:\{[^{}]*\}[^{}]*)*\}', raw or "")
        if json_match:
            raw = json_match.group(0)
        else:
            # Retry with explicit instruction
            raw = call_llm(system + "\n\nCRITICAL: Return ONLY the JSON object. No text before or after it.",
                           f"Instruction: {instruction}").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            if not raw or not raw.startswith("{"):
                json_match2 = _re2.search(r'\{[^{}]*([CLR]:\{[^{}]*\}[^{}]*)*\}', raw or "")
                if json_match2:
                    raw = json_match2.group(0)
                else:
                    raise ValueError(f"AI did not return valid JSON. Response: {(raw or '(empty)')[:200]}")

    result = json.loads(raw)

    # Clamp half_filter to valid values â€” LLM can confuse "right half space" with a half
    _valid_halves = {"1st half only", "2nd half only", "Both halves"}
    if result.get("half_filter") not in _valid_halves:
        result["half_filter"] = "Both halves"

    FLAG_NAMES = {"long_balls_only", "switches_only", "diagonals_only", "successful_only", "unsuccessful_only", "progressive_only",
                  "key_passes_only", "crosses_only", "through_balls_only",
                  "corners_only", "freekicks_only", "headers_only",
                  "big_chances_only", "big_chances_created_only", "own_goals_only",
                  "gk_saves_only", "penalties_only", "volleys_only", "chipped_only",
                  "direct_from_corner_only", "left_foot_only", "right_foot_only",
                  "fast_break_only", "touch_in_box_only",
                  "assist_throughball_only", "assist_cross_only", "assist_corner_only",
                  "assist_freekick_only", "intentional_assists_only",
                  "yellow_cards_only", "red_cards_only", "second_yellow_only",
                  "nutmegs_only", "success_in_box_only",
                  "deep_completion_only", "box_entry_pass_only", "box_entry_carry_only",
                  "final_third_entry_pass_only", "final_third_entry_carry_only"}
    bad = [v for v in result.get("filter_types", []) if v in FLAG_NAMES]
    for flag in bad:
        result["filter_types"].remove(flag)
        result[flag] = True

    # â”€â”€ Post-processing: strip hallucinated flags â”€â”€
    # The LLM often sets flags the user never asked for. Only allow flags
    # that match keywords actually present in the instruction.
    instr_lower = instruction.lower()

    FLAG_KEYWORD_MAP = {
        "progressive_only":         ["progressive", "prog pass", "prog carry"],
        "successful_only":          ["successful", "completed", "success"],
        "unsuccessful_only":        ["unsuccessful", "failed", "incomplete", "missed"],
        "key_passes_only":          ["key pass", "key passes"],
        "crosses_only":             ["cross", "crosses"],
        "long_balls_only":          ["long ball", "long balls"],
        "switches_only":            ["switch", "switches", "switch of play", "switches of play"],
        "diagonals_only":           ["diagonal", "diagonals", "long diagonal", "long diagonals", "raking diagonal", "raking diagonals"],
        "through_balls_only":       ["through ball", "through balls"],
        "corners_only":             ["corner", "corners"],
        "freekicks_only":           ["free kick", "free kicks", "freekick"],
        "headers_only":             ["header", "headers", "headed"],
        "big_chances_only":         ["big chance", "big chances"],
        "big_chances_created_only": ["big chance created", "big chances created",
                                     "chance created", "chances created"],
        "own_goals_only":           ["own goal", "own goals", "og"],
        "gk_saves_only":            ["gk save", "goalkeeper save", "keeper save", "saved"],
        "penalties_only":           ["penalty kick", "spot kick", "penalty shot"],
        "volleys_only":             ["volley", "volleys"],
        "chipped_only":             ["chipped", "chip shot", "lob"],
        "direct_from_corner_only":  ["direct from corner", "corner goal"],
        "left_foot_only":           ["left foot", "left footed"],
        "right_foot_only":          ["right foot", "right footed"],
        "fast_break_only":          ["fast break", "counter attack", "counter-attack", "on the break"],
        "touch_in_box_only":        ["touch in box", "in the box"],
        "assist_throughball_only":  ["assist through ball", "through ball assist"],
        "assist_cross_only":        ["assist cross", "cross assist"],
        "assist_corner_only":       ["assist corner", "corner assist"],
        "assist_freekick_only":     ["assist free kick", "free kick assist"],
        "intentional_assists_only": ["intentional assist", "deliberate assist"],
        "yellow_cards_only":        ["yellow card", "booked"],
        "red_cards_only":           ["red card", "sent off"],
        "second_yellow_only":       ["second yellow", "double yellow"],
        "nutmegs_only":             ["nutmeg", "nutmegs"],
        "success_in_box_only":          ["success in box", "take on in box", "dribble in box"],
        "deep_completion_only":         ["deep completion", "deep completions"],
        "box_entry_pass_only":          ["box entry pass", "box entry passes", "pass into the box", "passes into the box"],
        "box_entry_carry_only":         ["box entry carry", "box entry carries", "carry into the box", "carries into the box"],
        "final_third_entry_pass_only":  ["final third entry pass", "final third entry passes", "pass into the final third", "passes into the final third"],
        "final_third_entry_carry_only": ["final third entry carry", "final third entry carries", "carry into the final third", "carries into the final third"],
    }

    for flag, keywords in FLAG_KEYWORD_MAP.items():
        if result.get(flag) and not any(kw in instr_lower for kw in keywords):
            result[flag] = False

    for flag_name in INTENT_FLAG_TO_BOOL_COL:
        if query_has_intent_alias(instr_lower, flag_name):
            result[flag_name] = True

    # â”€â”€ Keyword-based overrides for common requests â”€â”€
    # These catch cases where the LLM maps to wrong filter_types

    # "through ball(s)" â†’ through_balls_only flag, not filter_types
    if _re.search(r"\bthrough\s*ball", instr_lower):
        result["through_balls_only"] = True
        # Remove wrong filter_types the LLM might have set
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t not in ("Carry", "Pass")]

    # "key pass(es)" â†’ key_passes_only flag
    if _re.search(r"\bkey\s*pass", instr_lower):
        result["key_passes_only"] = True
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t not in ("Pass",)]

    # "cross(es)" â†’ crosses_only flag
    if _re.search(r"\bcrosses?\b", instr_lower) and "crossbar" not in instr_lower:
        result["crosses_only"] = True

    # "long ball(s)" â†’ long_balls_only flag
    if _re.search(r"\blong\s*ball", instr_lower):
        result["long_balls_only"] = True

    if _re.search(r"\bswitch(?:es)?(?:\s+of\s+play)?\b", instr_lower):
        result["switches_only"] = True

    if _re.search(r"\b(?:long\s+)?diagonal(?:s)?\b|\braking\s+diagonal(?:s)?\b", instr_lower):
        result["diagonals_only"] = True

    # "header(s)" â†’ headers_only flag
    if _re.search(r"\bheader", instr_lower):
        result["headers_only"] = True

    # "corner(s)" â†’ corners_only flag
    if _re.search(r"\bcorner", instr_lower):
        result["corners_only"] = True

    # "free kick(s)" â†’ freekicks_only flag
    if _re.search(r"\bfree\s*kick", instr_lower):
        result["freekicks_only"] = True

    # "set piece(s)" â†’ corners + free kicks together. Clear any broad
    # filter_types unless the user explicitly asked for a specific event type.
    if _re.search(r"\bset[\s-]*pieces?\b", instr_lower) or query_has_intent_alias(instr_lower, "set_pieces"):
        result["corners_only"] = True
        result["freekicks_only"] = True
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t in available_types and t in {"Pass", "Goal", "MissedShot",
                                                                    "SavedShot", "ShotOnPost", "BlockedShot",
                                                                    "Aerial", "Foul", "Card"}]

    # â”€â”€ When a boolean flag is active, only keep filter_types the user asked for â”€â”€
    # The LLM often adds filter_types that the user didn't request.
    # e.g. "all big chances" â†’ LLM adds shot types, but big chances can be passes too.
    # Only keep filter_types if the user's words explicitly match a type keyword.
    BOOL_FLAGS = ["key_passes_only", "crosses_only", "long_balls_only", "switches_only", "diagonals_only",
                  "through_balls_only", "corners_only", "freekicks_only",
                  "headers_only", "big_chances_only", "big_chances_created_only",
                  "own_goals_only", "penalties_only", "volleys_only", "chipped_only",
                  "direct_from_corner_only", "left_foot_only", "right_foot_only",
                  "fast_break_only", "touch_in_box_only", "assist_throughball_only",
                  "assist_cross_only", "assist_corner_only", "assist_freekick_only",
                  "intentional_assists_only", "yellow_cards_only", "red_cards_only",
                  "second_yellow_only", "nutmegs_only", "success_in_box_only",
                  "deep_completion_only", "box_entry_pass_only", "box_entry_carry_only",
                  "final_third_entry_pass_only", "final_third_entry_carry_only"]
    if any(result.get(f) for f in BOOL_FLAGS) and result.get("filter_types"):
        # Check which type keywords the user actually mentioned
        USER_TYPE_KEYWORDS = {
            r"\bshot":          {"MissedShot", "SavedShot", "Goal", "ShotOnPost", "BlockedShot"},
            r"\bgoal":          {"Goal"},
            r"\bpass":          {"Pass"},
            r"\btackle":        {"Tackle"},
            r"\btake.?on":      {"TakeOn"},
            r"\bdribble":       {"TakeOn"},
            r"\baerial":        {"Aerial"},
            r"\bcarr":          {"Carry"},
            r"\bclearance":     {"Clearance"},
            r"\bintercept":     {"Interception"},
            r"\bfoul":          {"Foul"},
            r"\bsave":          {"Save"},
            r"\bcard":          {"Card"},
            r"\bblock":         {"Block", "BlockedPass", "BlockedShot"},
            r"\bduel":          {"Tackle", "TakeOn", "Aerial", "Challenge", "ShieldBallOpp"},
            r"\bchallenge":     {"Challenge"},
            r"\btouch":         {"BallTouch"},
            r"\bdispossess":    {"Dispossessed"},
            r"\boffside":       {"OffsideGiven", "OffsidePass", "OffsideProvoked"},
            r"\bpenalt":        {"PenaltyFaced"},
            r"\bpunch":         {"Punch"},
            r"\bsub(stitut)?": {"SubstitutionOn", "SubstitutionOff"},
            r"\bclaim":         {"Claim"},
            r"\brecovery|\brecoveries": {"BallRecovery"},
        }
        user_requested_types = set()
        for pattern, types in USER_TYPE_KEYWORDS.items():
            if _re.search(pattern, instr_lower):
                user_requested_types |= types

        if user_requested_types:
            # Keep only types the user explicitly mentioned
            result["filter_types"] = [t for t in result["filter_types"]
                                      if t in user_requested_types and t in available_types]
        else:
            # User didn't mention any type â†’ clear filter_types, let boolean flag work alone
            result["filter_types"] = []

    # For generic "set pieces" requests, prefer the restart flags alone.
    if (_re.search(r"\bset[\s-]*pieces?\b", instr_lower) or query_has_intent_alias(instr_lower, "set_pieces")) and not _re.search(
        r"\b(pass|passes|shot|shots|goal|goals|cross|crosses|header|headers|assist|assists)\b",
        instr_lower,
    ):
        result["filter_types"] = []

    # "deep completion(s)" â†’ deep_completion_only flag, not a made-up filter type
    if _re.search(r"\bdeep\s*completion", instr_lower):
        result["deep_completion_only"] = True
        result["filter_types"] = []

    # "box entry pass(es)" â†’ box_entry_pass_only flag
    if _re.search(r"\bbox\s*entry\s*pass|\bpass(?:es)?\s+into\s+(?:the\s+)?box|\bpass(?:es)?\s+(?:that\s+)?enter(?:s|ing)?\s+(?:the\s+)?box", instr_lower):
        result["box_entry_pass_only"] = True
        result["filter_types"] = []

    # "box entry carry/carries" â†’ box_entry_carry_only flag
    if _re.search(r"\bbox\s*entry\s*carr(?:y|ies)|\bcarr(?:y|ies)\s+into\s+(?:the\s+)?box|\bcarr(?:y|ies)\s+(?:that\s+)?enter(?:s|ing)?\s+(?:the\s+)?box", instr_lower):
        result["box_entry_carry_only"] = True
        result["filter_types"] = []

    # "final third entry pass(es)" â†’ final_third_entry_pass_only flag
    if _re.search(r"\bfinal\s*third\s*entry\s*pass|\bpass(?:es)?\s+into\s+(?:the\s+)?final\s+third|\bfinal\s*third\s+pass\s*entr", instr_lower):
        result["final_third_entry_pass_only"] = True
        result["filter_types"] = []

    # "final third entry carry/carries" â†’ final_third_entry_carry_only flag
    if _re.search(r"\bfinal\s*third\s*entry\s*carr|\bcarr(?:y|ies)\s+into\s+(?:the\s+)?final\s+third|\bfinal\s*third\s+carr(?:y|ies)\s*entr", instr_lower):
        result["final_third_entry_carry_only"] = True
        result["filter_types"] = []

    # "big chances created" â†’ big_chances_created_only flag (pass that created big chance)
    if _re.search(r"\bbig\s*chances?\s*creat|\bcreat\w*\b.*\bbig\s*chance", instr_lower):
        result["big_chances_created_only"] = True
        result["big_chances_only"] = False
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t not in ("MissedShot", "SavedShot", "Goal", "BlockedShot")]

    # "own goal(s)" / "og" â†’ own_goals_only flag; must include Goal type
    if _re.search(r"\bown\s*goal|\bog\b", instr_lower):
        result["own_goals_only"] = True
        if "Goal" in available_types:
            result["filter_types"] = ["Goal"]

    # "take on(s)" / "dribble(s)" â†’ filter_types TakeOn
    if _re.search(r"\btake\s*on", instr_lower) or _re.search(r"\bdribble", instr_lower):
        if "TakeOn" in available_types:
            result["filter_types"] = ["TakeOn"]

    # "tackle(s)" â†’ filter_types Tackle
    if _re.search(r"\btackle", instr_lower):
        if "Tackle" in available_types:
            result["filter_types"] = ["Tackle"]

    # "shot(s)" â†’ all shot types
    if _re.search(r"\bshot", instr_lower) and not _re.search(r"\btake\b", instr_lower):
        shot_types = [t for t in ["MissedShot", "SavedShot", "Goal", "ShotOnPost", "BlockedShot"]
                      if t in available_types]
        if shot_types:
            result["filter_types"] = shot_types

    # "aerial(s)" â†’ filter_types Aerial
    if _re.search(r"\baerial", instr_lower):
        if "Aerial" in available_types:
            result["filter_types"] = ["Aerial"]

    # "duel(s)" â†’ all duel types
    if _re.search(r"\bduel", instr_lower):
        duel_types = [t for t in ["Tackle", "TakeOn", "Aerial", "Challenge", "ShieldBallOpp"]
                      if t in available_types]
        if duel_types:
            result["filter_types"] = duel_types

    # "challenge(s)" â†’ Challenge
    if _re.search(r"\bchallenge", instr_lower):
        if "Challenge" in available_types:
            result["filter_types"] = ["Challenge"]

    # "ball touch(es)" / "touch(es)" â†’ BallTouch
    if _re.search(r"\bball\s*touch|\bball\s*touches", instr_lower):
        if "BallTouch" in available_types:
            result["filter_types"] = ["BallTouch"]

    # "dispossessed" â†’ Dispossessed
    if _re.search(r"\bdispossess", instr_lower):
        if "Dispossessed" in available_types:
            result["filter_types"] = ["Dispossessed"]

    # "offside" â†’ all offside types
    if _re.search(r"\boffside", instr_lower):
        offside_types = [t for t in ["OffsideGiven", "OffsidePass", "OffsideProvoked"]
                         if t in available_types]
        if offside_types:
            result["filter_types"] = offside_types

    # "penalty" / "penalties" â†’ PenaltyFaced
    if _re.search(r"\bpenalt(y|ies)", instr_lower):
        if "PenaltyFaced" in available_types:
            result["filter_types"] = ["PenaltyFaced"]

    # "punch(es)" â†’ Punch
    if _re.search(r"\bpunches?\b", instr_lower):
        if "Punch" in available_types:
            result["filter_types"] = ["Punch"]

    # "substitution(s)" / "sub(s)" â†’ SubstitutionOn + SubstitutionOff
    if _re.search(r"\bsubs?(titutions?)?\b", instr_lower):
        sub_types = [t for t in ["SubstitutionOn", "SubstitutionOff"]
                     if t in available_types]
        if sub_types:
            result["filter_types"] = sub_types

    # "claim(s)" â†’ Claim
    if _re.search(r"\bclaim", instr_lower):
        if "Claim" in available_types:
            result["filter_types"] = ["Claim"]

    # "ball recovery" / "recoveries" â†’ BallRecovery
    if _re.search(r"\bball\s*recover|\brecoveries", instr_lower):
        if "BallRecovery" in available_types:
            result["filter_types"] = ["BallRecovery"]

    # Fuzzy-correct filter_types against actual available types
    # LLM might return "Take On" instead of "TakeOn", etc.
    if result.get("filter_types") and available_types:
        corrected_types = []
        type_lookup = {t.lower().replace(" ", "").replace("_", ""): t
                       for t in available_types}
        for ft in result["filter_types"]:
            normalized = ft.lower().replace(" ", "").replace("_", "")
            if ft in available_types:
                corrected_types.append(ft)
            elif normalized in type_lookup:
                corrected_types.append(type_lookup[normalized])
            else:
                # Try substring match
                matched = False
                for avail in available_types:
                    if normalized in avail.lower() or avail.lower() in normalized:
                        corrected_types.append(avail)
                        matched = True
                        break
                if not matched:
                    corrected_types.append(ft)  # keep as-is, let it fail gracefully
        result["filter_types"] = corrected_types

    # â”€â”€ Deterministic zone filtering (pitch_zone / depth_zone) â”€â”€
    PITCH_ZONE_PATTERNS = [
        (r"\bleft\s*side(\s+of\s+the\s+(pitch|field))?\b",  "Entire Left Side"),
        (r"\bright\s*side(\s+of\s+the\s+(pitch|field))?\b", "Entire Right Side"),
        (r"\bleft\s*half\s*space\b",  "Left Half Space"),
        (r"\bright\s*half\s*space\b", "Right Half Space"),
        (r"\bleft\s*wing\b",          "Left Wing"),
        (r"\bright\s*wing\b",         "Right Wing"),
        (r"\b(center|centre|central)\b", "Centre"),
    ]
    DEPTH_ZONE_PATTERNS = [
        (r"\bdefensive\s*third\b",                   "Defensive Third"),
        (r"\bmid(dle)?\s*third\b",                   "Middle Third"),
        (r"\battacking\s*third\b|\bfinal\s*third\b", "Attacking Third"),
    ]

    result["pitch_zone_filter"] = ""
    result["depth_zone_filter"] = ""

    for pat, zone in PITCH_ZONE_PATTERNS:
        if _re.search(pat, instr_lower):
            result["pitch_zone_filter"] = zone
            break

    for pat, zone in DEPTH_ZONE_PATTERNS:
        if _re.search(pat, instr_lower):
            result["depth_zone_filter"] = zone
            break

    return result


def render_stats_panel(df):
    import streamlit as st
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Events", len(df))
    if "period" in df.columns:
        m2.metric("1st Half", len(df[df["period"] == "FirstHalf"]))
        m3.metric("2nd Half", len(df[df["period"] == "SecondHalf"]))
    st.divider()
    ca, cb = st.columns(2)
    with ca:
        if "type" in df.columns:
            st.markdown("**Events by Type**")
            tc = df["type"].value_counts().reset_index()
            tc.columns = ["Type", "Count"]
            st.dataframe(tc, use_container_width=True, hide_index=True)
    with cb:
        if "playerName" in df.columns:
            st.markdown("**Events by Player**")
            pc = df["playerName"].value_counts().reset_index()
            pc.columns = ["Player", "Count"]
            st.dataframe(pc, use_container_width=True, hide_index=True)
    if "xT" in df.columns:
        xt_df = df.copy()
        xt_df["xT"] = pd.to_numeric(xt_df["xT"], errors="coerce")
        xt_df = xt_df.dropna(subset=["xT"])
        if len(xt_df) > 0:
            st.divider()
            st.markdown("**Top 10 by xT**")
            st.dataframe(xt_df.nlargest(10, "xT")[["minute","second","type","playerName","period","xT"]],
                         use_container_width=True, hide_index=True)


# =============================================================================
# C2 â€” FILTER SNAPSHOTS
# =============================================================================
from pathlib import Path as _Path

_SNAPSHOTS_DIR = _Path.home() / ".clipmaker_snapshots"


def _get_snapshots_dir():
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    return _SNAPSHOTS_DIR


def save_filter_snapshot(name, config):
    """Save a filter configuration dict to a named JSON snapshot."""
    snapshot_file = _get_snapshots_dir() / f"{name}.json"
    with open(snapshot_file, "w") as f:
        json.dump(config, f, indent=2)


def load_filter_snapshot(name):
    """Load a filter configuration dict from a named snapshot."""
    snapshot_file = _get_snapshots_dir() / f"{name}.json"
    if snapshot_file.exists():
        with open(snapshot_file, "r") as f:
            return json.load(f)
    return None


def list_snapshots():
    """Return sorted list of saved snapshot names."""
    d = _get_snapshots_dir()
    return sorted([f.stem for f in d.glob("*.json")])


def delete_snapshot(name):
    """Delete a saved snapshot by name."""
    snapshot_file = _get_snapshots_dir() / f"{name}.json"
    if snapshot_file.exists():
        snapshot_file.unlink()


# =============================================================================
# D2 â€” PROGRESSIVE ACTION CHAINS
# =============================================================================

def detect_progressive_chains(df_all, min_chain_length=3):
    """
    Detect sequences of consecutive progressive actions (prog_pass or prog_carry)
    by the same team.  Returns a list of chain dicts.

    Each chain includes:
      - starts_in_own_half: True if the first progressive action starts in x < 50
      - reaches_opp_half: True if the final progressive action ends in x > 50
      - start_x / end_x: start and terminal x coordinates for sequence filtering
    """
    if df_all is None or df_all.empty:
        return []

    has_prog_pass  = "prog_pass"  in df_all.columns
    has_prog_carry = "prog_carry" in df_all.columns
    if not has_prog_pass and not has_prog_carry:
        return []

    def _end_x(row):
        try:
            v = row.get("endX") if row.get("endX") is not None else row.get("x", 0)
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def _start_x(row):
        try:
            return float(row.get("x", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _build_chain(chain_idxs, current_team):
        s  = df_all.loc[chain_idxs[0]]
        e  = df_all.loc[chain_idxs[-1]]
        sx = _start_x(s)
        ex = _end_x(e)
        start_seconds = int(s.get("minute", 0) or 0) * 60 + int(s.get("second", 0) or 0)
        end_seconds   = int(e.get("minute", 0) or 0) * 60 + int(e.get("second", 0) or 0)
        return {
            "start_idx":        chain_idxs[0],
            "end_idx":          chain_idxs[-1],
            "team":             current_team,
            "start_minute":     s.get("minute", 0),
            "start_second":     s.get("second", 0),
            "end_minute":       e.get("minute", 0),
            "end_second":       e.get("second", 0),
            "start_period":     s.get("period", "FirstHalf"),
            "end_period":       e.get("period", "FirstHalf"),
            "action_count":     len(chain_idxs),
            "start_x":          sx,
            "end_x":            ex,
            "starts_in_own_half": sx < 50,
            "reaches_opp_half": ex > 50,
            "duration_seconds": max(0, end_seconds - start_seconds),
        }

    chains     = []
    chain_idxs = []
    current_team = None

    for idx, row in df_all.iterrows():
        row_type = row.get("type", "")
        row_team = row.get("team", "")
        is_prog  = False

        if has_prog_pass and row_type == "Pass":
            try:
                is_prog = float(row.get("prog_pass", 0)) > 0
            except (TypeError, ValueError):
                is_prog = bool(row.get("prog_pass"))
        if not is_prog and has_prog_carry and row_type == "Carry":
            try:
                is_prog = float(row.get("prog_carry", 0)) > 0
            except (TypeError, ValueError):
                is_prog = bool(row.get("prog_carry"))

        if is_prog and (current_team is None or row_team == current_team):
            chain_idxs.append(idx)
            current_team = row_team
        else:
            if len(chain_idxs) >= min_chain_length:
                chains.append(_build_chain(chain_idxs, current_team))
            chain_idxs   = [idx] if is_prog else []
            current_team = row_team if is_prog else None

    if len(chain_idxs) >= min_chain_length:
        chains.append(_build_chain(chain_idxs, current_team))

    return chains


def get_chain_actions(df_all, chain):
    """Return a DataFrame slice of all events belonging to a build-up chain."""
    mask = (df_all.index >= chain["start_idx"]) & (df_all.index <= chain["end_idx"])
    return df_all[mask].copy()


