import sys
import os
import threading
import queue
import time
import platform
import json
import pandas as pd
import streamlit as st


# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="ClipMaker v1.2 by B4L1", page_icon="ClipMaker_logo.png", layout="wide")

st.markdown("""
<style>
@import url('https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css');

.block-container {
    padding-top: 1.6rem !important;
    padding-bottom: 2rem !important;
    max-width: 1200px !important;
}

.cm-header {
    display: flex;
    align-items: center;
    gap: 14px;
    margin: 0 0 4px;
    padding: 14px 0 6px;
    min-height: 74px;
    overflow: visible;
}
.cm-header-title {
    margin: 0;
    line-height: 1.2;
    font-size: 2rem;
    font-weight: 600;
}

.cm-hero {
    padding: 20px 0 14px;
    margin-bottom: 14px;
}
.cm-hero h1 {
    font-size: 1.4rem !important;
    font-weight: 600 !important;
    margin: 0 0 4px !important;
    line-height: 1.3 !important;
}
.cm-hero p {
    margin: 0;
    font-size: 0.95rem;
}

.cm-section {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0 0 8px;
    margin: 18px 0 10px;
}
.cm-section.first { margin-top: 4px; }

.cm-info {
    padding: 10px 12px;
    border-radius: 6px;
    margin: 8px 0 14px;
    line-height: 1.5;
    border: 1px solid rgba(127, 127, 127, 0.35);
}

.log-box {
    font-family: 'JetBrains Mono','Fira Code','Cascadia Code','Courier New',monospace;
    font-size: 12px;
    padding: 12px 14px;
    border-radius: 6px;
    min-height: 220px;
    max-height: 320px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.55;
    border: 1px solid rgba(127, 127, 127, 0.35);
    background: transparent;
    color: inherit;
}

.progress-label {
    font-size: 12px;
    opacity: 0.8;
    margin-bottom: 6px;
}

.ai-box {
    font-family: 'JetBrains Mono','Fira Code','Cascadia Code','Courier New',monospace;
    font-size: 12px;
    padding: 12px 14px;
    border-radius: 6px;
    white-space: pre-wrap;
    line-height: 1.55;
    border: 1px solid rgba(127, 127, 127, 0.35);
    background: transparent;
    color: inherit;
    margin-bottom: 12px;
}

.footer {
    text-align: center;
    font-size: 10px;
    padding: 24px 0 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.7;
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# FILE / FOLDER DIALOG HELPERS
# Windows: tkinter native dialogs
# macOS:   st.file_uploader (tkinter crashes Cocoa main thread on Mac)
# =============================================================================

IS_MAC = platform.system() == "Darwin"

def _pick_file_thread(result_queue, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw()
    try:
        root.wm_attributes("-topmost", True)
    except Exception:
        pass
    path = filedialog.askopenfilename(filetypes=filetypes)
    root.destroy()
    result_queue.put(path)

def _pick_folder_thread(result_queue):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw()
    try:
        root.wm_attributes("-topmost", True)
    except Exception:
        pass
    path = filedialog.askdirectory()
    root.destroy()
    result_queue.put(path)

def browse_file(filetypes):
    """Windows only — open a native file dialog via tkinter."""
    if IS_MAC:
        return ""
    q = queue.Queue()
    t = threading.Thread(target=_pick_file_thread, args=(q, filetypes), daemon=True)
    t.start(); t.join(timeout=60)
    try: return q.get_nowait()
    except queue.Empty: return ""

def browse_folder():
    """Windows only — open a native folder dialog via tkinter."""
    if IS_MAC:
        return ""
    q = queue.Queue()
    t = threading.Thread(target=_pick_folder_thread, args=(q,), daemon=True)
    t.start(); t.join(timeout=60)
    try: return q.get_nowait()
    except queue.Empty: return ""

def _save_uploaded_file(uploaded_file):
    """Save a Streamlit-uploaded file to a temp location and return its path."""
    import tempfile
    suffix = os.path.splitext(uploaded_file.name)[1]
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(uploaded_file.read())
    tmp.close()
    return tmp.name

# =============================================================================
# CORE LOGIC
# =============================================================================

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "ExtraTimeFirstHalf": 3, "ExtraTimeSecondHalf": 4,
    "FirstPeriodOfExtraTime": 3, "SecondPeriodOfExtraTime": 4,
    1: 1, 2: 2, 3: 3, 4: 4,
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
            # Silently drop non-match periods (PreMatch, PostGame, etc.)
            df = df[~unknown].copy()
        if df.empty:
            raise ValueError(f"No events remaining after dropping unrecognised periods: {bad}")
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
    """
    Monitors output file size in a background thread to estimate
    encoding progress. Pushes updates to progress_queue until stop_event is set.
    Estimated file size = (total_frames / fps) * bitrate_estimate
    """
    import os, time
    # Wait for file to be created
    for _ in range(20):
        if os.path.exists(out_path):
            break
        time.sleep(0.5)

    # Estimate final file size from a ~2Mbps bitrate baseline
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
    """Windows are tuples of (start, end, label, period).
    Only merge windows from the same period (same video file in split mode)."""
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

def apply_filters(df, config):
    """Apply xT, progressive, and action type filters."""
    original = len(df)

    # Action type filter
    if config.get("filter_types"):
        selected = config["filter_types"]
        if selected:
            df = df[df["type"].isin(selected)]

    # Progressive actions filter
    if config.get("progressive_only"):
        prog_cols = [c for c in ["prog_pass", "prog_carry"] if c in df.columns]
        if prog_cols:
            mask = df[prog_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
            df = df[(mask > 0).any(axis=1)]

    # Key pass filter
    if config.get("key_passes_only") and "is_key_pass" in df.columns:
        df = df[df["is_key_pass"].astype(str).str.lower().isin(["true", "1", "yes"])]

    # Pass type filters
    for flag, col in [
        ("crosses_only",      "is_cross"),
        ("long_balls_only",   "is_long_ball"),
        ("through_balls_only","is_through_ball"),
        ("corners_only",      "is_corner"),
        ("freekicks_only",    "is_freekick"),
        ("headers_only",      "is_header"),
        ("big_chances_only",  "is_big_chance"),
    ]:
        if config.get(flag) and col in df.columns:
            df = df[df[col].astype(str).str.lower().isin(["true", "1", "yes"])]

    # Outcome filters
    if config.get("successful_only") and "outcomeType" in df.columns:
        df = df[df["outcomeType"] == "Successful"]
    if config.get("unsuccessful_only") and "outcomeType" in df.columns:
        df = df[df["outcomeType"] == "Unsuccessful"]

    # xT filter
    if config.get("xt_min") is not None and "xT" in df.columns:
        xt_min = config["xt_min"]
        if xt_min > 0:
            df = df[pd.to_numeric(df["xT"], errors="coerce").fillna(0) >= xt_min]

    # Minute range filter
    if config.get("minute_min") is not None and "minute" in df.columns:
        df = df[pd.to_numeric(df["minute"], errors="coerce").fillna(0) >= config["minute_min"]]
    if config.get("minute_max") is not None and "minute" in df.columns:
        df = df[pd.to_numeric(df["minute"], errors="coerce").fillna(0) <= config["minute_max"]]

    # Top N by xT
    if config.get("top_n") and "xT" in df.columns:
        n = config["top_n"]
        df = df.copy()
        df["_xt_num"] = pd.to_numeric(df["xT"], errors="coerce").fillna(0)
        df = df.nlargest(n, "_xt_num").drop(columns=["_xt_num"])

    return df, original - len(df)

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

        # In split mode each period's timestamp is relative to its own file.
        # period_start stores kick-off position within each file.
        # In single-file mode period_start stores position in the one file.
        period_start = {
            1: to_seconds(config["half1_time"]),
            2: to_seconds(config["half2_time"]),
        }
        if config["half3_time"].strip():
            period_start[3] = to_seconds(config["half3_time"])
        if config["half4_time"].strip():
            period_start[4] = to_seconds(config["half4_time"])

        # In split mode: each file starts from its own clock zero.
        # Period offset is always the match clock at kick-off of that period.
        # In single-file mode: period_start already accounts for the global offset.
        if split_video:
            # Each file is independent — period offset is match clock at KO
            period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}
        else:
            period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}

        fallback = config["fallback_row"]
        period_col = config["period_column"] or None
        df = assign_periods(df, period_col, fallback)

        # Apply half filter
        half_filter = config.get("half_filter", "Both halves")
        if half_filter == "1st half only":
            df = df[df["resolved_period"] == 1]
            log("Filtering to 1st half only.")
        elif half_filter == "2nd half only":
            df = df[df["resolved_period"] == 2]
            log("Filtering to 2nd half only.")

        # Apply filters
        df, filtered_count = apply_filters(df, config)
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
            """Get the FFmpeg binary path — from PATH or MoviePy's bundled copy."""
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
            """Get video duration in seconds using ffmpeg -i stderr output."""
            import subprocess, re
            r = subprocess.run(
                [ffmpeg_bin, "-i", path],
                capture_output=True, text=True
            )
            output = r.stdout + r.stderr
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", output)
            if not m:
                raise ValueError(f"Could not determine duration of {path}")
            return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

        def cut_clip_ffmpeg(ffmpeg_bin, src_path, start, end, out_path):
            """Cut a clip directly with FFmpeg — bypasses MoviePy entirely.
            Uses stream copy for speed when possible, falls back to re-encode."""
            import subprocess
            duration = end - start
            # -map 0:v:0 -map 0:a:0 picks first video and first audio stream
            # -avoid_negative_ts make_zero fixes timestamp issues in .mkv files
            cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", str(start),
                "-i", src_path,
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a:0?",   # optional audio — won't fail if missing
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                out_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise ValueError(f"FFmpeg error cutting clip: {result.stderr[-500:]}")

        def cut_and_concat_ffmpeg(ffmpeg_bin, clip_specs, out_path, progress_queue, start_time):
            """Cut all clips and concatenate using FFmpeg concat demuxer."""
            import subprocess, tempfile
            tmp_dir = tempfile.mkdtemp()
            tmp_files = []
            total = len(clip_specs)

            for i, (src, start, end) in enumerate(clip_specs, 1):
                tmp_path = os.path.join(tmp_dir, f"part_{i:04d}.mp4")
                if start is None and end is None:
                    # Pre-rendered clip (e.g. replay) — copy directly
                    import shutil as _shutil
                    _shutil.copy2(src, tmp_path)
                else:
                    cut_clip_ffmpeg(ffmpeg_bin, src, start, end, tmp_path)
                tmp_files.append(tmp_path)
                elapsed = time.time() - start_time
                progress_queue.put({"current": i, "total": total, "elapsed": elapsed, "phase": "clips"})

            # Write concat list
            # Use forward slashes — FFmpeg concat demuxer chokes on Windows backslashes
            list_path = os.path.join(tmp_dir, "concat.txt")
            with open(list_path, "w", encoding="utf-8") as f:
                for p in tmp_files:
                    p_safe = p.replace(os.sep, "/")
                    f.write(f"file '{p_safe}'\n")

            # Concatenate
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

            # Cleanup
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
            saved = []
            for i, (start, end, label, period) in enumerate(windows, 1):
                src, src_dur = get_src_and_duration(period)
                s = max(0, start)
                e = min(src_dur, end)
                if e <= s:
                    log(f"  SKIPPED clip {i:02d}: {s:.1f}s–{e:.1f}s outside video duration {src_dur:.1f}s")
                    continue
                actions = [pt.split(" @")[0].strip() for pt in label.split(" + ")]
                dominant = max(set(actions), key=actions.count).replace(" ", "_")
                filename = f"{i:02d}_{dominant}.mp4"
                filepath = os.path.join(out_dir, filename)
                log(f"  Rendering {i:02d}/{total_clips}: {filename}")
                cut_clip_ffmpeg(ffmpeg_bin, src, s, e, filepath)

                # Append replay if available — match by (event_type, minute)
                if replay_map:
                    import tempfile
                    for pt in label.split(" + "):
                        action_part = pt.split(" @")[0].strip()
                        # Try to extract minute from label e.g. "TakeOn @ 67:45 P2"
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
                                    mode="w", suffix=".txt", delete=False
                                )
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
                prog(i, total_clips, time.time() - start_time)
            log(f"\n\u2713 {len(saved)} clips saved to: {os.path.abspath(out_dir)}/")
        else:
            clip_specs = []
            for i, (start, end, label, period) in enumerate(windows, 1):
                src, src_dur = get_src_and_duration(period)
                s = max(0, start)
                e = min(src_dur, end)
                if e <= s:
                    log(f"  SKIPPED clip {i:02d}: {s:.1f}s–{e:.1f}s outside video duration {src_dur:.1f}s")
                    continue
                clip_specs.append((src, s, e))

                # Append replay clip into the reel sequence if matched
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
                                clip_specs.append((replay_clip, None, None))  # None = use full file
                                log(f"    + Replay queued for {action_part} {minute_match}′")
                            break

            if not clip_specs:
                log("\n✗ No matching events found — nothing to clip.")
                progress_queue.put({"error": "No matching events found. Try a different filter or check your CSV data."})
                return

            total_dur = sum(e - s for _, s, e in clip_specs)
            log(f"Assembling {len(clip_specs)} clips ({total_dur:.1f}s)...")
            out_path = os.path.join(out_dir, config["output_filename"])

            # For progress bar — estimate based on clip count
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
# AI — GROQ API + PANDAS ENGINE
# =============================================================================

