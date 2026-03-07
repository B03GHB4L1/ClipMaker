import sys
import os
import threading
import queue
import time
import platform
import pandas as pd
import streamlit as st
from moviepy import VideoFileClip, concatenate_videoclips

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="ClipMaker 1.1 by B4L1", page_icon="⚽", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 1rem; }
    .stTextInput > label, .stNumberInput > label, .stCheckbox > label { font-weight: 500; }
    .log-box {
        background: #0e1117; color: #00ff88; font-family: 'Courier New', monospace;
        font-size: 13px; padding: 16px; border-radius: 8px;
        height: 260px; overflow-y: auto; white-space: pre-wrap;
        border: 1px solid #2a2a2a;
    }
    h1 { font-size: 2rem !important; }
    .footer {
        text-align: center; color: #555; font-size: 11px;
        padding-top: 8px; padding-bottom: 4px;
    }
    .progress-label {
        font-size: 13px; color: #aaa; margin-bottom: 4px;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# FILE / FOLDER DIALOG HELPERS (tkinter)
# =============================================================================

def _pick_file_thread(result_queue, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        if platform.system() == "Windows":
            root.wm_attributes("-topmost", True)
        elif platform.system() == "Darwin":
            os.system("osascript -e 'tell application \"Python\" to activate'")
    except Exception:
        pass
    path = filedialog.askopenfilename(filetypes=filetypes)
    root.destroy()
    result_queue.put(path)

def _pick_folder_thread(result_queue):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        if platform.system() == "Windows":
            root.wm_attributes("-topmost", True)
        elif platform.system() == "Darwin":
            os.system("osascript -e 'tell application \"Python\" to activate'")
    except Exception:
        pass
    path = filedialog.askdirectory()
    root.destroy()
    result_queue.put(path)

def browse_file(filetypes):
    q = queue.Queue()
    t = threading.Thread(target=_pick_file_thread, args=(q, filetypes), daemon=True)
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""

def browse_folder():
    q = queue.Queue()
    t = threading.Thread(target=_pick_folder_thread, args=(q,), daemon=True)
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""

# =============================================================================
# CORE LOGIC
# =============================================================================

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "ExtraTimeFirstHalf": 3, "ExtraTimeSecondHalf": 4,
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
        if df["resolved_period"].isna().any():
            bad = df[df["resolved_period"].isna()][period_column].unique()
            raise ValueError(f"Unrecognised period values: {bad}")
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
    if not windows:
        return []
    merged = [list(windows[0])]
    for start, end, label in windows[1:]:
        prev = merged[-1]
        if start <= prev[1] + min_gap:
            prev[1] = max(prev[1], end)
            prev[2] = prev[2] + " + " + label
        else:
            merged.append([start, end, label])
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


    # xT filter
    if config.get("xt_min") is not None and "xT" in df.columns:
        xt_min = config["xt_min"]
        if xt_min > 0:
            df = df[pd.to_numeric(df["xT"], errors="coerce").fillna(0) >= xt_min]

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

        period_start = {
            1: to_seconds(config["half1_time"]),
            2: to_seconds(config["half2_time"]),
        }
        if config["half3_time"].strip():
            period_start[3] = to_seconds(config["half3_time"])
        if config["half4_time"].strip():
            period_start[4] = to_seconds(config["half4_time"])

        period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}
        fallback = config["fallback_row"]
        period_col = config["period_column"] or None
        df = assign_periods(df, period_col, fallback)

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
            label = f"{row['type']} @ {int(row['minute'])}:{int(row['second']):02d} (P{int(row['resolved_period'])})"
            raw_windows.append((ts - config["before_buffer"], ts + config["after_buffer"], label))

        windows = merge_overlapping_windows(raw_windows, config["min_gap"])
        log(f"Found {len(df)} events → {len(windows)} clips after merging.\n")

        if config["dry_run"]:
            for i, (s, e, lbl) in enumerate(windows, 1):
                log(f"  Clip {i:02d}: {s:.1f}s – {e:.1f}s  ({e-s:.0f}s)  |  {lbl}")
            log("\n✓ DRY RUN complete.")
            log_queue.put({"type": "done"})
            return

        log("Loading video...")
        video_path = config["video_file"].strip().strip('"\'')
        video = VideoFileClip(video_path)
        out_dir = config["output_dir"]
        os.makedirs(out_dir, exist_ok=True)

        total_clips = len(windows)
        start_time = time.time()

        if config["individual_clips"]:
            saved = []
            for i, (start, end, label) in enumerate(windows, 1):
                start = max(0, start)
                end = min(video.duration, end)
                if end <= start:
                    continue
                actions = [p.split(" @")[0].strip() for p in label.split(" + ")]
                dominant = max(set(actions), key=actions.count).replace(" ", "_")
                filename = f"{i:02d}_{dominant}.mp4"
                filepath = os.path.join(out_dir, filename)
                log(f"  Rendering {i:02d}/{total_clips}: {filename}")
                clip = video.subclipped(start, end)
                clip.write_videofile(filepath, codec="libx264", preset="ultrafast", logger=None)
                saved.append(filepath)
                prog(i, total_clips, time.time() - start_time)
            video.close()
            log(f"\n✓ {len(saved)} clips saved to: {os.path.abspath(out_dir)}/")
        else:
            clips = []
            for i, (start, end, label) in enumerate(windows, 1):
                start = max(0, start)
                end = min(video.duration, end)
                if end <= start:
                    continue
                clips.append(video.subclipped(start, end))
                prog(i, total_clips, time.time() - start_time)

            total_dur = sum(c.duration for c in clips)
            log(f"Assembling {len(clips)} clips ({total_dur:.1f}s)...")
            out_path = os.path.join(out_dir, config["output_filename"])
            final = concatenate_videoclips(clips)
            # Calculate total frames for progress tracking
            fps = final.fps or 25
            total_frames = int(total_dur * fps)
            assembly_start = time.time()
            stop_event = threading.Event()
            monitor_thread = threading.Thread(
                target=monitor_file_progress,
                args=(out_path, total_frames, fps, progress_queue, stop_event),
                daemon=True
            )
            monitor_thread.start()
            final.write_videofile(out_path, codec="libx264", preset="ultrafast", logger=None)
            stop_event.set()
            monitor_thread.join()
            video.close()
            log(f"\n✓ Saved to: {out_path}")

        log_queue.put({"type": "done"})

    except Exception as e:
        log(f"\n✗ ERROR: {e}")
        log_queue.put({"type": "error"})

# =============================================================================
# SESSION STATE
# =============================================================================
for key, default in [
    ("video_path", ""), ("video2_path", ""), ("csv_path", ""), ("output_dir", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# =============================================================================
# UI
# =============================================================================

st.title("⚽ ClipMaker 1.1 by B4L1")
st.caption("Football highlight reel generator from match event data")
st.divider()

col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("Files")

    split_video = st.checkbox("Match is split into two separate video files (1st/2nd half)")

    vc1, vc2 = st.columns([4, 1])
    with vc1:
        lbl1 = "1st Half Video File" if split_video else "Video File"
        video_path = st.text_input(lbl1, value=st.session_state.video_path,
                                    placeholder="Click Browse or paste full path")
    with vc2:
        st.write(""); st.write("")
        if st.button("Browse", key="browse_video"):
            picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
            if picked:
                st.session_state.video_path = picked
                st.rerun()

    if split_video:
        v2c1, v2c2 = st.columns([4, 1])
        with v2c1:
            video2_path = st.text_input("2nd Half Video File", value=st.session_state.video2_path,
                                        placeholder="Click Browse or paste full path")
        with v2c2:
            st.write(""); st.write("")
            if st.button("Browse", key="browse_video2"):
                picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
                if picked:
                    st.session_state.video2_path = picked
                    st.rerun()
    else:
        video2_path = ""

    cc1, cc2 = st.columns([4, 1])
    with cc1:
        csv_path = st.text_input("CSV File", value=st.session_state.csv_path,
                                  placeholder="Click Browse or paste full path")
    with cc2:
        st.write(""); st.write("")
        if st.button("Browse", key="browse_csv"):
            picked = browse_file([("CSV files", "*.csv"), ("All files", "*.*")])
            if picked:
                st.session_state.csv_path = picked
                st.rerun()

    st.subheader("Kick-off Timestamps")
    if split_video:
        st.caption("Enter timestamps relative to the START of each video file")
    else:
        st.caption("Type exactly what your video player shows — MM:SS or HH:MM:SS")
    tc1, tc2 = st.columns(2)
    with tc1:
        half1 = st.text_input("1st Half kick-off", placeholder="e.g. 4:16")
        half3 = st.text_input("ET 1st Half (optional)", placeholder="leave blank")
    with tc2:
        half2 = st.text_input("2nd Half kick-off", placeholder="e.g. 0:45" if split_video else "e.g. 1:00:32")
        half4 = st.text_input("ET 2nd Half (optional)", placeholder="leave blank")

    st.subheader("Action Filters")
    st.caption("Leave all blank to include every action in the CSV")

    # Load CSV column options if file selected
    final_csv_for_filter = st.session_state.csv_path or csv_path
    action_types = []
    has_xt = False
    has_prog = False
    if final_csv_for_filter and os.path.exists(final_csv_for_filter):
        try:
            _df = pd.read_csv(final_csv_for_filter)
            action_types = sorted(_df["type"].dropna().unique().tolist()) if "type" in _df.columns else []
            has_xt = "xT" in _df.columns
            has_prog = any(c in _df.columns for c in ["prog_pass", "prog_carry"])
        except Exception:
            pass

    filter_types = st.multiselect(
        "Action Types to Include",
        options=action_types,
        placeholder="All types included if left blank" if action_types else "Load a CSV first",
        help="Select which action types to clip. Leave empty to include all."
    )

    fc1, fc2 = st.columns(2)
    with fc1:
        progressive_only = st.checkbox(
            "Progressive actions only",
            disabled=not has_prog,
            help="Only include actions where prog_pass or prog_carry > 0"
        )
    with fc2:
        xt_min = st.number_input(
            "Min xT value",
            min_value=0.0, value=0.0, step=0.001, format="%.3f",
            disabled=not has_xt,
            help="Only include actions with xT at or above this value. Set to 0 to include all."
        )

    top_n = st.number_input(
        "Top N actions by xT (0 = include all)",
        min_value=0, value=0, step=1,
        disabled=not has_xt,
        help="Rank all actions by xT and clip only the top N. Set to 0 to include all."
    )


with col2:
    st.subheader("Half Detection")
    period_col = st.text_input("Period Column Name", value="period",
                                help="The CSV column that says FirstHalf/SecondHalf or 1/2. Leave blank if none.")
    fallback_row = st.number_input("Fallback Row Index", min_value=0, value=0, step=1,
                                    help="Row index where 2nd half begins. Only used if period column is blank.")
    use_fallback = st.checkbox("Use fallback row index instead of period column")

    st.subheader("Clip Settings")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        before_buf = st.number_input("Before (s)", value=3, min_value=0)
    with sc2:
        after_buf = st.number_input("After (s)", value=8, min_value=0)
    with sc3:
        min_gap = st.number_input("Merge Gap (s)", value=6, min_value=0,
                                   help="Events within this many seconds of each other are merged into one clip. A sequence of passes in the same move becomes one clip rather than many. Increase to merge more aggressively, decrease to keep events separate.")

    st.subheader("Output")
    oc1, oc2 = st.columns([4, 1])
    with oc1:
        out_dir_input = st.text_input("Output Folder", value=st.session_state.output_dir,
                                       placeholder="Click Browse to choose folder")
    with oc2:
        st.write(""); st.write("")
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

st.divider()

run_col, _ = st.columns([1, 3])
with run_col:
    run_btn = st.button("▶  Run ClipMaker", type="primary", use_container_width=True)

# Progress area
progress_placeholder = st.empty()
status_placeholder = st.empty()
log_placeholder = st.empty()

final_video = st.session_state.video_path or video_path
final_video2 = st.session_state.video2_path or video2_path
final_csv = st.session_state.csv_path or csv_path
final_out_dir = st.session_state.output_dir or out_dir_input or "output"

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
            "data_file": final_csv,
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
            "filter_types": filter_types,
            "progressive_only": progressive_only,
            "xt_min": xt_min,
            "top_n": int(top_n) if top_n > 0 else None,
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
