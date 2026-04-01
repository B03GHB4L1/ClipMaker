"""
clipmaker_core.py  —  Shared backend logic for ClipMaker v1.2
Imported by ClipMaker.py (Home) and pages/1_Filtering.py
"""

import os
import threading
import time
import json
import pandas as pd

# =============================================================================
# PERIOD / TIMESTAMP HELPERS
# =============================================================================

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "FirstPeriodOfExtraTime": 3, "SecondPeriodOfExtraTime": 4,
    "PenaltyShootout": 5,
    1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
}

def to_seconds(timestamp):
    parts = list(map(int, timestamp.strip().split(":")))
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

def apply_filters(df, config, log=None):
    original = len(df)

    if config.get("filter_types"):
        selected = config["filter_types"]
        if selected:
            before = len(df)
            available = df["type"].unique().tolist() if "type" in df.columns else []
            df = df[df["type"].isin(selected)]
            if log and len(df) == 0 and before > 0:
                log(f"  ⚠ filter_types={selected} matched 0/{before} events. Available types: {available[:15]}")

    if config.get("progressive_only"):
        prog_cols = [c for c in ["prog_pass", "prog_carry"] if c in df.columns]
        if prog_cols:
            mask = df[prog_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
            filtered = df[(mask > 0).any(axis=1)]
            if len(filtered) > 0:
                df = filtered
            elif log:
                log("  ⚠ progressive_only matched 0 events — ignoring flag")

    if config.get("key_passes_only") and "is_key_pass" in df.columns:
        df = df[df["is_key_pass"].astype(str).str.lower().isin(["true", "1", "yes"])]

    for flag, col in [
        ("crosses_only",      "is_cross"),
        ("long_balls_only",   "is_long_ball"),
        ("through_balls_only","is_through_ball"),
        ("corners_only",      "is_corner"),
        ("freekicks_only",    "is_freekick"),
        ("headers_only",      "is_header"),
        ("big_chances_only",  "is_big_chance_shot"),
        ("big_chances_created_only", "is_big_chance"),
    ]:
        if config.get(flag) and col in df.columns:
            df = df[df[col].astype(str).str.lower().isin(["true", "1", "yes"])]

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
                      "big_chances_only", "long_balls_only", "successful_only",
                      "unsuccessful_only", "progressive_only"]:
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
        log(f"Found {len(df)} events → {len(windows)} clips after merging.\n")

        if config["dry_run"]:
            for i, (s, e, lbl, p) in enumerate(windows, 1):
                log(f"  Clip {i:02d}: {s:.1f}s – {e:.1f}s  ({e-s:.0f}s)  |  {lbl}")
            log("\n✓ DRY RUN complete.")
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
                "-map", "0:v:0", "-map", "0:a:0?",
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
        replay_map = config.get("replay_map", {})

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

                    if replay_map:
                        import tempfile
                        for pt in label.split(" + "):
                            action_part = pt.split(" @")[0].strip()
                            minute_match = None
                            for chunk in pt.split():
                                if ":" in chunk:
                                    try:
                                        minute_match = int(chunk.split(":")[0])
                                    except ValueError:
                                        pass
                            rkey = (action_part, minute_match)
                            if rkey in replay_map:
                                rdata = replay_map[rkey]
                                replay_clip = rdata.get("clip_path", "")
                                if replay_clip and os.path.exists(replay_clip):
                                    combined = filepath.replace(".mp4", "_with_replay.mp4")
                                    concat_list = tempfile.NamedTemporaryFile(
                                        mode="w", suffix=".txt", delete=False)
                                    concat_list.write(f"file '{os.path.abspath(filepath).replace(os.sep, '/')}'\n")
                                    concat_list.write(f"file '{os.path.abspath(replay_clip).replace(os.sep, '/')}'\n")
                                    concat_list.close()
                                    import subprocess
                                    subprocess.run([
                                        ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
                                        "-i", concat_list.name, "-c", "copy", combined
                                    ], capture_output=True)
                                    os.unlink(concat_list.name)
                                    if os.path.exists(combined):
                                        os.replace(combined, filepath)
                                        log(f"    + Replay appended (confidence {rdata['confidence']:.2f})")
                                break

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

                if replay_map:
                    for pt in label.split(" + "):
                        action_part = pt.split(" @")[0].strip()
                        minute_match = None
                        for chunk in pt.split():
                            if ":" in chunk:
                                try:
                                    minute_match = int(chunk.split(":")[0])
                                except ValueError:
                                    pass
                        rkey = (action_part, minute_match)
                        if rkey in replay_map:
                            rdata = replay_map[rkey]
                            replay_clip = rdata.get("clip_path", "")
                            if replay_clip and os.path.exists(replay_clip):
                                clip_specs.append((replay_clip, None, None))
                                log(f"    + Replay queued for {action_part} {minute_match}′")
                            break

            if not clip_specs:
                log("\n✗ No matching events found — nothing to clip.")
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
        log(f"\n✗ ERROR: {e}")
        log_queue.put({"type": "error"})