# =============================================================================
# GROQ PROXY SETTINGS
# Deploy the groq-proxy folder to Vercel, then paste your proxy URL below.
# Your actual Groq API key lives on Vercel — never in this file.
# See groq-proxy/README.md for full deployment instructions.
# =============================================================================
GROQ_PROXY_URL = "https://groq-proxy-eight.vercel.app/api/chat"  # <-- update after deploying

# Models ordered by quality — fallback chain works down the list on rate limit (429).
# Guard/safeguard models excluded — those are content classifiers, not chat models.
GROQ_CHAT_MODELS = [
    "llama-3.1-8b-instant",                        # fast, high req/min, payload trimmed for TPM
    "llama-3.3-70b-versatile",                     # stronger fallback if 8b rate-limited
    "meta-llama/llama-4-scout-17b-16e-instruct",   # large context, 30K TPM
    "moonshotai/kimi-k2-instruct",                  # strong reasoning
    "openai/gpt-oss-120b",                          # large model fallback
    "openai/gpt-oss-20b",                           # lighter fallback
    "qwen/qwen3-32b",                               # final fallback
]

def _ping_proxy():
    """Fire a silent warmup request to Vercel so it's awake before the user queries.
    Called once in a background thread at startup — errors are silently ignored."""
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
        pass  # warmup failure is silent — just means cold start may still occur

# Warm up the proxy once per session in the background
if "proxy_warmed" not in st.session_state:
    st.session_state["proxy_warmed"] = True
    import threading
    threading.Thread(target=_ping_proxy, daemon=True).start()


def call_llm(system_prompt, user_message):
    """Send request through the Vercel proxy (which holds the real API key).
    Automatically falls back to the next model if rate-limited (429).
    Retries up to 3 times on connection errors (e.g. Vercel cold start timeout)."""
    import urllib.request, urllib.error, random, time

    # Always try best model first; shuffle the rest to spread load
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
            headers={
                "Content-Type": "application/json",
                "User-Agent":   "ClipMaker/1.2",
            },
            method="POST"
        )
        # Retry up to 3 times on connection/timeout errors (Vercel cold start)
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                if e.code == 429 or "rate_limit" in body.lower():
                    last_error = f"Rate limit on {model}"
                    break  # try next model
                raise ValueError(f"Proxy/API error {e.code} on {model}: {body[:300]}")
            except Exception as e:
                last_error = str(e)
                if attempt < 1:
                    time.sleep(2)  # 2s pause before retry
                    continue
                break  # move to next model

    raise ValueError(f"Could not reach the AI server after multiple attempts. Check your internet connection and try again.")

def read_csv_safe(path):
    """Read CSV trying UTF-8 first, falling back to latin-1 for files saved on Windows.
    Automatically converts boolean-like string columns (TRUE/FALSE/1/0) to proper booleans."""
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1")

    # Convert string TRUE/FALSE columns to proper Python booleans.
    # This ensures == True filters work regardless of how the CSV was exported.
    bool_cols = [c for c in df.columns if c.startswith("is_") or c in ("prog_pass", "prog_carry")]
    for col in bool_cols:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip().str.upper().map(
                {"TRUE": True, "FALSE": False, "1": True, "0": False, "YES": True, "NO": False}
            ).fillna(False).astype(bool)

    return df

