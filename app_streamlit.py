import sys
import os
import tempfile
import threading
import queue
import pandas as pd
import streamlit as st
from moviepy import VideoFileClip, concatenate_videoclips

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="Clip Maker", page_icon="⚽", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    .stTextInput > label, .stNumberInput > label, .stCheckbox > label { font-weight: 500; }
    .log-box {
        background: #0e1117; color: #00ff88; font-family: 'Courier New', monospace;
        font-size: 13px; padding: 16px; border-radius: 8px;
        height: 320px; overflow-y: auto; white-space: pre-wrap;
        border: 1px solid #2a2a2a;
    }
    h1 { font-size: 2rem !important; }
    .browse-note { font-size: 12px; color: #888; margin-top: -12px; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# TKINTER FILE/FOLDER DIALOG HELPERS
# Run in a separate thread to avoid blocking Streamlit
# =============================================================================

def _pick_file_thread(result_queue, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askopenfilename(filetypes=filetypes)
    root.destroy()
    result_queue.put(path)

def _pick_folder_thread(result_queue):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askdirectory()
    root.destroy()
    result_queue.put(path)

def browse_file(filetypes):
    """Opens a Windows file picker and returns the selected path."""
    q = queue.Queue()
    t = threading.Thread(target=_pick_file_thread, args=(q, filetypes), daemon=True)
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""

def browse_folder():
    """Opens a Windows folder picker and returns the selected path."""
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

def run_clip_maker(config, log_queue):
    def log(msg):
        log_queue.put(msg)

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
            log_queue.put("__DONE__")
            return

        log(f"Loading video...")
        video_path = config["video_file"].strip().strip('"\'')
        video = VideoFileClip(video_path)
        out_dir = config["output_dir"]
        os.makedirs(out_dir, exist_ok=True)

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
                log(f"  Rendering {i:02d}/{len(windows)}: {filename}")
                clip = video.subclipped(start, end)
                clip.write_videofile(filepath, codec="libx264", preset="ultrafast", logger=None)
                saved.append(filepath)
            video.close()
            log(f"\n✓ {len(saved)} clips saved to: {os.path.abspath(out_dir)}/")
        else:
            clips = []
            for start, end, label in windows:
                start = max(0, start)
                end = min(video.duration, end)
                if end <= start:
                    continue
                clips.append(video.subclipped(start, end))
            total = sum(c.duration for c in clips)
            log(f"Assembling {len(clips)} clips ({total:.1f}s)...")
            out_path = os.path.join(out_dir, config["output_filename"])
            final = concatenate_videoclips(clips)
            final.write_videofile(out_path, codec="libx264", preset="ultrafast")
            video.close()
            log(f"\n✓ Saved to: {out_path}")

        log_queue.put("__DONE__")

    except Exception as e:
        log(f"\n✗ ERROR: {e}")
        log_queue.put("__ERROR__")

# =============================================================================
# SESSION STATE — stores Browse selections across reruns
# =============================================================================
for key, default in [
    ("video_path", ""),
    ("csv_path", ""),
    ("output_dir", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# =============================================================================
# UI
# =============================================================================

st.title("⚽ Clip Maker")
st.caption("Football highlight reel generator from match event data")
st.divider()

col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("Files")

    # Video file browse
    vc1, vc2 = st.columns([4, 1])
    with vc1:
        video_path = st.text_input("Video File", value=st.session_state.video_path,
                                    placeholder="Click Browse or paste full path")
    with vc2:
        st.write("")
        st.write("")
        if st.button("Browse", key="browse_video"):
            picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
            if picked:
                st.session_state.video_path = picked
                st.rerun()

    # CSV file browse
    cc1, cc2 = st.columns([4, 1])
    with cc1:
        csv_path = st.text_input("CSV File", value=st.session_state.csv_path,
                                  placeholder="Click Browse or paste full path")
    with cc2:
        st.write("")
        st.write("")
        if st.button("Browse", key="browse_csv"):
            picked = browse_file([("CSV files", "*.csv"), ("All files", "*.*")])
            if picked:
                st.session_state.csv_path = picked
                st.rerun()

    st.subheader("Kick-off Timestamps")
    st.caption("Type exactly what your video player shows — MM:SS or HH:MM:SS")
    tc1, tc2 = st.columns(2)
    with tc1:
        half1 = st.text_input("1st Half", placeholder="e.g. 4:16")
        half3 = st.text_input("ET 1st Half (optional)", placeholder="leave blank")
    with tc2:
        half2 = st.text_input("2nd Half", placeholder="e.g. 1:00:32")
        half4 = st.text_input("ET 2nd Half (optional)", placeholder="leave blank")

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
        min_gap = st.number_input("Merge Gap (s)", value=6, min_value=0, help="Events within this many seconds of each other are merged into one clip. A sequence of passes in the same move becomes one clip rather than many. Increase to merge more aggressively, decrease to keep events separate.")

    st.subheader("Output")

    # Output folder browse
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

st.divider()

run_col, _ = st.columns([1, 3])
with run_col:
    run_btn = st.button("▶  Run Clip Maker", type="primary", use_container_width=True)

log_placeholder = st.empty()

# Resolve final paths from session state or typed input
final_video = st.session_state.video_path or video_path
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
        }

        log_queue = queue.Queue()
        log_lines = []

        with st.spinner("Running..."):
            thread = threading.Thread(target=run_clip_maker, args=(config, log_queue), daemon=True)
            thread.start()

            while True:
                try:
                    msg = log_queue.get(timeout=0.5)
                    if msg in ("__DONE__", "__ERROR__"):
                        break
                    log_lines.append(msg)
                    log_placeholder.markdown(
                        f'<div class="log-box">{"<br>".join(log_lines)}</div>',
                        unsafe_allow_html=True
                    )
                except queue.Empty:
                    if not thread.is_alive():
                        break

        thread.join()
        log_placeholder.markdown(
            f'<div class="log-box">{"<br>".join(log_lines)}</div>',
            unsafe_allow_html=True
        )
