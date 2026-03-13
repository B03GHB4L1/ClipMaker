# ---------------------------------------------------------------------------
# pages/2_Replay_Detector.py — STREAMLIT UI PAGE for replay detection.
#
# This is the USER-FACING PAGE. It renders the Streamlit interface (file
# pickers, settings sliders, log panel) and calls the detection engine in
# replay_detector.py (parent directory) to do the actual video analysis.
# ---------------------------------------------------------------------------
import os
import sys
import time
import queue
import threading
import platform
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Locate replay_detector.py in the parent ClipMaker/ directory so this page
# can import the 6-feature ensemble without duplicating code.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

IS_MAC = platform.system() == "Darwin"

# =============================================================================
# DEPENDENCY CHECK
# =============================================================================
_missing = []
try:
    import cv2
    import numpy as np
except ImportError:
    _missing.append("opencv-python")

def _open(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Unable to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frame_count / fps if fps > 0 else 0
    return cap, float(fps), float(duration)

def _grab(cap, t_sec, fps):
    t_sec = max(0.0, float(t_sec))
    cap.set(cv2.CAP_PROP_POS_MSEC, t_sec * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        return None, None

    h, w = frame.shape[:2]
    if w > 480:
        scale = 480.0 / w
        frame = cv2.resize(frame, (480, int(h * scale)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return gray, frame

def _frame_dup_ratio(cap, fps, center_t, win=2.0, pairs=8):
    start = max(0.0, float(center_t) - win / 2.0)
    end = start + win
    ts = np.linspace(start, end, num=max(3, pairs + 1))

    diffs = []
    prev = None
    for t in ts:
        gray, _ = _grab(cap, t, fps)
        if gray is None:
            continue
        if prev is not None:
            d = float(np.mean(np.abs(prev.astype(np.float32) - gray.astype(np.float32))))
            diffs.append(d)
        prev = gray

    if not diffs:
        return 0.0

    base_t = max(0.0, float(center_t) - 30.0)
    b1, _ = _grab(cap, base_t, fps)
    b2, _ = _grab(cap, base_t + 0.1, fps)
    if b1 is not None and b2 is not None:
        baseline = float(np.mean(np.abs(b1.astype(np.float32) - b2.astype(np.float32))))
    else:
        baseline = 8.0

    if baseline <= 0:
        return 0.0

    dup_count = sum(1 for d in diffs if d < baseline * 0.6)
    return dup_count / len(diffs)

def _hist_cuts(cap, fps, start_sec, end_sec, thr=27.0):
    cuts = []
    prev_hist = None
    t = max(0.0, float(start_sec))
    end_sec = float(end_sec)

    while t <= end_sec:
        gray, _ = _grab(cap, t, fps)
        if gray is None:
            t += 0.2
            continue

        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        cv2.normalize(hist, hist)

        if prev_hist is not None:
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            cut_score = (1.0 - corr) * 100.0
            if cut_score >= float(thr):
                cuts.append(t)

        prev_hist = hist
        t += 0.2

    return cuts

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="Replay Detector by B4L1", page_icon="ClipMaker_logo.png", layout="wide")

st.markdown("""
<style>
@import url('https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css');

.block-container {
    padding-top: 0 !important;
    padding-bottom: 2rem !important;
    max-width: 1200px !important;
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
# FILE / FOLDER DIALOG HELPERS (Windows only — Mac uses st.file_uploader)
# =============================================================================

def _pick_file_thread(result_queue, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
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
    root = tk.Tk()
    root.withdraw()
    try:
        root.wm_attributes("-topmost", True)
    except Exception:
        pass
    path = filedialog.askdirectory()
    root.destroy()
    result_queue.put(path)

def browse_file(filetypes):
    if IS_MAC:
        return ""
    q = queue.Queue()
    t = threading.Thread(target=_pick_file_thread, args=(q, filetypes), daemon=True)
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""

def browse_folder():
    if IS_MAC:
        return ""
    q = queue.Queue()
    t = threading.Thread(target=_pick_folder_thread, args=(q,), daemon=True)
    t.start()
    t.join(timeout=60)
    try:
        return q.get_nowait()
    except queue.Empty:
        return ""

def _save_uploaded_file(uploaded_file):
    """Save a Streamlit uploaded file to a temp path and return the path."""
    import tempfile
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.read())
        return tmp.name

# =============================================================================
# SHARED LOGIC (mirrors ClipMaker exactly)
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
        raise ValueError(f"Period {period} not in period_start.")
    offset_min, offset_sec = period_offset[period]
    elapsed = (minute * 60 + second) - (offset_min * 60 + offset_sec)
    if elapsed < 0:
        raise ValueError(f"Negative elapsed at {minute}:{second:02d} P{period}.")
    return period_start[period] + elapsed

def video_sec_to_clock(video_sec, period, period_start, period_offset):
    """Convert a raw video timestamp (seconds) back to match clock MM:SS + period label."""
    offset_min, offset_sec = period_offset.get(period, (0, 0))
    offset_secs = offset_min * 60 + offset_sec
    elapsed = video_sec - period_start.get(period, 0)
    match_sec = max(0.0, offset_secs + elapsed)
    mins = int(match_sec // 60)
    secs = int(match_sec % 60)
    return f"{mins}:{secs:02d} (P{period})"

# =============================================================================
# 6-FEATURE ENSEMBLE DETECTION ENGINE
# Powered by replay_detector.py (parent directory).
# Imported: _open, _score, _is_replay, _hist_cuts
# =============================================================================

def find_replay_for_event(cap, fps, dur, event_ts, search_after, search_window,
                           scene_threshold, flow_threshold, min_replay_duration,
                           sample_interval, log, max_event_seconds=12.0):
    """
    Two-pass replay finder. *cap* is owned by the caller — it is NOT opened or
    closed here, so the caller can reuse it across all events without the
    overhead of reopening a large video file each time.

    Pass 1 — fast pixel-diff scan at 2.0s steps:
        Two frames 0.1 s apart per step. Cheap: 2 seeks/step.

    Pass 2 — _frame_dup_ratio confirmation on candidate clusters:
        Called ONCE per cluster to confirm it is a replay.

    Boundary walks use the same cheap 2-frame diff, NOT _frame_dup_ratio.
    _frame_dup_ratio seeks 30 s away every call for its own baseline, which
    multiplied across 40 boundary steps per event caused 80-minute runtimes.
    The baseline computed in Pass 1 is reused for all boundary decisions.

    Returns (replay_start, replay_end, confidence) or None.
    """
    SCAN_STEP   = max(1.0, float(sample_interval) * 2.5)   # Pass-1 step (s)
    DUP_THR     = 0.35  # Minimum dup ratio for cluster confirmation
    DUP_STEP    = max(0.4, float(sample_interval))   # Boundary walk resolution (s)
    CLUSTER_GAP = SCAN_STEP * 2
    event_start_time = time.time()

    frame_cache = {}
    def _grab_cached(t_probe):
        key = round(float(t_probe), 2)
        if key in frame_cache:
            return frame_cache[key]
        frame_cache[key] = _grab(cap, t_probe, fps)
        if len(frame_cache) > 450:
            frame_cache.pop(next(iter(frame_cache)))
        return frame_cache[key]

    def _timed_out():
        return (time.time() - event_start_time) >= max_event_seconds

    # flow_threshold (0.5–5.0) → fraction of baseline diff allowed (0.60→0.20).
    sensitivity = 0.60 - (min(5.0, max(0.5, flow_threshold)) - 0.5) / 4.5 * 0.40

    window_start = event_ts + search_after
    window_end   = event_ts + search_after + search_window

    # ── Adaptive baseline: 2 grabs only ─────────────────────────────────
    base_t = window_end + 5.0 if event_ts < 35.0 else max(1.0, event_ts - 30.0)
    ga, _ = _grab_cached(base_t)
    gb, _ = _grab_cached(base_t + 0.1)
    if ga is not None and gb is not None:
        base_diff = float(np.mean(np.abs(ga.astype(np.float32) - gb.astype(np.float32))))
    else:
        base_diff = 8.0
    diff_thr = max(1.5, base_diff * sensitivity)
    log(f"[ANALYZE] Pass 1 baseline={base_diff:.2f}, slow-mo cutoff={diff_thr:.2f}, sensitivity={sensitivity:.2f}")

    # ── Pass 1: coarse pixel-diff scan ──────────────────────────────────
    candidates = []
    t = window_start
    while t < min(window_end, dur):
        if _timed_out():
            log("[ANALYZE] Event time budget reached; skipping this event for speed.")
            return None
        g1, _ = _grab_cached(t)
        g2, _ = _grab_cached(t + 0.1)
        if g1 is not None and g2 is not None:
            d = float(np.mean(np.abs(g1.astype(np.float32) - g2.astype(np.float32))))
            if d < diff_thr:
                candidates.append(t)
        t += SCAN_STEP

    if not candidates:
        log("[ANALYZE] Pass 1 found no slow-motion candidates.")
        return None
    log(f"[ANALYZE] Pass 1 found {len(candidates)} slow-motion candidate(s).")

    # ── Cluster consecutive candidates ───────────────────────────────────
    clusters = []
    cur = [candidates[0]]
    for c in candidates[1:]:
        if c - cur[-1] <= CLUSTER_GAP:
            cur.append(c)
        else:
            clusters.append(cur)
            cur = [c]
    clusters.append(cur)
    clusters = clusters[:3]

    # ── Pass 2: confirm each cluster with _frame_dup_ratio (once per cluster)
    replay_start = None
    replay_end   = None
    best_conf    = 0.0

    for cluster in clusters:
        if _timed_out():
            log("[ANALYZE] Event time budget reached during verification.")
            return None
        probe = cluster[len(cluster) // 2]
        dup = _frame_dup_ratio(cap, fps, probe, win=2.0, pairs=8)
        if dup < DUP_THR:
            log(f"[ANALYZE] Cluster at ~{probe:.1f}s dup={dup:.2f}: not a replay.")
            continue

        log(f"[ANALYZE] Cluster at ~{probe:.1f}s dup={dup:.2f}: replay confirmed.")

        # Cheap per-step check reusing the already-computed diff_thr.
        # 2 seeks/step vs 8-10 seeks/step for _frame_dup_ratio.
        def _slow_at(t_probe):
            f1, _ = _grab_cached(t_probe)
            f2, _ = _grab_cached(t_probe + 0.1)
            if f1 is None or f2 is None:
                return False
            d = float(np.mean(np.abs(f1.astype(np.float32) - f2.astype(np.float32))))
            return d < diff_thr  # True = slow-mo = still in replay

        # Walk backward to tighten replay start
        r_start = cluster[0]
        back = r_start - DUP_STEP
        while back >= max(window_start, r_start - 8.0):
            if _timed_out():
                break
            if _slow_at(back):
                r_start = back
                back -= DUP_STEP
            else:
                break

        # Walk forward — require 3 CONSECUTIVE normal-speed steps before closing
        r_end = cluster[-1] + DUP_STEP
        limit = min(window_end, dur)
        consec_live = 0
        live_start  = None
        while r_end < limit:
            if _timed_out():
                break
            if _slow_at(r_end):       # still slow-mo → still in replay
                consec_live = 0
                live_start  = None
            else:                      # normal speed → possible end
                if consec_live == 0:
                    live_start = r_end
                consec_live += 1
                if consec_live >= 3:   # 3 consecutive live frames → end confirmed
                    r_end = live_start
                    break
            r_end += DUP_STEP

        min_dur = min_replay_duration
        duration = r_end - r_start
        if duration < min_dur:
            log(f"[ANALYZE] Replay too short ({duration:.1f}s < {min_dur:.1f}s) \u2014 skipped.")
            continue

        conf = round(min(1.0, dup / 0.55), 3)
        if conf > best_conf:
            best_conf    = conf
            replay_start = r_start
            replay_end   = r_end
        break  # first confirmed cluster wins

    if replay_start is None:
        return None

    # Snap start to nearest scene cut (histogram diff only, no Farneback)
    snap_cuts = _hist_cuts(cap, fps,
                            max(0.0, replay_start - 2.0),
                            replay_start + 2.0,
                            thr=scene_threshold)
    if snap_cuts:
        near = min(snap_cuts, key=lambda c: abs(c - replay_start))
        if abs(near - replay_start) < 2.0:
            replay_start = near

    return (replay_start, replay_end, best_conf)


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
    raise ValueError("FFmpeg not found. Please ensure FFmpeg is installed and added to PATH.")


def run_detector(config, log_queue, progress_queue):
    def log(msg):
        log_queue.put({"type": "log", "msg": msg})

    cap1 = cap2 = cap3 = None

    try:
        # --- Load and resolve CSV ---
        df = pd.read_csv(config["data_file"])
        for col in ["minute", "second", "type"]:
            if col not in df.columns:
                raise ValueError(f"CSV missing required column: '{col}'")

        period_col = config["period_column"] or None
        fallback = config["fallback_row"]
        df = assign_periods(df, period_col, fallback)

        # --- Build period_start and period_offset (mirrors ClipMaker) ---
        period_start = {
            1: to_seconds(config["half1_time"]),
            2: to_seconds(config["half2_time"]),
        }
        if config.get("half3_time", "").strip():
            period_start[3] = to_seconds(config["half3_time"])
        if config.get("half4_time", "").strip():
            period_start[4] = to_seconds(config["half4_time"])

        period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0)}

        # --- Resolve video timestamps for each event ---
        timestamps = []
        for _, row in df.iterrows():
            try:
                ts = match_clock_to_video_time(
                    int(row["minute"]), int(row["second"]),
                    int(row["resolved_period"]), period_start, period_offset
                )
                timestamps.append(ts)
            except ValueError as e:
                log(f"[WARN] {e}")
                timestamps.append(None)

        df["video_timestamp"] = timestamps
        df = df.dropna(subset=["video_timestamp"]).sort_values("video_timestamp").reset_index(drop=True)
        log(f"[INFO] Loaded {len(df)} events from CSV.")

        # Open video capture(s) ONCE — reused across all events
        video_path1 = config["video_file"].strip().strip("\"'")
        split_video = bool(config.get("split_video") and config.get("video2_file", "").strip())
        try:
            cap1, fps1, dur1 = _open(video_path1)
        except Exception as e:
            log(f"[ERROR] Cannot open video: {e}")
            log_queue.put({"type": "error"})
            return
        log(f"[INFO] Opened video 1: {os.path.basename(video_path1)} ({dur1:.0f}s)")

        video_path2 = fps2 = dur2 = None
        video_path3 = fps3 = dur3 = None
        if split_video:
            video_path2 = config["video2_file"].strip().strip("\"'")
            try:
                cap2, fps2, dur2 = _open(video_path2)
            except Exception as e:
                log(f"[ERROR] Cannot open video 2: {e}")
                log_queue.put({"type": "error"})
                return
            log(f"[INFO] Opened video 2: {os.path.basename(video_path2)} ({dur2:.0f}s)")

            # Optional third file for extra-time periods.
            if config.get("video3_file", "").strip():
                video_path3 = config["video3_file"].strip().strip("\"'")
                try:
                    cap3, fps3, dur3 = _open(video_path3)
                except Exception as e:
                    log(f"[ERROR] Cannot open video 3: {e}")
                    log_queue.put({"type": "error"})
                    return
                log(f"[INFO] Opened video 3: {os.path.basename(video_path3)} ({dur3:.0f}s)")

        results = []
        total = len(df)
        start_time = time.time()

        for i, (_, row) in enumerate(df.iterrows(), 1):
            event_ts = row["video_timestamp"]
            minute = int(row["minute"])
            second = int(row["second"])
            event_type = row["type"]
            period = int(row["resolved_period"])

            log(f"[EVENT {i}/{total}] {event_type} @ {minute}:{second:02d} P{period} (video {event_ts:.1f}s)")

            # Route to correct capture in split-video mode
            if split_video and period >= 3 and cap3 is not None:
                cap_ev, fps_ev, dur_ev, vpath_ev = cap3, fps3, dur3, video_path3
            elif split_video and period >= 2 and cap2 is not None:
                cap_ev, fps_ev, dur_ev, vpath_ev = cap2, fps2, dur2, video_path2
            else:
                cap_ev, fps_ev, dur_ev, vpath_ev = cap1, fps1, dur1, video_path1

            replay = find_replay_for_event(
                cap=cap_ev, fps=fps_ev, dur=dur_ev,
                event_ts=event_ts,
                search_after=config["search_after"],
                search_window=config["search_window"],
                scene_threshold=config["scene_threshold"],
                flow_threshold=config["flow_threshold"],
                min_replay_duration=config["min_replay_duration"],
                sample_interval=config["sample_interval"],
                max_event_seconds=float(config.get("max_event_seconds", 12.0)),
                log=log,
            )

            if replay:
                r_start, r_end, confidence = replay
                r_clock_start = video_sec_to_clock(r_start, period, period_start, period_offset)
                r_clock_end   = video_sec_to_clock(r_end,   period, period_start, period_offset)
                log(f"[MATCH] Replay found: {r_clock_start} to {r_clock_end} (confidence {confidence:.2f})")
                results.append({
                    "event_minute": minute,
                    "event_second": second,
                    "event_type": event_type,
                    "event_period": period,
                    "event_video_ts": round(event_ts, 2),
                    "replay_start": round(r_start, 2),
                    "replay_end": round(r_end, 2),
                    "replay_clock_start": r_clock_start,
                    "replay_clock_end": r_clock_end,
                    "replay_duration": round(r_end - r_start, 2),
                    "confidence": confidence,
                    "video_file_used": vpath_ev,
                })
            else:
                log("[MATCH] No replay detected.")

            elapsed = time.time() - start_time
            progress_queue.put({"current": i, "total": total, "elapsed": elapsed})

        if not results:
            log(f"[RESULT] No replays detected across {total} events.")
            log("[HINT] Try lowering sensitivity or increasing the search window.")
            log_queue.put({"type": "done", "results": []})
            return

        if config.get("dry_run"):
            log(f"[RESULT] Dry run complete. Detected {len(results)} replay(s); no clips rendered.")
            log_queue.put({"type": "done", "results": results})
            return

        # --- Render replay clips via ffmpeg ---
        log(f"[RESULT] Found {len(results)} replay(s) across {total} events. Rendering clips...")
        out_dir = config["output_dir"]
        os.makedirs(out_dir, exist_ok=True)
        try:
            ffmpeg_bin = get_ffmpeg_binary()
        except ValueError as e:
            log(f"[ERROR] {e}")
            log_queue.put({"type": "error"})
            return
        import subprocess
        rendered = []
        for r in results:
            clip_name = (
                f"replay_{r['event_type'].replace(' ','_')}"
                f"_{r['event_minute']}m{r['event_second']:02d}s.mp4"
            )
            clip_path = os.path.join(out_dir, clip_name)
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", str(r["replay_start"]),
                "-to", str(r["replay_end"]),
                "-i", r.get("video_file_used", config["video_file"]),
                "-c", "copy",
                clip_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                r["clip_path"] = clip_path
                rendered.append(r)
                log(f"[RENDER] Saved clip: {clip_name}")
            else:
                log(f"[ERROR] ffmpeg failed for {clip_name}: {result.stderr[-200:]}")
        log(f"[RESULT] Saved {len(rendered)} replay clip(s) to: {out_dir}")
        log_queue.put({"type": "done", "results": rendered})

    except Exception as e:
        log(f"[ERROR] {e}")
        import traceback
        log(traceback.format_exc())
        log_queue.put({"type": "error"})
    finally:
        # Always release captures — even on error
        if cap1 is not None:
            cap1.release()
        if cap2 is not None:
            cap2.release()
        if cap3 is not None:
            cap3.release()

# =============================================================================
# SESSION STATE — inherit from main app where available
# =============================================================================
for key, default in [
    ("video_path", ""), ("video2_path", ""), ("video3_path", ""), ("csv_path", ""), ("output_dir", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

if "rd_task" not in st.session_state:
    st.session_state["rd_task"] = None
if "rd_last_results" not in st.session_state:
    st.session_state["rd_last_results"] = []

# Auto-sync scraped CSV into csv_path
if st.session_state.get("scraped_csv_path") and not st.session_state.get("csv_path"):
    st.session_state["csv_path"] = st.session_state["scraped_csv_path"]

# =============================================================================
# UI
# =============================================================================

st.markdown("""
<div class="cm-hero">
    <h1><i class="ph ph-film-strip"></i>Replay Detector</h1>
    <p>Finds broadcast slow-motion replays for each event — outputs timestamps ready for ClipMaker.</p>
</div>
""", unsafe_allow_html=True)

if _missing:
    st.error(
        f"**Missing dependency:** {', '.join(_missing)}\n\n"
        "Install it by running:\n\n"
        f"```\npip install {' '.join(_missing)}\n```"
    )
    st.stop()

st.markdown('<hr>', unsafe_allow_html=True)

col1, col2 = st.columns([1, 1], gap="large")

# ── LEFT COLUMN ──────────────────────────────────────────────────────────────
with col1:
    st.markdown('<div class="cm-section first"><i class="ph ph-files"></i>Files</div>', unsafe_allow_html=True)

    if IS_MAC:
        uploaded_video = st.file_uploader("Video File", type=["mp4", "mkv", "avi", "mov"])
        if uploaded_video:
            st.session_state.video_path = _save_uploaded_file(uploaded_video)
        video_path = st.session_state.video_path

        split_video = st.checkbox(
            "My match is spread across multiple video files",
            key="split_video_mac",
            help="Tick this if you have separate files for 1st half, 2nd half, or extra time."
        )
        video2_path = ""
        video3_path = ""
        if split_video:
            uploaded_video2 = st.file_uploader(
                "2nd Half Video (optional)", type=["mp4", "mkv", "avi", "mov"], key="uploader_video2"
            )
            if uploaded_video2:
                st.session_state.video2_path = _save_uploaded_file(uploaded_video2)
            video2_path = st.session_state.video2_path

            uploaded_video3 = st.file_uploader(
                "Extra Time Video (optional)", type=["mp4", "mkv", "avi", "mov"], key="uploader_video3"
            )
            if uploaded_video3:
                st.session_state.video3_path = _save_uploaded_file(uploaded_video3)
            video3_path = st.session_state.video3_path

        _sc = st.session_state.get("scraped_csv_path", "")
        if _sc:
            csv_path = _sc
            st.info(f"Loaded from WhoScored Scraper: **{os.path.basename(_sc)}**")
        else:
            uploaded_csv = st.file_uploader("Events CSV", type=["csv"])
            if uploaded_csv:
                st.session_state.csv_path = _save_uploaded_file(uploaded_csv)
            csv_path = st.session_state.csv_path
    else:
        vc1, vc2 = st.columns([4, 1])
        with vc1:
            video_path = st.text_input("Video File", value=st.session_state.video_path,
                                        placeholder="Click Browse or paste full path")
        with vc2:
            st.write(""); st.write("")
            if st.button("Browse", key="browse_video"):
                picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
                if picked:
                    st.session_state.video_path = picked
                    st.rerun()

        split_video = st.checkbox(
            "My match is spread across multiple video files",
            help="Tick this if you have separate files for 1st half, 2nd half, or extra time."
        )
        video2_path = ""
        video3_path = ""
        if split_video:
            v2c1, v2c2 = st.columns([4, 1])
            with v2c1:
                video2_path = st.text_input(
                    "2nd Half Video (optional)",
                    value=st.session_state.video2_path,
                    placeholder="Click Browse or paste full path",
                    key="input_video2"
                )
            with v2c2:
                st.write(""); st.write("")
                if st.button("Browse", key="browse_video2"):
                    picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
                    if picked:
                        st.session_state.video2_path = picked
                        st.rerun()

            v3c1, v3c2 = st.columns([4, 1])
            with v3c1:
                video3_path = st.text_input(
                    "Extra Time Video (optional)",
                    value=st.session_state.video3_path,
                    placeholder="Click Browse or paste full path",
                    key="input_video3"
                )
            with v3c2:
                st.write(""); st.write("")
                if st.button("Browse", key="browse_video3"):
                    picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov"), ("All files", "*.*")])
                    if picked:
                        st.session_state.video3_path = picked
                        st.rerun()

        _sc = st.session_state.get("scraped_csv_path", "")
        if _sc:
            csv_path = _sc
            st.info(f"Loaded from WhoScored Scraper: **{os.path.basename(_sc)}**")
        else:
            cc1, cc2 = st.columns([4, 1])
            with cc1:
                csv_path = st.text_input("Events CSV (ClipMaker CSV)", value=st.session_state.csv_path,
                                          placeholder="Click Browse or paste full path")
            with cc2:
                st.write(""); st.write("")
                if st.button("Browse", key="browse_csv"):
                    picked = browse_file([("CSV files", "*.csv"), ("All files", "*.*")])
                    if picked:
                        st.session_state.csv_path = picked
                        st.rerun()

    out_dir_input = st.session_state.output_dir or "output"

    st.markdown('<div class="cm-section"><i class="ph ph-clock"></i>Kick-off Timestamps</div>', unsafe_allow_html=True)
    _shared_h1 = st.session_state.get("cm_half1_time", "")
    _shared_h2 = st.session_state.get("cm_half2_time", "")
    if _shared_h1 and _shared_h2:
        st.info("Using kick-off times from ClipMaker page")
        half1 = _shared_h1
        half2 = _shared_h2
        half3 = st.session_state.get("cm_half3_time", "")
        half4 = st.session_state.get("cm_half4_time", "")
    else:
        st.caption("Enter exactly what your video player shows at kick-off — MM:SS or HH:MM:SS")
        tc1, tc2 = st.columns(2)
        with tc1:
            half1 = st.text_input("1st Half kick-off", value="", placeholder="e.g. 4:16")
            half3 = st.text_input("ET 1st Half (optional)", value="", placeholder="leave blank")
        with tc2:
            half2 = st.text_input("2nd Half kick-off", value="", placeholder="e.g. 1:00:32")
            half4 = st.text_input("ET 2nd Half (optional)", value="", placeholder="leave blank")

    period_col = "period"
    use_fallback = False
    fallback_row = None

# ── RIGHT COLUMN ─────────────────────────────────────────────────────────────
with col2:
    st.markdown('<div class="cm-section first"><i class="ph ph-sliders"></i>Search Settings</div>', unsafe_allow_html=True)
    st.caption("Controls where and how long the detector searches for replays after each event.")

    search_after = st.number_input(
        "Search delay (seconds)",
        min_value=0, value=5, step=1,
        help="How long after the event to start checking for replay footage."
    )
    search_window = st.number_input(
        "Search window (seconds)",
        min_value=5, value=45, step=5,
        help="How long to keep searching after the delay starts."
    )
    min_replay_duration = st.number_input(
        "Minimum replay length (seconds)",
        min_value=1, value=8, step=1,
        help="Ignore short detections below this length."
    )

    st.markdown('<div class="cm-section"><i class="ph ph-wave-triangle"></i>Replay Sensitivity</div>', unsafe_allow_html=True)
    st.caption(
        "If it misses replays, choose Aggressive. If it catches normal footage, choose Conservative."
    )
    sensitivity_preset = st.select_slider(
        "Replay Sensitivity",
        options=["Conservative", "Balanced", "Aggressive"],
        value="Balanced",
        label_visibility="collapsed",
        help="Conservative: only flags obvious slow-motion replays, fewest false positives. "
             "Balanced: works well for most broadcasts. "
             "Aggressive: catches more replays but may occasionally tag non-replay footage."
    )
    _preset_map = {
        "Conservative": (3.5, 35.0, 1.0),
        "Balanced":     (2.0, 27.0, 0.5),
        "Aggressive":   (0.8, 18.0, 0.3),
    }
    flow_threshold, scene_threshold, sample_interval = _preset_map[sensitivity_preset]

    with st.expander("Advanced settings"):
        st.caption("Only change these if you need finer control.")
        scene_threshold = st.slider(
            "Scene cut sensitivity",
            min_value=10.0, max_value=60.0, value=float(scene_threshold), step=1.0,
            help="Lower values detect more cuts. Use this if replay start is slightly off."
        )
        flow_threshold = st.slider(
            "Detection threshold",
            min_value=0.5, max_value=5.0, value=float(flow_threshold), step=0.1,
            help="Lower values are more sensitive and may detect more replays."
        )
        sample_interval = st.slider(
            "Scan step (seconds)",
            min_value=0.1, max_value=1.0, value=float(sample_interval), step=0.1,
            help="How often frames are sampled. Lower values are more precise but slower."
        )

    st.markdown('<div class="cm-section"><i class="ph ph-funnel"></i>Event Filters</div>', unsafe_allow_html=True)
    st.caption("Narrow the search to specific event types. Leave blank to scan all events in the CSV.")

    final_csv_for_filter = st.session_state.csv_path or csv_path
    action_types = []
    if final_csv_for_filter and os.path.exists(final_csv_for_filter):
        try:
            _df = pd.read_csv(final_csv_for_filter)
            if "type" in _df.columns:
                action_types = sorted(_df["type"].dropna().unique().tolist())
        except Exception:
            pass

    filter_types = st.multiselect(
        "Action Types to Search",
        options=action_types,
        placeholder="All event types included" if action_types else "Load a CSV first",
        help="Only search for replays of these event types. Leave blank to search all events."
    )

st.markdown('<hr>', unsafe_allow_html=True)

run_col, run_hint = st.columns([1, 3])
with run_col:
    run_btn = st.button("Scan for Replays", type="primary", use_container_width=True)
with run_hint:
    st.caption("You can switch pages while scanning. The job keeps running in the background.")

progress_placeholder = st.empty()
status_placeholder = st.empty()
log_placeholder = st.empty()
results_placeholder = st.empty()

final_video = st.session_state.video_path or video_path
final_video2 = st.session_state.video2_path or video2_path
final_video3 = st.session_state.video3_path or video3_path
final_csv = st.session_state.csv_path or csv_path
final_out_dir = st.session_state.output_dir or out_dir_input or "output"
dry_run = True

if run_btn:
    errors = []
    if not final_video:
        errors.append("Video file is required.")
    if split_video and not final_video2:
        errors.append("Split video enabled but no 2nd half video file was provided.")
    if not final_csv:
        errors.append("Events CSV is required.")
    if not half1:
        errors.append("1st half kick-off time is required.")
    if not half2:
        errors.append("2nd half kick-off time is required.")
    if errors:
        for e in errors:
            st.error(e)
    else:
        # Apply action type filter to CSV before passing to detector
        working_csv = final_csv
        if filter_types:
            try:
                _fdf = pd.read_csv(final_csv)
                _fdf = _fdf[_fdf["type"].isin(filter_types)]
                filtered_csv_path = os.path.join(final_out_dir, "_filtered_events.csv")
                os.makedirs(final_out_dir, exist_ok=True)
                _fdf.to_csv(filtered_csv_path, index=False)
                working_csv = filtered_csv_path
            except Exception as ex:
                st.error(f"Failed to filter CSV: {ex}")
                st.stop()

        config = {
            "video_file": final_video,
            "data_file": working_csv,
            "half1_time": half1,
            "half2_time": half2,
            "half3_time": half3 or "",
            "half4_time": half4 or "",
            "period_column": "" if use_fallback else period_col,
            "fallback_row": int(fallback_row) if use_fallback else None,
            "search_after": search_after,
            "search_window": search_window,
            "min_replay_duration": min_replay_duration,
            "scene_threshold": scene_threshold,
            "flow_threshold": flow_threshold,
            "sample_interval": sample_interval,
            "output_dir": final_out_dir,
            "dry_run": dry_run,
            "split_video": split_video,
            "video2_file": final_video2,
            "video3_file": final_video3,
            "max_event_seconds": 10.0,
        }
        log_queue = queue.Queue()
        progress_queue = queue.Queue()
        thread = threading.Thread(
            target=run_detector, args=(config, log_queue, progress_queue), daemon=False
        )
        thread.start()
        st.session_state["rd_task"] = {
            "thread": thread,
            "log_queue": log_queue,
            "progress_queue": progress_queue,
            "log_lines": [],
            "last_progress": {"current": 0, "total": 1, "elapsed": 0},
            "results": None,
            "config": config,
        }
        st.rerun()

task = st.session_state.get("rd_task")
if task:
    thread = task["thread"]
    log_queue = task["log_queue"]
    progress_queue = task["progress_queue"]

    while not progress_queue.empty():
        task["last_progress"] = progress_queue.get_nowait()

    while not log_queue.empty():
        msg = log_queue.get_nowait()
        if msg["type"] == "log":
            task["log_lines"].append(msg["msg"])
        elif msg["type"] == "done":
            task["results"] = msg.get("results", [])

    cur = task["last_progress"]["current"]
    tot = task["last_progress"]["total"]
    elapsed = task["last_progress"]["elapsed"]
    frac = cur / tot if tot > 0 else 0

    if cur > 0 and elapsed > 0:
        rate = cur / elapsed
        remaining = (tot - cur) / rate if rate > 0 else 0
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        eta_str = f"{mins}m {secs:02d}s remaining"
    else:
        eta_str = "Calculating..."

    with progress_placeholder.container():
        st.markdown(
            f'<div class="progress-label">Event {cur} of {tot} — {eta_str}</div>',
            unsafe_allow_html=True
        )
        st.progress(frac)

    log_placeholder.markdown(
        f'<div class="log-box">{"<br>".join(task["log_lines"])}</div>',
        unsafe_allow_html=True
    )

    if thread.is_alive():
        st.info("Replay scan is running in the background. You can leave this page and come back.")
        time.sleep(0.4)
        st.rerun()
    else:
        final_results = task.get("results") or []
        progress_placeholder.empty()
        st.session_state["rd_task"] = None
        st.session_state["rd_last_results"] = final_results

        if final_results:
            replay_map = {}
            for r in final_results:
                key = (r["event_type"], r["event_minute"])
                replay_map[key] = {
                    "start": r["replay_start"],
                    "end": r["replay_end"],
                    "clip_path": r.get("clip_path", ""),
                    "confidence": r["confidence"],
                }
            st.session_state["replay_map"] = replay_map

            import json as _json
            _map_path = os.path.join(task["config"]["output_dir"], ".replay_map.json")
            try:
                _json_map = {f"{k[0]}||{k[1]}": v for k, v in replay_map.items()}
                with open(_map_path, "w") as _f:
                    _json.dump(_json_map, _f)
                st.session_state["replay_map_path"] = _map_path
            except Exception:
                pass

last_results = st.session_state.get("rd_last_results") or []
if last_results:
    st.success(
        f"Scan complete. **{len(last_results)} replay{'s' if len(last_results) != 1 else ''}** found."
    )

    def _conf_label(c):
        if c >= 0.70:
            return "High"
        if c >= 0.40:
            return "Medium"
        return "Low"

    summary_rows = [{
        "Event": f"{r['event_type']} {r['event_minute']}'{r['event_second']:02d}\"",
        "Period": f"P{r['event_period']}",
        "Replay Start": r.get("replay_clock_start", f"{r['replay_start']:.1f}s"),
        "Duration": f"{r['replay_duration']:.0f}s",
        "Quality": _conf_label(r["confidence"]),
    } for r in last_results]
    results_placeholder.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

# Footer
st.markdown('<div class="footer">@B03GHB4L1 · Replay Detector</div>', unsafe_allow_html=True)