# =============================================================================
# AI — GROQ PROXY
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
        s = re.sub(r"[''`]s?\b", "", s)       # possessive 's
        s = re.sub(r"[^a-z0-9\s]", "", s)     # non-alphanumeric
        return s.strip()

    if "playerName" not in df.columns:
        return None, None

    # Skip common football/query terms — single words AND multi-word phrases
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
        "pickup", "sweeper",
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
    }

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

    # 3. Strip trailing 's' for plurals (e.g. "hills" → "hill")
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

    q = question.lower().strip()

    # ── 1. Detect boolean filters (through balls, key passes, etc.) ──
    BOOL_PATTERNS = {
        "is_through_ball":    [r"\bthrough\s*ball"],
        "is_long_ball":       [r"\blong\s*ball"],
        "is_key_pass":        [r"\bkey\s*pass", r"\bchance[sd]?\s*creat", r"\bcreat\w*\b.*\bchance"],
        "is_cross":           [r"\bcross(?:es)?\b"],
        "is_header":          [r"\bheader"],
        "is_corner":          [r"\bcorner"],
        "is_freekick":        [r"\bfree\s*kick"],
        "is_big_chance_shot": [r"\bbig\s*chance"],
        "is_big_chance":      [r"\bbig\s*chance[sd]?\s*creat", r"\bcreat\w*\b.*\bbig\s*chance"],
        "is_gk_save":         [r"\bgk\s*save", r"\bkeeper\s*save"],
    }

    TYPE_PATTERNS = {
        "shots":          (r"\bshot", ["MissedShot", "SavedShot", "Goal", "ShotOnPost", "BlockedShot"]),
        "goals":          (r"\bgoal", ["Goal"]),
        "passes":         (r"\bpass(?:es)?\b", ["Pass"]),
        "tackles":        (r"\btackle", ["Tackle"]),
        "take_ons":       (r"\btake\s*on|\bdribble", ["TakeOn"]),
        "aerials":        (r"\baerial", ["Aerial"]),
        "carries":        (r"\bcarr(?:y|ies)\b", ["Carry"]),
        "clearances":     (r"\bclearance", ["Clearance"]),
        "interceptions":  (r"\bintercept", ["Interception"]),
        "fouls":          (r"\bfoul", ["Foul"]),
        "saves":          (r"\bsave(?:s)?\b(?!d)", ["Save"]),
        "cards":          (r"\bcard|\byellow|\bred\b", ["Card"]),
        "blocks":         (r"\bblock(?:s)?\b", ["Block", "BlockedPass", "BlockedShot"]),
        "recoveries":     (r"\brecovery|\brecoveries|\brecover", ["BallRecovery"]),
        "duels":          (r"\bduel", ["Tackle", "TakeOn", "Aerial", "Challenge"]),
        "challenges":     (r"\bchallenge", ["Challenge"]),
        "ball_touches":   (r"\bball\s*touch|\btouch(?:es)?\b", ["BallTouch"]),
        "dispossessed":   (r"\bdispossess", ["Dispossessed"]),
        "offside":        (r"\boffside", ["OffsideGiven", "OffsidePass", "OffsideProvoked"]),
        "penalty":        (r"\bpenalt(?:y|ies)", ["PenaltyFaced"]),
        "punch":          (r"\bpunch(?:es)?\b", ["Punch"]),
        "substitutions":  (r"\bsub(?:stitution)?s?\b|\bcoming\s*on|\bcoming\s*off", ["SubstitutionOn", "SubstitutionOff"]),
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

    # "big chances created" matches both — "created" is more specific, wins
    if "is_big_chance" in active_bools and "is_big_chance_shot" in active_bools:
        del active_bools["is_big_chance_shot"]

    # "big chances created" also matches is_key_pass via "chance created" —
    # if is_big_chance matched, it's more specific, remove is_key_pass
    if "is_big_chance" in active_bools and "is_key_pass" in active_bools:
        del active_bools["is_key_pass"]

    active_types = []
    for name, (pat, types) in TYPE_PATTERNS.items():
        if re.search(pat, q):
            for t in types:
                if t in df["type"].values:
                    active_types.append(t)

    # ── 2. Detect players ──
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

    # ── 3. Detect team filter ──
    teams = df["team"].dropna().unique().tolist() if "team" in df.columns else []
    active_team = None
    for team in teams:
        if team.lower() in q:
            active_team = team
            break

    # ── 4. Detect half filter ──
    active_half = None
    if re.search(r"\b1st\s*half|\bfirst\s*half", q):
        active_half = "FirstHalf"
    elif re.search(r"\b2nd\s*half|\bsecond\s*half", q):
        active_half = "SecondHalf"

    # ── 5. Detect outcome filter ──
    # "won" in "who won the most X" or "won the most X" is an aggregate question,
    # not an outcome filter — suppress successful_only in that context.
    _won_is_agg = bool(re.search(r"\bwho\b.*\bwon\b|\bwon\b.*\bmost\b", q))
    successful_only = bool(re.search(r"\bsuccessful\b|\bcompleted\b|\bwin\b", q)) or (
        bool(re.search(r"\bwon\b", q)) and not _won_is_agg
    )
    unsuccessful_only = bool(re.search(r"\bunsuccessful\b|\bfailed\b|\bmissed\b|\blost\b|\blose\b", q))

    # ── 6. Apply deterministic filters ──
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

    # ── 7. Build display columns ──
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

    # ── 8. Detect special aggregate queries (progressive, xT/dangerous) ──
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

    # ── 9. Standard response types ──
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

    # ── Pre-resolve player names from the question ──
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

    # ── Pre-filter the DataFrame if we found player names ──
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
        f"xT present: {'xT' in df.columns}"
        f"{player_note_for_llm}"
    )
    system = """You are a Python/pandas code generator for football data analysis.
Write a single Python expression that answers the question using a DataFrame called `df`.
Return ONLY the expression — no imports, no assignments, no markdown, no explanation.
RULES:
- Use EXACT strings from the schema — never invent type names
- Player names: use str.contains(..., case=False, na=False) — BUT if the NOTE says
  the df is already pre-filtered for players, do NOT add any player filter
- CRITICAL — boolean columns must use ==True, never filter by type name:
    crosses       -> df['is_cross']==True
    headers       -> df['is_header']==True
    corners       -> df['is_corner']==True
    freekicks     -> df['is_freekick']==True
    key passes    -> df['is_key_pass']==True
    long balls    -> df['is_long_ball']==True
    through balls -> df['is_through_ball']==True
    big chances        -> df['is_big_chance_shot']==True
    big chances created -> df['is_big_chance']==True
- shots = ONLY df['type'].isin(['MissedShot','SavedShot','Goal','ShotOnPost','BlockedShot'])
- passes = ONLY df['type']=='Pass'
- saves = ONLY df['type']=='Save'
- team filter: use df['team'].str.contains(..., case=False, na=False)
- "who had the most X?" ALWAYS returns .groupby('playerName').size().idxmax()
- "how many X?" returns a scalar via .shape[0] or .sum()
- When returning a filtered DataFrame, return the FULL filtered df
- If the df is pre-filtered for a player, just filter by event type"""
    user = f"Schema:\n{schema}\n\nQuestion: {question}"
    raw = call_llm(system, user).strip()
    import re as _re
    raw = _re.sub(r"^```[a-zA-Z]*\n?", "", raw).strip()
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
                    "is_key_pass", "is_cross", "is_long_ball", "is_through_ball",
                    "is_corner", "is_freekick", "is_header", "is_big_chance", "xT"]

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
            # a filtered DataFrame — apply it
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
                f"No matching events found — the filter returned no data. "
                f"Teams in this CSV: {teams}"
            )
        raise ValueError(f"Could not compute: {err}  [code: {code_norm}]")