def fuzzy_correct_player(name, df):
    """Find the closest real player name in df to a potentially misspelled input.
    Returns (corrected_name, original_input) or (None, None) if no close match found."""
    from difflib import get_close_matches
    import unicodedata

    def _strip(s):
        return "".join(c for c in unicodedata.normalize("NFD", str(s))
                       if unicodedata.category(c) != "Mn").lower()

    if "playerName" not in df.columns:
        return None, None

    all_players  = df["playerName"].dropna().unique().tolist()
    all_stripped = [_strip(p) for p in all_players]
    name_stripped = _strip(name)

    matches = get_close_matches(name_stripped, all_stripped, n=1, cutoff=0.5)
    if matches:
        idx = all_stripped.index(matches[0])
        return all_players[idx], name   # (corrected, original)
    return None, None


def answer_with_pandas(question, df):
    """Translate a natural language question into a pandas expression via Groq and execute it."""
    import unicodedata, re
    cols = list(df.columns)
    sample = df.head(2).to_dict(orient="records")  # 3->2 rows to save tokens
    unique_types   = df["type"].dropna().unique().tolist() if "type" in df.columns else []
    unique_players = df["playerName"].dropna().unique().tolist() if "playerName" in df.columns else []
    unique_periods = df["period"].dropna().unique().tolist() if "period" in df.columns else []

    # Trim player list to stay within token limits (esp. llama-3.1-8b-instant: 6K TPM).
    # The model uses str.contains() for lookups so full list isn't needed —
    # a sample is enough for it to understand the naming convention/format.
    MAX_PLAYERS = 25
    player_list = unique_players[:MAX_PLAYERS]
    player_note = f" (showing {MAX_PLAYERS} of {len(unique_players)})" if len(unique_players) > MAX_PLAYERS else ""

    schema = (
        f"Columns: {cols}\n"
        f"Sample rows: {sample}\n"
        f"Total rows: {len(df)}\n"
        f"Unique event types (EXACT): {unique_types}\n"
        f"Unique player names (EXACT){player_note}: {player_list}\n"
        f"Unique periods (EXACT): {unique_periods}\n"
        f"prog_pass present: {'prog_pass' in df.columns}\n"
        f"prog_carry present: {'prog_carry' in df.columns}\n"
        f"xT present: {'xT' in df.columns}"
    )
    system = """You are a Python/pandas code generator for football data analysis.
Write a single Python expression that answers the question using a DataFrame called `df`.
Return ONLY the expression — no imports, no assignments, no markdown, no explanation.
RULES:
- Use EXACT strings from the schema — never invent type names like 'Carry' or 'Cross' or 'Header'
- Player names: use str.contains(..., case=False, na=False)
- CRITICAL — boolean columns must use ==True, never filter by type name:
    crosses       -> df['is_cross']==True        (NOT type=='Cross')
    headers       -> df['is_header']==True        (NOT type=='Header')
    corners       -> df['is_corner']==True        (NOT type=='Corner')
    freekicks     -> df['is_freekick']==True      (NOT type=='Freekick')
    key passes    -> df['is_key_pass']==True      (NOT type=='KeyPass')
    long balls    -> df['is_long_ball']==True
    through balls -> df['is_through_ball']==True
    big chances   -> df['is_big_chance']==True        (the PASS that created the chance)
    big chance shots/missed big chances -> df['is_big_chance_shot']==True  (the SHOT from a big chance — use outcomeType to filter missed/scored)
- 'carries'/'progressive carries' -> filter prog_carry==True, NOT a type filter
- 'progressive passes' -> filter prog_pass==True, NOT a type filter
- xT filters: use pd.to_numeric(df['xT'], errors='coerce')
- When returning a filtered DataFrame, return the FULL filtered df — do NOT manually select columns
- When returning aggregated results (counts, sums, idxmax), return a Series or scalar
CRITICAL TYPE DEFINITIONS — memorise these exactly:
- shots     = ONLY df['type'].isin(['MissedShots','SavedShot','Goal']) — NEVER 'Shot', NEVER str.contains, NEVER include Clearance/Aerial/BlockedPass
- passes    = ONLY df['type']=='Pass' — NEVER include BlockedPass, BallTouch, KeeperPickup, ShieldBallOpp etc.
- saves     = ONLY df['type']=='Save' — NEVER include SavedShot (that is the shot, not the save)

CRITICAL FILTER RULES:
- team filter: ALWAYS use df['team']=='PSG' — NEVER use df['playerName'].str.contains('PSG')
- NEVER add prog_pass, prog_carry, or xT>0 conditions unless the user explicitly mentions progressive passes, progressive carries, or xT
- "who had the most X?" ALWAYS returns a single player name via .groupby('playerName').size().idxmax() — NEVER value_counts()
- "how many X?" returns a scalar integer via .shape[0] or .sum()
- "how many X per player?" or "rank players by X" returns a Series via .groupby().size().sort_values(ascending=False)

Examples:
  show all shots                     -> df[df['type'].isin(['MissedShots','SavedShot','Goal'])]
  show all passes                    -> df[df['type']=='Pass']
  show all saves                     -> df[df['type']=='Save']
  show Palmer shots                  -> df[df['playerName'].str.contains('Palmer',case=False,na=False)&df['type'].isin(['MissedShots','SavedShot','Goal'])]
  show Chelsea shots                 -> df[(df['team']=='Chelsea')&df['type'].isin(['MissedShots','SavedShot','Goal'])]
  show all PSG crosses               -> df[(df['team']=='PSG')&(df['is_cross']==True)]
  show all PSG headers               -> df[(df['team']=='PSG')&(df['is_header']==True)]
  show all PSG passes                -> df[(df['team']=='PSG')&(df['type']=='Pass')]
  show PSG second half passes        -> df[(df['team']=='PSG')&(df['type']=='Pass')&(df['period']=='SecondHalf')]
  show all successful passes         -> df[(df['type']=='Pass')&(df['outcomeType']=='Successful')]
  show PSG successful passes         -> df[(df['team']=='PSG')&(df['type']=='Pass')&(df['outcomeType']=='Successful')]
  show Vitinha passes                -> df[df['playerName'].str.contains('Vitinha',case=False,na=False)&(df['type']=='Pass')]
  show Vitinha first half passes     -> df[df['playerName'].str.contains('Vitinha',case=False,na=False)&(df['type']=='Pass')&(df['period']=='FirstHalf')]
  show Vitinha unsuccessful passes   -> df[df['playerName'].str.contains('Vitinha',case=False,na=False)&(df['type']=='Pass')&(df['outcomeType']=='Unsuccessful')]
  show all second half shots         -> df[df['type'].isin(['MissedShots','SavedShot','Goal'])&(df['period']=='SecondHalf')]
  show all PSG shots in second half  -> df[(df['team']=='PSG')&df['type'].isin(['MissedShots','SavedShot','Goal'])&(df['period']=='SecondHalf')]
  how many shots did PSG have?       -> df[(df['team']=='PSG')&df['type'].isin(['MissedShots','SavedShot','Goal'])].shape[0]
  how many crosses were there?       -> df[df['is_cross']==True].shape[0]
  who had the most passes?           -> df[df['type']=='Pass'].groupby('playerName').size().idxmax()
  who had the most tackles?          -> df[df['type']=='Tackle'].groupby('playerName').size().idxmax()
  who scored the most goals?         -> df[df['type']=='Goal'].groupby('playerName').size().idxmax()
  who had the most shots?            -> df[df['type'].isin(['MissedShots','SavedShot','Goal'])].groupby('playerName').size().idxmax()
  which PSG player had the most passes? -> df[(df['type']=='Pass')&(df['team']=='PSG')].groupby('playerName').size().idxmax()
  which Chelsea player had the most shots? -> df[df['type'].isin(['MissedShots','SavedShot','Goal'])&(df['team']=='Chelsea')].groupby('playerName').size().idxmax()
  which team had more possession?    -> df[df['type']=='Pass'].groupby('team').size().idxmax()
  which team had more shots?         -> df[df['type'].isin(['MissedShots','SavedShot','Goal'])].groupby('team').size().sort_values(ascending=False)
  rank Chelsea players by tackles    -> df[(df['type']=='Tackle')&(df['team']=='Chelsea')].groupby('playerName').size().sort_values(ascending=False)
  who created the most chances?      -> df[df['is_key_pass']==True].groupby('playerName').size().idxmax()
  who was the most creative player?  -> df[df['is_key_pass']==True].groupby('playerName').size().idxmax()
  who was the most creative PSG player? -> df[(df['is_key_pass']==True)&(df['team']=='PSG')].groupby('playerName').size().idxmax()
  who was the most dangerous player? -> df.assign(_xt=pd.to_numeric(df['xT'],errors='coerce')).groupby('playerName')['_xt'].sum().idxmax() if pd.to_numeric(df['xT'],errors='coerce').sum()>0 else df[(df['prog_pass']==True)|(df['prog_carry']==True)].groupby('playerName').size().idxmax()
  who generated the most threat?     -> df.assign(_xt=pd.to_numeric(df['xT'],errors='coerce')).groupby('playerName')['_xt'].sum().idxmax() if pd.to_numeric(df['xT'],errors='coerce').sum()>0 else df[(df['prog_pass']==True)|(df['prog_carry']==True)].groupby('playerName').size().idxmax()
  most progressive player            -> df[(df['prog_pass']==True)|(df['prog_carry']==True)].groupby('playerName').size().idxmax()
  who had the most big chances?      -> df[df['is_big_chance']==True].groupby('playerName').size().idxmax()
  show big chances missed            -> df[(df['is_big_chance_shot']==True)&(df['outcomeType']=='Unsuccessful')]
  show big chances scored            -> df[(df['is_big_chance_shot']==True)&(df['type']=='Goal')]
  who missed the most big chances?   -> df[(df['is_big_chance_shot']==True)&(df['outcomeType']=='Unsuccessful')].groupby('playerName').size().idxmax()
  top/highest player in each pass type -> pd.DataFrame([{'category': {'is_key_pass':'Key Passes','is_cross':'Crosses','is_long_ball':'Long Balls','is_through_ball':'Through Balls','is_corner':'Corners','is_freekick':'Freekicks','is_header':'Headers','is_big_chance':'Big Chances'}.get(col, col), 'player': df[df[col]==True].groupby('playerName').size().idxmax(), 'count': int(df[df[col]==True].groupby('playerName').size().max())} for col in ['is_key_pass','is_cross','is_long_ball','is_through_ball','is_corner','is_freekick','is_header','is_big_chance'] if df[col].any()])
  show Salah's crosses               -> df[df['playerName'].str.contains('Salah',case=False,na=False)&(df['is_cross']==True)]
  show all headers                   -> df[df['is_header']==True]
  show Estevao's take ons            -> df[df['playerName'].str.contains('Estevao',case=False,na=False)&(df['type']=='TakeOn')]
  show all key passes                -> df[df['is_key_pass']==True]
  top xT events                      -> df.assign(x=pd.to_numeric(df['xT'],errors='coerce')).nlargest(10,'x')
  pass count by player               -> df[df['type']=='Pass'].groupby('playerName').size().sort_values(ascending=False)
  most crosses by player             -> df[df['is_cross']==True].groupby('playerName').size().sort_values(ascending=False)
  pass accuracy by player            -> df[df['type']=='Pass'].groupby('playerName').apply(lambda x: round((x['outcomeType']=='Successful').sum()/len(x)*100,1)).sort_values(ascending=False)
  how many goals were scored?        -> df[df['type']=='Goal'].shape[0]
  show events in last 10 minutes     -> df[df['minute']>=80]
  show all events after minute 75    -> df[df['minute']>75]
  show all events before minute 15   -> df[df['minute']<15]"""
    user = f"Schema:\n{schema}\n\nQuestion: {question}"
    raw = call_llm(system, user).strip()
    # Strip markdown code fences that some models add despite instructions
    import re as _re
    raw = _re.sub(r"^```[a-zA-Z]*\n?", "", raw).strip()
    raw = _re.sub(r"```$", "", raw).strip()
    # If model returned multiple lines, take only the first non-empty line
    # that looks like a pandas expression (starts with df)
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    code = raw  # default
    for line in lines:
        if line.startswith("df"):
            code = line
            break
    code = code.strip().strip("`")
    if code.startswith("python"):
        code = code[6:].strip()
    def strip_accents(s):
        return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")
    df_norm = df.copy()
    if "playerName" in df_norm.columns:
        df_norm["playerName"] = df_norm["playerName"].apply(lambda x: strip_accents(x) if pd.notna(x) else x)
    code_norm = strip_accents(code)
    # Core display columns — shown when result is a DataFrame
    DISPLAY_COLS = ["minute", "second", "type", "outcomeType", "playerName", "team", "period",
                    "is_key_pass", "is_cross", "is_long_ball", "is_through_ball",
                    "is_corner", "is_freekick", "is_header", "is_big_chance", "xT"]

    def _clean_df_result(result):
        """Drop internal columns, reorder and return a clean display DataFrame."""
        drop_cols = ["prog_pass", "prog_carry", "x", "y", "resolved_period",
                     "_xt_num", "video_timestamp"]
        result = result.drop(columns=[c for c in drop_cols if c in result.columns])
        bool_cols = [c for c in result.columns if c.startswith("is_")]
        for c in bool_cols:
            if c in result.columns and not result[c].any():
                result = result.drop(columns=[c])
        result = result.dropna(axis=1, how="all")
        ordered = [c for c in DISPLAY_COLS if c in result.columns]
        extras  = [c for c in result.columns if c not in ordered]
        return result[ordered + extras].reset_index(drop=True)

    def _fuzzy_retry(code, df_norm, question):
        """If a query returns empty, try to find a misspelled player name and retry."""
        # Extract player name candidates from str.contains() calls in the generated code
        pat = r"""str\.contains\([^)]*["']([^"']+)["']"""
        candidates = re.findall(pat, code)
        for candidate in candidates:
            corrected, original = fuzzy_correct_player(candidate, df)
            if corrected and strip_accents(corrected).lower() != strip_accents(candidate).lower():
                # Swap the misspelled name for the corrected one in the code
                corrected_stripped = strip_accents(corrected)
                fixed_code = code.replace(candidate, corrected_stripped)
                try:
                    retry = eval(fixed_code, {"df": df_norm, "pd": pd})
                    if isinstance(retry, pd.DataFrame) and not retry.empty:
                        return retry, corrected, original
                    if isinstance(retry, pd.Series) and not retry.empty:
                        return retry, corrected, original
                except Exception:
                    pass
        return None, None, None

    def _extract_name_from_question(q):
        """Extract a likely player name fragment from the question for validation."""
        import re as _re2
        # Remove common football query words, leaving likely name fragments
        stopwords = {"show","all","the","by","from","in","of","with","who","had",
                     "most","least","best","top","first","half","second","shots",
                     "passes","crosses","headers","corners","freekicks","tackles",
                     "takeons","events","goals","assists","key","progressive",
                     "carries","long","balls","through","big","chances","fouls",
                     "cards","clearances","interceptions","recoveries","s","and","or"}
        words = [w.strip("'s.,?!") for w in q.lower().split()]
        name_words = [w for w in words if w and w not in stopwords and len(w) > 2]
        return name_words

    try:
        result = eval(code_norm, {"df": df_norm, "pd": pd, "SHOT_TYPES": ["MissedShots", "SavedShot", "Goal"]})
        # Guard against idxmax/idxmin on empty series
        if isinstance(result, str) and not result.strip():
            return "No matching events found."

        if isinstance(result, pd.DataFrame):
            if result.empty:
                # Attempt fuzzy player name correction before giving up
                retry_result, corrected, original = _fuzzy_retry(code_norm, df_norm, question)
                if retry_result is not None and isinstance(retry_result, pd.DataFrame):
                    result = _clean_df_result(retry_result)
                    result.attrs["fuzzy_note"] = f"No exact match for '{original}' — showing results for '{corrected}'."
                    return result
                return "No matching events found."

            # Sanity check: if question mentions a player name, verify results contain them.
            # If not, the model ignored the player filter — re-call LLM with corrected name.
            if "playerName" in result.columns:
                name_fragments = _extract_name_from_question(question)
                for frag in name_fragments:
                    corrected, original = fuzzy_correct_player(frag, df)
                    if corrected:
                        corrected_strip = strip_accents(corrected).lower()
                        result_names = result["playerName"].apply(
                            lambda x: strip_accents(str(x)).lower()
                        )
                        if not result_names.str.contains(
                            corrected_strip.split()[-1], na=False
                        ).any():
                            # Model ignored player — re-ask LLM with the real name substituted in
                            corrected_question = question.lower().replace(
                                frag, corrected
                            ) if frag in question.lower() else f"{question} (player name is '{corrected}')"
                            try:
                                retry_code = call_llm(system, f"Schema:\n{schema}\n\nQuestion: {corrected_question}")
                                retry_code = retry_code.strip().strip("`")
                                if retry_code.startswith("python"):
                                    retry_code = retry_code[6:].strip()
                                retry_code_norm = strip_accents(retry_code)
                                retry = eval(retry_code_norm, {"df": df_norm, "pd": pd})
                                if isinstance(retry, pd.DataFrame) and not retry.empty:
                                    result = retry
                                    result.attrs["fuzzy_note"] = f"Showing results for '{corrected}'."
                            except Exception:
                                pass
                        break  # only check first name fragment

            # Drop internal/reserved columns and NaN-only columns
            return _clean_df_result(result)

        if isinstance(result, pd.Series):
            if result.empty:
                return "No matching events found."
            return result.reset_index().rename(columns={"index": "player", 0: "count"}) if result.index.name else result

        return str(result) if str(result).strip() else "No matching events found."

    except Exception as e:
        err = str(e)
        if "argmax of an empty sequence" in err or "argmin of an empty sequence" in err:
            # Friendly message for empty filter results (wrong team, player, type etc.)
            teams = df["team"].dropna().unique().tolist() if "team" in df.columns else []
            raise ValueError(
                f"No matching events found — the filter returned no data. "
                f"Check that team/player names match the data. "
                f"Teams in this CSV: {teams}"
            )
        raise ValueError(f"Could not compute: {err}  [code: {code_norm}]")