BOOL_COL_TO_FLAG = {
    "is_key_pass":        "key_passes_only",
    "is_cross":           "crosses_only",
    "is_long_ball":       "long_balls_only",
    "is_through_ball":    "through_balls_only",
    "is_corner":          "corners_only",
    "is_freekick":        "freekicks_only",
    "is_header":          "headers_only",
    "is_big_chance_shot": "big_chances_only",          # the big chance shot itself
    "is_big_chance":      "big_chances_created_only",  # pass that created a big chance
}

def parse_filters(instruction, df, available_types):
    import re as _re
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
        hints = [f'"{orig}" → use player_filter="{matched}"' for orig, matched in resolved_names]
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
- "half_filter": "1st half only", "2nd half only", or "Both halves"
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
- For duels: use filter_types=["Tackle", "TakeOn", "Aerial", "Challenge"]
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
- "shots" means ALL shot types above — never omit any unless the user specifies a subtype
- NEVER invent event type names — ONLY use exact names from the available list
- For through balls: set "through_balls_only": true (NOT filter_types)
- For key passes: set "key_passes_only": true (NOT filter_types)
- For crosses: set "crosses_only": true (NOT filter_types)
- For long balls: set "long_balls_only": true (NOT filter_types)
- For headers: set "headers_only": true (NOT filter_types)
- For corners: set "corners_only": true (NOT filter_types)
- For free kicks: set "freekicks_only": true (NOT filter_types)
- For big chances (the shot itself): set "big_chances_only": true (NOT filter_types)
- For big chances created (the pass that created a big chance): set "big_chances_created_only": true (NOT filter_types)

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
  "through_balls_only": false,
  "corners_only": false,
  "freekicks_only": false,
  "headers_only": false,
  "big_chances_only": false,
  "big_chances_created_only": false,
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
        json_match = _re2.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw or "")
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
                json_match2 = _re2.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw or "")
                if json_match2:
                    raw = json_match2.group(0)
                else:
                    raise ValueError(f"AI did not return valid JSON. Response: {(raw or '(empty)')[:200]}")

    result = json.loads(raw)

    FLAG_NAMES = {"long_balls_only", "successful_only", "unsuccessful_only", "progressive_only",
                  "key_passes_only", "crosses_only", "through_balls_only",
                  "corners_only", "freekicks_only", "headers_only",
                  "big_chances_only", "big_chances_created_only"}
    bad = [v for v in result.get("filter_types", []) if v in FLAG_NAMES]
    for flag in bad:
        result["filter_types"].remove(flag)
        result[flag] = True

    # ── Post-processing: strip hallucinated flags ──
    # The LLM often sets flags the user never asked for. Only allow flags
    # that match keywords actually present in the instruction.
    instr_lower = instruction.lower()

    FLAG_KEYWORD_MAP = {
        "progressive_only":       ["progressive", "prog pass", "prog carry"],
        "successful_only":        ["successful", "completed", "success"],
        "unsuccessful_only":      ["unsuccessful", "failed", "incomplete", "missed"],
        "key_passes_only":        ["key pass", "key passes"],
        "crosses_only":           ["cross", "crosses"],
        "long_balls_only":        ["long ball", "long balls"],
        "through_balls_only":     ["through ball", "through balls"],
        "corners_only":           ["corner", "corners"],
        "freekicks_only":         ["free kick", "free kicks", "freekick"],
        "headers_only":           ["header", "headers", "headed"],
        "big_chances_only":       ["big chance", "big chances"],
        "big_chances_created_only": ["big chance created", "big chances created",
                                     "chance created", "chances created"],
    }

    for flag, keywords in FLAG_KEYWORD_MAP.items():
        if result.get(flag) and not any(kw in instr_lower for kw in keywords):
            result[flag] = False

    # ── Keyword-based overrides for common requests ──
    # These catch cases where the LLM maps to wrong filter_types

    # "through ball(s)" → through_balls_only flag, not filter_types
    if _re.search(r"\bthrough\s*ball", instr_lower):
        result["through_balls_only"] = True
        # Remove wrong filter_types the LLM might have set
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t not in ("Carry", "Pass")]

    # "key pass(es)" → key_passes_only flag
    if _re.search(r"\bkey\s*pass", instr_lower):
        result["key_passes_only"] = True
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t not in ("Pass",)]

    # "cross(es)" → crosses_only flag
    if _re.search(r"\bcross(?:es)?\b", instr_lower) and "crossbar" not in instr_lower:
        result["crosses_only"] = True

    # "long ball(s)" → long_balls_only flag
    if _re.search(r"\blong\s*ball", instr_lower):
        result["long_balls_only"] = True

    # "header(s)" → headers_only flag
    if _re.search(r"\bheader", instr_lower):
        result["headers_only"] = True

    # "corner(s)" → corners_only flag
    if _re.search(r"\bcorner", instr_lower):
        result["corners_only"] = True

    # "free kick(s)" → freekicks_only flag
    if _re.search(r"\bfree\s*kick", instr_lower):
        result["freekicks_only"] = True

    # ── When a boolean flag is active, only keep filter_types the user asked for ──
    # The LLM often adds filter_types that the user didn't request.
    # e.g. "all big chances" → LLM adds shot types, but big chances can be passes too.
    # Only keep filter_types if the user's words explicitly match a type keyword.
    BOOL_FLAGS = ["key_passes_only", "crosses_only", "long_balls_only",
                  "through_balls_only", "corners_only", "freekicks_only",
                  "headers_only", "big_chances_only", "big_chances_created_only"]
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
            r"\bduel":          {"Tackle", "TakeOn", "Aerial", "Challenge"},
            r"\bchallenge":     {"Challenge"},
            r"\btouch":         {"BallTouch"},
            r"\bdispossess":    {"Dispossessed"},
            r"\boffside":       {"OffsideGiven", "OffsidePass", "OffsideProvoked"},
            r"\bpenalt":        {"PenaltyFaced"},
            r"\bpunch":         {"Punch"},
            r"\bsub(?:stitut)": {"SubstitutionOn", "SubstitutionOff"},
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
            # User didn't mention any type → clear filter_types, let boolean flag work alone
            result["filter_types"] = []

    # "big chances created" → big_chances_created_only flag (pass that created big chance)
    if _re.search(r"\bbig\s*chance[sd]?\s*creat|\bcreat\w*\b.*\bbig\s*chance", instr_lower):
        result["big_chances_created_only"] = True
        result["big_chances_only"] = False
        result["filter_types"] = [t for t in result.get("filter_types", [])
                                  if t not in ("MissedShot", "SavedShot", "Goal", "BlockedShot")]

    # "take on(s)" / "dribble(s)" → filter_types TakeOn
    if _re.search(r"\btake\s*on", instr_lower) or _re.search(r"\bdribble", instr_lower):
        if "TakeOn" in available_types:
            result["filter_types"] = ["TakeOn"]

    # "tackle(s)" → filter_types Tackle
    if _re.search(r"\btackle", instr_lower):
        if "Tackle" in available_types:
            result["filter_types"] = ["Tackle"]

    # "shot(s)" → all shot types
    if _re.search(r"\bshot", instr_lower) and not _re.search(r"\btake\b", instr_lower):
        shot_types = [t for t in ["MissedShot", "SavedShot", "Goal", "ShotOnPost", "BlockedShot"]
                      if t in available_types]
        if shot_types:
            result["filter_types"] = shot_types

    # "aerial(s)" → filter_types Aerial
    if _re.search(r"\baerial", instr_lower):
        if "Aerial" in available_types:
            result["filter_types"] = ["Aerial"]

    # "duel(s)" → all duel types
    if _re.search(r"\bduel", instr_lower):
        duel_types = [t for t in ["Tackle", "TakeOn", "Aerial", "Challenge"]
                      if t in available_types]
        if duel_types:
            result["filter_types"] = duel_types

    # "challenge(s)" → Challenge
    if _re.search(r"\bchallenge", instr_lower):
        if "Challenge" in available_types:
            result["filter_types"] = ["Challenge"]

    # "ball touch(es)" / "touch(es)" → BallTouch
    if _re.search(r"\bball\s*touch|\bball\s*touches", instr_lower):
        if "BallTouch" in available_types:
            result["filter_types"] = ["BallTouch"]

    # "dispossessed" → Dispossessed
    if _re.search(r"\bdispossess", instr_lower):
        if "Dispossessed" in available_types:
            result["filter_types"] = ["Dispossessed"]

    # "offside" → all offside types
    if _re.search(r"\boffside", instr_lower):
        offside_types = [t for t in ["OffsideGiven", "OffsidePass", "OffsideProvoked"]
                         if t in available_types]
        if offside_types:
            result["filter_types"] = offside_types

    # "penalty" / "penalties" → PenaltyFaced
    if _re.search(r"\bpenalt(?:y|ies)", instr_lower):
        if "PenaltyFaced" in available_types:
            result["filter_types"] = ["PenaltyFaced"]

    # "punch(es)" → Punch
    if _re.search(r"\bpunch(?:es)?\b", instr_lower):
        if "Punch" in available_types:
            result["filter_types"] = ["Punch"]

    # "substitution(s)" / "sub(s)" → SubstitutionOn + SubstitutionOff
    if _re.search(r"\bsub(?:stitution)?s?\b", instr_lower):
        sub_types = [t for t in ["SubstitutionOn", "SubstitutionOff"]
                     if t in available_types]
        if sub_types:
            result["filter_types"] = sub_types

    # "claim(s)" → Claim
    if _re.search(r"\bclaim", instr_lower):
        if "Claim" in available_types:
            result["filter_types"] = ["Claim"]

    # "ball recovery" / "recoveries" → BallRecovery
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
# FILTER SNAPSHOTS
# Snapshots are persisted as a JSON dict in config/snapshots.json,
# keyed by snapshot name, value is the saved filter config dict.
# =============================================================================

_SNAPSHOTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config", "snapshots.json"
)


def _load_snapshots_store():
    if os.path.exists(_SNAPSHOTS_PATH):
        try:
            with open(_SNAPSHOTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_snapshots_store(store):
    os.makedirs(os.path.dirname(_SNAPSHOTS_PATH), exist_ok=True)
    with open(_SNAPSHOTS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def save_filter_snapshot(name, data):
    """Persist a named filter configuration snapshot."""
    store = _load_snapshots_store()
    store[name] = data
    _save_snapshots_store(store)


def load_filter_snapshot(name):
    """Return the saved filter config dict for *name*, or None if not found."""
    store = _load_snapshots_store()
    return store.get(name)


def list_snapshots():
    """Return a sorted list of saved snapshot names."""
    return sorted(_load_snapshots_store().keys())


def delete_snapshot(name):
    """Delete a snapshot by name. No-op if it does not exist."""
    store = _load_snapshots_store()
    if name in store:
        del store[name]
        _save_snapshots_store(store)