# Maps CSV boolean columns to their JSON config flag names
BOOL_COL_TO_FLAG = {
    "is_key_pass":      "key_passes_only",
    "is_cross":         "crosses_only",
    "is_long_ball":     "long_balls_only",
    "is_through_ball":  "through_balls_only",
    "is_corner":        "corners_only",
    "is_freekick":      "freekicks_only",
    "is_header":        "headers_only",
    "is_big_chance":    "big_chances_only",
    "is_big_chance_shot": "big_chance_shots_only",
}

def parse_filters(instruction, df, available_types):
    """Translate a plain English clip request into a ClipMaker filter config via Groq."""
    has_xt   = "xT" in df.columns
    has_prog = "prog_pass" in df.columns or "prog_carry" in df.columns
    players  = df["playerName"].dropna().unique().tolist() if "playerName" in df.columns else []
    periods  = df["period"].dropna().unique().tolist() if "period" in df.columns else []
    teams    = df["team"].dropna().unique().tolist() if "team" in df.columns else []

    # Detect which boolean columns are actually present and have True values in this CSV
    active_bool_cols = {
        col: flag for col, flag in BOOL_COL_TO_FLAG.items()
        if col in df.columns and df[col].any()
    }
    bool_flag_docs = "\n".join(
        f'  - Set "{flag}": true for {col.replace("is_","").replace("_"," ")} events (column: {col})'
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

BOOLEAN FLAGS AVAILABLE IN THIS CSV (use these when relevant):
{bool_flag_docs}
- Use "successful_only": true when the user says "successful", "completed", "accurate", "good", "correct", "on target", or any word implying the action worked.
- Use "unsuccessful_only": true when the user says "unsuccessful", "failed", "bad", "inaccurate", "missed", "wrong", "incomplete", or any word implying the action did NOT work.
- Use "progressive_only": true only when the user explicitly asks for progressive passes/carries.

IMPORTANT RULES:
- "filter_types": ONLY use actual event type names from the available list (e.g. "Pass", "Goal", "MissedShots", "SavedShot", "Tackle"). NEVER put flag names here.
- "team_filter": use for team requests (e.g. "Chelsea players" -> "Chelsea"). NEVER list individual players here.
- "player_filter": a comma-separated string of player names (e.g. "Cole Palmer, Pedro Neto" or just "Cole Palmer"). Use this for one or more specific players. Do NOT use team_filter when listing specific players by name.
- "half_filter": use "1st half only", "2nd half only", or "Both halves".
- "successful_only": true when user says "successful" or "completed".
- "unsuccessful_only": true when user says "unsuccessful", "failed", or "missed" (except shots — use filter_types=["MissedShots"] for missed shots).
- "minute_min" / "minute_max": use for time range requests. e.g. "last 15 minutes" of a 90-min game -> minute_min=75. "first half" -> use half_filter instead.
- "xt_min": use when user asks for high-threat or dangerous events (requires xT column).
- "top_n": use when user asks for "top N" events by xT value.
- "progressive_only": true only when user explicitly asks for progressive passes/carries.
- ALL boolean flags are top-level JSON keys, NEVER values inside filter_types.
- For pass-subtype requests (key passes, long balls, crosses, headers etc): set filter_types=["Pass"] AND the boolean flag to true.
- NEVER leave filter_types=[] when a pass-subtype boolean flag is true — always pair with filter_types=["Pass"].
- For shots: use filter_types=["MissedShots", "SavedShot", "Goal"] — there is no type called "Shot".
- For saves: use filter_types=["Save"].
- For tackles: use filter_types=["Tackle"].

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
  "long_balls_only": false,
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
    result = json.loads(raw.strip())

    # Defensive cleanup — move any flag names accidentally placed in filter_types
    FLAG_NAMES = {"long_balls_only", "successful_only", "unsuccessful_only", "progressive_only",
                  "key_passes_only", "crosses_only", "through_balls_only",
                  "corners_only", "freekicks_only", "headers_only", "big_chances_only"}
    bad = [v for v in result.get("filter_types", []) if v in FLAG_NAMES]
    for flag in bad:
        result["filter_types"].remove(flag)
        result[flag] = True  # promote to top-level flag

    return result

def render_stats_panel(df):
    """Render a pre-computed match data summary from the CSV."""
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
# SESSION STATE
# =============================================================================
for key, default in [
    ("video_path", ""), ("video2_path", ""), ("csv_path", ""), ("output_dir", ""),
    ("half1_time", ""), ("half2_time", ""), ("half3_time", ""), ("half4_time", ""),
    ("split_video", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# Auto-populate csv_path from WhoScored scraper result whenever it's fresher
_scraped = st.session_state.get("scraped_csv_path", "")
if _scraped and _scraped != st.session_state.csv_path:
    st.session_state.csv_path = _scraped

# Restore replay_map from disk if session state was cleared by page navigation
if not st.session_state.get("replay_map"):
    _map_path = st.session_state.get("replay_map_path", "")
    if _map_path and os.path.exists(_map_path):
        try:
            import json as _json
            with open(_map_path) as _f:
                _json_map = _json.load(_f)
            # Restore string keys back to (event_type, minute) tuples
            st.session_state["replay_map"] = {
                (k.split("||")[0], int(k.split("||")[1]) if k.split("||")[1] != "None" else None): v
                for k, v in _json_map.items()
            }
        except Exception:
            pass

# =============================================================================
# UI
# =============================================================================

try:
    with open("ClipMaker_logo.png", "rb") as _f:
        _logo_b64 = __import__("base64").b64encode(_f.read()).decode()
    st.markdown(f"""
        <div class='cm-header'>
            <img src='data:image/png;base64,{_logo_b64}' style='width:64px;height:64px;object-fit:contain;display:block;'/>
            <div class='cm-header-title'>ClipMaker v1.2 by B4L1</div>
        </div>""", unsafe_allow_html=True)
except Exception:
    st.title("ClipMaker v1.2 by B4L1")
st.caption("Football highlight reel generator from match event data")

# Onboarding banner — shown until a CSV is loaded
if not st.session_state.csv_path:
    st.info("Start by scraping a match on the WhoScored Scraper page in the sidebar. Your CSV will load here automatically.")
else:
    _loaded_name = os.path.basename(st.session_state.csv_path)
    st.success(f"CSV loaded: **{_loaded_name}**")

st.divider()
split_video = st.session_state.get("split_video", False)
video_path = st.session_state.video_path
video2_path = st.session_state.video2_path
csv_path = st.session_state.csv_path
half1 = st.session_state.half1_time
half2 = st.session_state.half2_time
half3 = st.session_state.half3_time
half4 = st.session_state.half4_time
half_filter = "Both halves"
period_col = "period"
fallback_row = 0
use_fallback = False
before_buf = 3
after_buf = 8
min_gap = 6
out_dir_input = st.session_state.output_dir
individual = False
out_filename = "Highlights.mp4"
dry_run = False
append_replays = bool(st.session_state.get("replay_map"))

team_filter = "All players"
player_filter = "All players"
filter_types = []
selected_pass_types = []
key_passes_only = False
progressive_only = False
xt_min = 0.0
top_n = 0

ai_input = ""
ask_btn = False
make_clips_ai_btn = False
run_btn = False
ai_answer_placeholder = st.empty()

tabs = st.tabs(["Files & Times", "Clip Settings", "Filters & AI"])

with tabs[0]:
    st.markdown('<div class="cm-section first"><i class="ph ph-files"></i>Files</div>', unsafe_allow_html=True)

    split_video = st.checkbox(
        "Match is split into two separate video files (1st/2nd half)",
        value=st.session_state.get("split_video", False)
    )
    st.session_state["split_video"] = split_video

    lbl1 = "1st Half Video File" if split_video else "Video File"
    if IS_MAC:
        _up1 = st.file_uploader(lbl1, type=["mp4", "mkv", "avi", "mov"], key="up_video1")
        if _up1:
            _p = _save_uploaded_file(_up1)
            if _p != st.session_state.video_path:
                st.session_state.video_path = _p
                st.rerun()
        video_path = st.session_state.video_path
        if video_path:
            st.caption(os.path.basename(video_path))
    else:
        vc1, vc2 = st.columns([4, 1])
        with vc1:
            video_path = st.text_input(lbl1, value=st.session_state.video_path,
                                       placeholder="Click Browse or paste full path")
        with vc2:
            st.write("")
            st.write("")
            if st.button("Browse", key="browse_video"):
                picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
                if picked:
                    st.session_state.video_path = picked
                    st.rerun()

    if split_video:
        if IS_MAC:
            _up2 = st.file_uploader("2nd Half Video File", type=["mp4", "mkv", "avi", "mov"], key="up_video2")
            if _up2:
                _p2 = _save_uploaded_file(_up2)
                if _p2 != st.session_state.video2_path:
                    st.session_state.video2_path = _p2
                    st.rerun()
            video2_path = st.session_state.video2_path
            if video2_path:
                st.caption(os.path.basename(video2_path))
        else:
            v2c1, v2c2 = st.columns([4, 1])
            with v2c1:
                video2_path = st.text_input("2nd Half Video File", value=st.session_state.video2_path,
                                            placeholder="Click Browse or paste full path")
            with v2c2:
                st.write("")
                st.write("")
                if st.button("Browse", key="browse_video2"):
                    picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
                    if picked:
                        st.session_state.video2_path = picked
                        st.rerun()
    else:
        video2_path = ""

    _from_scraper = (st.session_state.get("scraped_csv_path")
                     and st.session_state.csv_path == st.session_state.scraped_csv_path)
    if IS_MAC:
        if not _from_scraper:
            _upc = st.file_uploader("CSV File", type=["csv"], key="up_csv")
            if _upc:
                _pc = _save_uploaded_file(_upc)
                if _pc != st.session_state.csv_path:
                    st.session_state.csv_path = _pc
                    st.rerun()
        csv_path = st.session_state.csv_path
    else:
        cc1, cc2 = st.columns([4, 1])
        with cc1:
            csv_path = st.text_input("CSV File", value=st.session_state.csv_path,
                                     placeholder="Click Browse or scrape a match first")
        with cc2:
            st.write("")
            st.write("")
            if st.button("Browse", key="browse_csv"):
                picked = browse_file([("CSV files", "*.csv"), ("All files", "*.*")])
                if picked:
                    st.session_state.csv_path = picked
                    st.rerun()

    if _from_scraper:
        c1, c2 = st.columns([3, 1])
        c1.caption("Loaded from WhoScored Scraper")
        if c2.button("Clear", key="clear_csv"):
            st.session_state.csv_path = ""
            st.session_state["scraped_csv_path"] = ""
            st.session_state["scraped_csv_df"] = ""
            st.rerun()
    elif st.session_state.csv_path:
        st.caption(os.path.basename(st.session_state.csv_path))

    st.markdown('<div class="cm-section"><i class="ph ph-clock"></i>Kick-off Timestamps</div>', unsafe_allow_html=True)
    if split_video:
        st.caption("Enter the time shown at kick-off in each video file.")
    else:
        st.caption("Enter exactly what your player shows at kick-off: MM:SS or HH:MM:SS.")

    tc1, tc2 = st.columns(2)
    with tc1:
        half1 = st.text_input("1st Half kick-off", value=st.session_state.half1_time, placeholder="e.g. 4:16")
        half3 = st.text_input("ET 1st Half (optional)", value=st.session_state.half3_time, placeholder="leave blank")
    with tc2:
        half2 = st.text_input("2nd Half kick-off", value=st.session_state.half2_time,
                              placeholder="e.g. 0:45" if split_video else "e.g. 1:00:32")
        half4 = st.text_input("ET 2nd Half (optional)", value=st.session_state.half4_time, placeholder="leave blank")

    if half1:
        st.session_state.half1_time = half1
    if half2:
        st.session_state.half2_time = half2
    if half3:
        st.session_state.half3_time = half3
    if half4:
        st.session_state.half4_time = half4

    half_filter = st.selectbox(
        "Halves to include",
        options=["Both halves", "1st half only", "2nd half only"],
        help="Limit clips to one half if needed."
    )

with tabs[1]:
    period_col = "period"
    fallback_row = 0
    use_fallback = False

    st.markdown('<div class="cm-section first"><i class="ph ph-scissors"></i>Clip Settings</div>', unsafe_allow_html=True)
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        before_buf = st.number_input("Before (s)", value=3, min_value=0)
    with sc2:
        after_buf = st.number_input("After (s)", value=8, min_value=0)
    with sc3:
        min_gap = st.number_input("Merge Gap (s)", value=6, min_value=0,
                                  help="Events inside this gap are merged into one clip.")

    st.markdown('<div class="cm-section"><i class="ph ph-folder-open"></i>Output</div>', unsafe_allow_html=True)
    if IS_MAC:
        out_dir_input = st.text_input("Output Folder", value=st.session_state.output_dir,
                                      placeholder="Paste full folder path")
        if out_dir_input and out_dir_input != st.session_state.output_dir:
            st.session_state.output_dir = out_dir_input
    else:
        oc1, oc2 = st.columns([4, 1])
        with oc1:
            out_dir_input = st.text_input("Output Folder", value=st.session_state.output_dir,
                                          placeholder="Click Browse to choose folder")
        with oc2:
            st.write("")
            st.write("")
            if st.button("Browse", key="browse_out"):
                picked = browse_folder()
                if picked:
                    st.session_state.output_dir = picked
                    st.rerun()

    individual = st.checkbox("Save individual clips instead of one combined reel")
    if not individual:
        out_filename = st.text_input("Output Filename", value="Highlights.mp4")
    else:
        out_filename = "Highlights.mp4"

    dry_run = st.checkbox("Dry Run (preview clips without rendering)")

with tabs[2]:
    left_col, right_col = st.columns([1, 1], gap="large")

    with left_col:
        st.markdown('<div class="cm-section first"><i class="ph ph-funnel"></i>Manual Action Filters</div>', unsafe_allow_html=True)
        st.caption("Leave blank to include everything.")

        final_csv_for_filter = st.session_state.csv_path or csv_path
        action_types = []
        has_xt = False
        has_prog = False
        _home_team = _away_team = ""
        _filter_df = None
        if final_csv_for_filter and os.path.exists(final_csv_for_filter):
            try:
                _filter_df = pd.read_csv(final_csv_for_filter)
                action_types = sorted(_filter_df["type"].dropna().unique().tolist()) if "type" in _filter_df.columns else []
                has_xt = "xT" in _filter_df.columns
                has_prog = any(c in _filter_df.columns for c in ["prog_pass", "prog_carry"])
                if "team" in _filter_df.columns:
                    teams = [t for t in _filter_df["team"].dropna().unique().tolist() if t]
                    if len(teams) >= 2:
                        _home_team, _away_team = teams[0], teams[1]
                    elif len(teams) == 1:
                        _home_team = teams[0]
            except Exception:
                pass

        if _filter_df is not None and "playerName" in _filter_df.columns:
            _all_players = sorted(_filter_df["playerName"].dropna().unique().tolist())
            if "team" in _filter_df.columns:
                _home_players = sorted(_filter_df[_filter_df["team"] == _home_team]["playerName"].dropna().unique()) if _home_team else _all_players
                _away_players = sorted(_filter_df[_filter_df["team"] == _away_team]["playerName"].dropna().unique()) if _away_team else _all_players
            else:
                _home_players = _away_players = _all_players
        else:
            _all_players = _home_players = _away_players = []

        team_filter = "All players"
        player_filter = "All players"
        if len(_all_players) == 1:
            st.caption(f"Player: **{_all_players[0]}**")
            player_filter = _all_players[0]
        elif _home_team and _away_team:
            team_filter = st.radio("Team", options=["Both teams", _home_team, _away_team], horizontal=True)
            if team_filter == _home_team:
                _pool = ["All players"] + _home_players
            elif team_filter == _away_team:
                _pool = ["All players"] + _away_players
            else:
                team_filter = "All players"
                _pool = ["All players"] + _all_players
            player_filter = st.selectbox("Player", options=_pool, index=0)
        elif _all_players:
            player_filter = st.selectbox("Player", options=["All players"] + _all_players, index=0)

        filter_types = st.multiselect(
            "Action Type",
            options=action_types,
            placeholder="All types" if action_types else "Load a CSV first",
        )

        PASS_TYPE_MAP = {
            "Key passes": ("key_passes_only", "is_key_pass"),
            "Crosses": ("crosses_only", "is_cross"),
            "Long balls": ("long_balls_only", "is_long_ball"),
            "Through balls": ("through_balls_only", "is_through_ball"),
            "Corners": ("corners_only", "is_corner"),
            "Freekicks": ("freekicks_only", "is_freekick"),
            "Headers": ("headers_only", "is_header"),
            "Big chances": ("big_chances_only", "is_big_chance"),
        }
        available_pass_types = [
            label for label, (_, col) in PASS_TYPE_MAP.items()
            if _filter_df is not None and col in _filter_df.columns and _filter_df[col].any()
        ]
        selected_pass_types = []
        key_passes_only = False
        progressive_only = False
        if available_pass_types:
            selected_pass_types = st.multiselect(
                "Pass / Action Subtype",
                options=available_pass_types,
                placeholder="All subtypes",
            )
            key_passes_only = "Key passes" in selected_pass_types

        if has_prog:
            progressive_only = st.checkbox("Progressive actions only")

        xt_min = 0.0
        top_n = 0
        if has_xt:
            with st.expander("xT Filters"):
                xt_min = st.number_input("Min xT value", min_value=0.0, value=0.0, step=0.001, format="%.3f")
                top_n = st.number_input("Top N by xT (0 = all)", min_value=0, value=0, step=1)

    with right_col:
        append_replays = bool(st.session_state.get("replay_map"))
        st.markdown('<div class="cm-section first"><i class="ph ph-robot"></i>ClipMaker AI</div>', unsafe_allow_html=True)

        _ai_csv = st.session_state.get("scraped_csv_path") or st.session_state.csv_path or csv_path
        if _ai_csv and os.path.exists(_ai_csv.strip().strip("\"'")):
            with st.expander("View Data Summary", expanded=False):
                try:
                    render_stats_panel(read_csv_safe(_ai_csv.strip().strip("\"'")))
                except Exception:
                    pass

        ai_input = st.text_area(
            "Ask about your data or describe the clips you want",
            placeholder='e.g. "Who had the most take ons?" or "Make a reel of Estevao\'s passes in the second half"',
            height=100,
            label_visibility="collapsed"
        )
        ask_btn = st.button("Ask About Data", use_container_width=True)
        make_clips_ai_btn = st.button("Make Clips with AI", type="primary", use_container_width=True)
        ai_answer_placeholder = st.empty()

    st.markdown('<div class="cm-section"><i class="ph ph-play-circle"></i>Run</div>', unsafe_allow_html=True)
    run_left, run_center, run_right = st.columns([1, 2, 1])
    with run_center:
        run_btn = st.button("Run ClipMaker", type="primary", use_container_width=True)

# Progress area
progress_placeholder = st.empty()
status_placeholder = st.empty()
log_placeholder = st.empty()

final_video = st.session_state.video_path or video_path
final_video2 = st.session_state.video2_path or video2_path
final_csv = st.session_state.csv_path or csv_path
final_out_dir = st.session_state.output_dir or out_dir_input or "output"

# =============================================================================
# HANDLE AI DATA QUESTION
# =============================================================================

if ask_btn:
    if not _ai_csv:
        ai_answer_placeholder.error("Load a CSV file first.")
    elif not ai_input.strip():
        ai_answer_placeholder.error("Please enter a question.")
    else:
        with ai_answer_placeholder.container():
            with st.spinner("Computing answer..."):
                try:
                    df_ai = read_csv_safe(_ai_csv.strip().strip("\'\""))
                    answer = answer_with_pandas(ai_input, df_ai)
                    st.markdown("**Answer:**")
                    if isinstance(answer, pd.DataFrame):
                        st.dataframe(answer, use_container_width=True, hide_index=True)
                        st.caption(f"{len(answer)} event{'s' if len(answer) != 1 else ''} · To clip these, describe them in the AI box and click **Make clips with AI**.")
                    elif isinstance(answer, pd.Series):
                        st.dataframe(answer.reset_index(), use_container_width=True, hide_index=True)
                        st.caption("To clip these events, describe them in the AI box and click **Make clips with AI**.")
                    else:
                        st.markdown(f'<div class="ai-box">{answer}</div>', unsafe_allow_html=True)
                        st.caption("To clip these events, describe them in the AI box and click **Make clips with AI**.")
                except Exception as e:
                    st.error(f"Error: {e}")

# =============================================================================
# HANDLE AI MAKE CLIPS
# =============================================================================

if make_clips_ai_btn:
    if not final_video:
        st.error("Video file is required.")
    elif not final_csv:
        st.error("CSV file is required.")
    elif not ai_input.strip():
        st.error("Please describe what clips you want.")
    else:
        df_ai = read_csv_safe(final_csv.strip().strip("\'\""))
        available_types = df_ai["type"].dropna().unique().tolist() if "type" in df_ai.columns else []
        with st.spinner("AI is interpreting your request..."):
            try:
                filters = parse_filters(ai_input, df_ai, available_types)
            except Exception as e:
                st.error(f"Could not parse request: {e}")
                st.stop()
        st.markdown("**AI interpreted your request as:**")
        st.markdown(f'<div class="ai-box">{filters.get("explanation", "No explanation.")}</div>',
                    unsafe_allow_html=True)
        with st.expander("See full filter config"):
            st.json({k: v for k, v in filters.items() if k != "explanation"})

        # Apply team/player filter by subsetting CSV
        team_filter_ai  = filters.get("team_filter", "").strip()
        player_filter_ai = filters.get("player_filter", "").strip()
        ai_data_file = final_csv.strip().strip("\'\"")
        df_filtered = df_ai.copy()

        if team_filter_ai and "team" in df_filtered.columns:
            df_team = df_filtered[df_filtered["team"].str.contains(team_filter_ai, case=False, na=False)]
            if len(df_team) == 0:
                st.warning(f"No events for team '{team_filter_ai}'. Running on all teams.")
            else:
                df_filtered = df_team
                st.info(f"Filtered to {len(df_filtered)} events for team '{team_filter_ai}'.")

        if player_filter_ai and "playerName" in df_filtered.columns:
            # Support multiple comma-separated player names
            player_names = [p.strip() for p in player_filter_ai.split(",") if p.strip()]
            if len(player_names) > 1:
                mask = df_filtered["playerName"].apply(
                    lambda x: any(n.lower() in str(x).lower() for n in player_names)
                )
            else:
                mask = df_filtered["playerName"].str.contains(player_filter_ai, case=False, na=False)
            df_player = df_filtered[mask]
            if len(df_player) == 0:
                st.warning(f"No events for '{player_filter_ai}'. Running on all players.")
            else:
                df_filtered = df_player
                st.info(f"Filtered to {len(df_filtered)} events for '{player_filter_ai}'.")

        if df_filtered is not df_ai:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
            df_filtered.to_csv(tmp.name, index=False)
            tmp.close()
            ai_data_file = tmp.name

        ai_config = {
            "video_file": final_video,
            "video2_file": final_video2,
            "split_video": split_video,
            "data_file": ai_data_file,
            "half1_time": half1 or "0:00",
            "half2_time": half2 or "45:00",
            "half3_time": half3 or "",
            "half4_time": half4 or "",
            "period_column": "" if use_fallback else period_col,
            "fallback_row": int(fallback_row) if use_fallback else None,
            "before_buffer": before_buf,
            "after_buffer": after_buf,
            "min_gap": min_gap,
            "output_dir": final_out_dir,
            "output_filename": out_filename if not individual else "Highlights.mp4",
            "individual_clips": individual,
            "dry_run": dry_run,
            "half_filter": filters.get("half_filter", half_filter),
            "filter_types": filters.get("filter_types", []),
            "progressive_only":   filters.get("progressive_only", False),
            "key_passes_only":    filters.get("key_passes_only", False),
            "crosses_only":       filters.get("crosses_only", False),
            "long_balls_only":    filters.get("long_balls_only", False),
            "through_balls_only": filters.get("through_balls_only", False),
            "corners_only":       filters.get("corners_only", False),
            "freekicks_only":     filters.get("freekicks_only", False),
            "headers_only":       filters.get("headers_only", False),
            "big_chances_only":   filters.get("big_chances_only", False),
            "xt_min": filters.get("xt_min", 0.0),
            "top_n": int(filters.get("top_n", 0)) or None,
            "successful_only": filters.get("successful_only", False),
            "unsuccessful_only": filters.get("unsuccessful_only", False),
            "minute_min": filters.get("minute_min", None),
            "minute_max": filters.get("minute_max", None),
            "unsuccessful_only": filters.get("unsuccessful_only", False),
        }

        ai_log_queue = queue.Queue()
        ai_progress_queue = queue.Queue()
        ai_log_lines = []
        ai_log_ph = st.empty()

        ai_thread = threading.Thread(
            target=run_clip_maker,
            args=(ai_config, ai_log_queue, ai_progress_queue),
            daemon=True
        )
        ai_thread.start()

        while ai_thread.is_alive() or not ai_log_queue.empty():
            while not ai_log_queue.empty():
                msg = ai_log_queue.get_nowait()
                if isinstance(msg, dict) and msg.get("type") == "log":
                    ai_log_lines.append(msg.get("msg", ""))
            ai_log_ph.markdown(
                f'<div class="log-box">{"<br>".join(ai_log_lines)}</div>',
                unsafe_allow_html=True
            )
            time.sleep(0.3)

        ai_thread.join()
        ai_log_ph.markdown(
            f'<div class="log-box">{"<br>".join(ai_log_lines)}</div>',
            unsafe_allow_html=True
        )
        if any("✓" in l for l in ai_log_lines):
            st.success("Done! Check your output folder.")

# Apply manual team/player filter — subset CSV to a temp file if needed
_team_data_file = final_csv
_needs_filter = (team_filter != "All players") or (player_filter != "All players")
if _needs_filter and final_csv and os.path.exists(final_csv.strip().strip("\"'")):
    try:
        _tdf = read_csv_safe(final_csv.strip().strip("\'\""))
        # Team filter
        if team_filter != "All players" and "team" in _tdf.columns:
            _team_name = _home_team if f"Players from {_home_team}" == team_filter else _away_team
            _tdf = _tdf[_tdf["team"] == _team_name]
        # Player filter (more specific — applied on top of team filter)
        if player_filter != "All players" and "playerName" in _tdf.columns:
            _tdf = _tdf[_tdf["playerName"] == player_filter]
        if len(_tdf) > 0:
            import tempfile
            _tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
            _tdf.to_csv(_tmp.name, index=False)
            _tmp.close()
            _team_data_file = _tmp.name
    except Exception:
        pass


if run_btn:
    errors = []
    if not final_video and not dry_run:
        errors.append("Video file is required.")
    if not final_csv:
        errors.append("CSV file is required.")
    if not half1:
        errors.append("1st half kick-off time is required.")
    if not half2:
        errors.append("2nd half kick-off time is required.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        config = {
            "video_file": final_video,
            "video2_file": (st.session_state.video2_path or video2_path).strip().strip("\"'"),
            "split_video": split_video,
            "data_file": _team_data_file,
            "half1_time": half1,
            "half2_time": half2,
            "half3_time": half3 or "",
            "half4_time": half4 or "",
            "period_column": "" if use_fallback else period_col,
            "fallback_row": int(fallback_row) if use_fallback else None,
            "before_buffer": before_buf,
            "after_buffer": after_buf,
            "min_gap": min_gap,
            "output_dir": final_out_dir,
            "output_filename": out_filename,
            "individual_clips": individual,
            "dry_run": dry_run,
            "half_filter": half_filter,
            "filter_types": filter_types,
            "progressive_only": progressive_only,
            "key_passes_only": key_passes_only,
            "crosses_only":       "Crosses"               in selected_pass_types,
            "long_balls_only":    "Long balls"            in selected_pass_types,
            "through_balls_only": "Through balls"         in selected_pass_types,
            "corners_only":       "Corners"               in selected_pass_types,
            "freekicks_only":     "Freekicks"             in selected_pass_types,
            "headers_only":       "Headers"               in selected_pass_types,
            "big_chances_only":   "Big chances"           in selected_pass_types,
            "xt_min": xt_min,
            "top_n": int(top_n) if top_n > 0 else None,
            "replay_map": st.session_state.get("replay_map", {}) if append_replays else {},
        }

        log_queue = queue.Queue()
        progress_queue = queue.Queue()
        log_lines = []
        last_progress = {"current": 0, "total": 1, "elapsed": 0}

        thread = threading.Thread(
            target=run_clip_maker, args=(config, log_queue, progress_queue), daemon=True
        )
        thread.start()

        while thread.is_alive() or not log_queue.empty():
            # Drain progress queue
            while not progress_queue.empty():
                last_progress = progress_queue.get_nowait()

            # Drain log queue
            updated = False
            while not log_queue.empty():
                msg = log_queue.get_nowait()
                if msg["type"] == "log":
                    log_lines.append(msg["msg"])
                    updated = True

            # Update progress bar
            cur = last_progress["current"]
            tot = last_progress["total"]
            elapsed = last_progress["elapsed"]
            frac = cur / tot if tot > 0 else 0

            phase = last_progress.get("phase", "clips")

            if cur > 0 and elapsed > 0:
                rate = cur / elapsed
                remaining = (tot - cur) / rate
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                eta_str = f"{mins}m {secs:02d}s remaining"
            else:
                eta_str = "Calculating..."

            if phase == "assembly":
                if frac >= 0.99:
                    label_str = "Finalising — merging audio and video, almost done..."
                else:
                    label_str = f"Assembling — frame {cur:,} of {tot:,} — {eta_str}"
            else:
                label_str = f"Clip {cur} of {tot} — {eta_str}"

            with progress_placeholder.container():
                st.markdown(
                    f'<div class="progress-label">{label_str}</div>',
                    unsafe_allow_html=True
                )
                st.progress(frac)

            if updated:
                log_placeholder.markdown(
                    f'<div class="log-box">{"<br>".join(log_lines)}</div>',
                    unsafe_allow_html=True
                )

            time.sleep(0.3)

        thread.join()

        # Final log flush
        while not log_queue.empty():
            msg = log_queue.get_nowait()
            if msg["type"] == "log":
                log_lines.append(msg["msg"])

        log_placeholder.markdown(
            f'<div class="log-box">{"<br>".join(log_lines)}</div>',
            unsafe_allow_html=True
        )
        progress_placeholder.empty()

# Footer
st.markdown('<div class="footer">@B03GHB4L1</div>', unsafe_allow_html=True)
