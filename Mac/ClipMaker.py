import sys
import os
import threading
import queue
import time
import platform
import streamlit as st

from whoscored_scraper import scrape_whoscored, save_scraped_match_csv
from clipmaker_core import normalize_event_labels, ping_proxy, read_csv_safe
import theme

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="ClipMaker v1.2.2 by B4L1",
    page_icon="ClipMaker_logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject(
    logo_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ClipMaker_logo.png"),
)
theme.init_shared_state()
theme.render_top_nav("home")
# =============================================================================
# FILE / FOLDER DIALOG HELPERS
# =============================================================================
IS_MAC = platform.system() == "Darwin"

# -- macOS helpers (use osascript; tkinter can fail from Streamlit worker threads on Mac) --

def _browse_file_mac():
    """Open a native macOS file picker via AppleScript. Safe from any thread."""
    import subprocess
    script = 'tell application "Finder" to set f to (choose file)\nreturn POSIX path of f'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _browse_folder_mac():
    """Open a native macOS folder picker via AppleScript. Safe from any thread."""
    import subprocess
    script = 'tell application "Finder" to set f to (choose folder)\nreturn POSIX path of f'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip().rstrip("/")
    except Exception:
        pass
    return ""


def _pick_file_thread(result_queue, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw()
    try: root.wm_attributes("-topmost", True)
    except Exception: pass
    path = filedialog.askopenfilename(filetypes=filetypes)
    root.destroy()
    result_queue.put(path)

def _pick_folder_thread(result_queue):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw()
    try: root.wm_attributes("-topmost", True)
    except Exception: pass
    path = filedialog.askdirectory()
    root.destroy()
    result_queue.put(path)

def browse_file(filetypes):
    if IS_MAC:
        return _browse_file_mac()
    q = queue.Queue()
    t = threading.Thread(target=_pick_file_thread, args=(q, filetypes), daemon=True)
    t.start(); t.join(timeout=60)
    try: return q.get_nowait()
    except queue.Empty: return ""

def browse_folder():
    if IS_MAC:
        return _browse_folder_mac()
    q = queue.Queue()
    t = threading.Thread(target=_pick_folder_thread, args=(q,), daemon=True)
    t.start(); t.join(timeout=60)
    try: return q.get_nowait()
    except queue.Empty: return ""

def _save_uploaded_file(uploaded_file):
    import tempfile
    suffix = os.path.splitext(uploaded_file.name)[1]
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(uploaded_file.read())
    tmp.close()
    return tmp.name


# =============================================================================
# SESSION STATE
# =============================================================================
for key, default in [
    ("video_path", ""), ("video2_path", ""), ("csv_path", ""), ("output_dir", ""),
    ("half1_time", ""), ("half2_time", ""), ("half3_time", ""), ("half4_time", ""),
    ("half5_time", ""), ("had_extra_time", False), ("had_penalties", False),
    ("split_video", False), ("whoscored_url", ""),
    ("before_buffer", 5), ("after_buffer", 8), ("min_gap", 6),
]:
    if key not in st.session_state:
        st.session_state[key] = default

if "scraper_full_df" not in st.session_state:
    st.session_state["scraper_full_df"] = None
if "multi_scraped_csv_paths" not in st.session_state:
    st.session_state["multi_scraped_csv_paths"] = []
if "scraper_batch_results" not in st.session_state:
    st.session_state["scraper_batch_results"] = []
if "match_setup_by_csv" not in st.session_state:
    st.session_state["match_setup_by_csv"] = {}
if "active_setup_csv_path" not in st.session_state:
    st.session_state["active_setup_csv_path"] = st.session_state.get("csv_path", "")

def _saved_whoscored_csv_paths():
    match_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "match data")
    if not os.path.isdir(match_dir):
        return []
    return sorted(
        os.path.join(match_dir, name)
        for name in os.listdir(match_dir)
        if name.lower().startswith("whoscored_") and name.lower().endswith(".csv")
    )


def _match_names_from_saved_csv(path):
    try:
        df = read_csv_safe(path)
        home = str(df["homeTeam"].dropna().iloc[0]) if "homeTeam" in df.columns and not df["homeTeam"].dropna().empty else ""
        away = str(df["awayTeam"].dropna().iloc[0]) if "awayTeam" in df.columns and not df["awayTeam"].dropna().empty else ""
        if home or away:
            return home, away, len(df)
        if "team" in df.columns:
            teams = df["team"].dropna().astype(str).unique().tolist()[:2]
            return (teams + ["", ""])[:2] + [len(df)]
        return "", "", len(df)
    except Exception:
        stem = os.path.splitext(os.path.basename(path))[0]
        label = stem.replace("whoscored_", "").replace("_all_events", "")
        if "_vs_" in label:
            home, away = label.split("_vs_", 1)
            return home.replace("_", " "), away.replace("_", " "), 0
        return label.replace("_", " "), "", 0


def _batch_item_from_saved_csv(path):
    home, away, rows = _match_names_from_saved_csv(path)
    return {"url": "", "path": path, "rows": rows, "home_team": home, "away_team": away}


saved_match_paths = _saved_whoscored_csv_paths()
current_paths = st.session_state.get("multi_scraped_csv_paths", []) or []
all_match_paths = []
for path in current_paths + saved_match_paths:
    if path and os.path.exists(path) and path not in all_match_paths:
        all_match_paths.append(path)

if all_match_paths:
    st.session_state["multi_scraped_csv_paths"] = all_match_paths
    existing_batch = {
        item.get("path"): item
        for item in st.session_state.get("scraper_batch_results", []) or []
        if item.get("path") and os.path.exists(item.get("path"))
    }
    if len(existing_batch) < len(all_match_paths):
        st.session_state["scraper_batch_results"] = [
            existing_batch.get(path) or _batch_item_from_saved_csv(path)
            for path in all_match_paths
        ]
_scraped = st.session_state.get("scraped_csv_path", "")
if _scraped and _scraped != st.session_state.csv_path:
    st.session_state.csv_path = _scraped

if "proxy_warmed" not in st.session_state:
    st.session_state["proxy_warmed"] = True
    threading.Thread(target=ping_proxy, daemon=True).start()


# =============================================================================
# HEADER
# =============================================================================
_logo_b64 = theme.load_logo_b64(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ClipMaker_logo.png"))
st.markdown(theme.logo_header("CLIPMAKER v1.2.2", "Football highlight reel generator · by B4L1", _logo_b64 or None, uppercase_title=False), unsafe_allow_html=True)

# =============================================================================
# STEP 1 — WHOSCORED SCRAPER
# =============================================================================
st.markdown(theme.step_header(1, "WhoScored Scraper"), unsafe_allow_html=True)

scrape_c1, scrape_c2 = st.columns([9.6, 1.0], gap="small")
with scrape_c1:
    scraper_url = st.text_area(
        "WhoScored match URLs",
        value=st.session_state.get("whoscored_url", ""),
        placeholder="Paste one WhoScored match URL per line to scrape a batch",
        height=84,
        label_visibility="collapsed",
    )
    if scraper_url != st.session_state.get("whoscored_url", ""):
        st.session_state["whoscored_url"] = scraper_url
with scrape_c2:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    scrape_btn = st.button("Scrape", use_container_width=True)

st.caption("WhoScored is the data source. Paste one match URL for normal use, or one URL per line for a multi-match scrape.")

# Scraper steps — shown during and after a run
_SCRAPER_STEPS = [
    "Connecting to WhoScored",
    "Loading match page",
    "Extracting event data",
    "Calculating xT & progressive metrics",
    "Saving CSV",
]

scraper_status_ph = st.empty()
scraper_error_ph  = st.empty()

def _parse_scraper_urls(text):
    urls = []
    seen = set()
    for raw in str(text or "").replace(",", "\n").splitlines():
        url = raw.strip()
        if not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


_MATCH_SETUP_KEYS = [
    "video_path", "video2_path", "csv_path", "half1_time", "half2_time",
    "half3_time", "half4_time", "half5_time", "had_extra_time",
    "had_penalties", "split_video", "before_buffer", "after_buffer", "min_gap",
]


def _match_setup_label(path):
    if not path:
        return "Select a saved match..."
    for item in st.session_state.get("scraper_batch_results", []) or []:
        if item.get("path") == path:
            label = f"{item.get('home_team', '')} vs {item.get('away_team', '')}".strip(" vs ")
            return label or os.path.basename(path)
    return os.path.basename(path)


def _capture_match_setup(path):
    if not path:
        return
    st.session_state["match_setup_by_csv"][path] = {
        key: st.session_state.get(key)
        for key in _MATCH_SETUP_KEYS
        if key != "csv_path"
    }


def _restore_match_setup(path):
    setup = st.session_state.get("match_setup_by_csv", {}).get(path, {})
    st.session_state["csv_path"] = path
    st.session_state["scraped_csv_path"] = path
    for key, value in setup.items():
        st.session_state[key] = value


def _render_match_setup_selector():
    paths = [p for p in st.session_state.get("multi_scraped_csv_paths", []) or [] if p and os.path.exists(p)]
    if len(paths) <= 1:
        if st.session_state.get("csv_path"):
            st.session_state["active_setup_csv_path"] = st.session_state.get("csv_path")
        return
    current = st.session_state.get("active_setup_csv_path") or st.session_state.get("csv_path") or ""
    if current and current not in paths:
        current = ""
    options = [""] + paths
    selected = st.selectbox(
        "Setup match",
        options,
        index=options.index(current),
        format_func=_match_setup_label,
        key="home_match_setup_selector",
        help="Choose which scraped match the video, timestamps and clip settings apply to.",
    )
    st.caption("Each scraped match keeps its own video file, kick-off timestamps and clip settings.")
    if not selected:
        return
    if selected != current:
        _capture_match_setup(current)
        st.session_state["active_setup_csv_path"] = selected
        _restore_match_setup(selected)
        st.rerun()


def _scrape_url_batch(urls, out_queue, app_dir, save_dir):
    results = []
    errors = []
    total = len(urls)
    for idx, url in enumerate(urls, 1):
        out_queue.put({"type": "log", "msg": f"Starting match {idx}/{total}: {url}"})
        local_queue = queue.Queue()
        try:
            scrape_whoscored(url, local_queue, app_dir)
        except Exception as exc:
            local_queue.put({"type": "error", "msg": str(exc)})

        result = None
        last_log = ""
        while not local_queue.empty():
            msg = local_queue.get_nowait()
            if msg["type"] == "log":
                last_log = msg["msg"]
                out_queue.put({"type": "log", "msg": f"[{idx}/{total}] {msg['msg']}"})
            elif msg["type"] == "data":
                result = msg
            elif msg["type"] == "error":
                errors.append({"url": url, "error": msg.get("msg") or last_log or "Unknown error"})

        if result is not None:
            out_queue.put({"type": "log", "msg": f"[{idx}/{total}] Saving CSV"})
            saved_path = save_scraped_match_csv(
                result["df"],
                result.get("home_team", ""),
                result.get("away_team", ""),
                save_dir,
            )
            item = {
                "url": url,
                "path": saved_path,
                "rows": len(result["df"]),
                "home_team": result.get("home_team", ""),
                "away_team": result.get("away_team", ""),
                "df": result["df"],
            }
            results.append(item)
            out_queue.put({"type": "saved", "result": item})
            out_queue.put({"type": "log", "msg": f"[{idx}/{total}] Saved {os.path.basename(saved_path)}"})

    out_queue.put({"type": "done", "results": results, "errors": errors})

def _render_scraper_steps(active_step, done=False, error_msg=None):
    """Render a clean step-by-step progress list."""
    ok_green = theme.light_color("#DFFF00", "#3a5000")
    rows = []
    for i, label in enumerate(_SCRAPER_STEPS):
        if done and error_msg is None:
            icon = theme.icon_span("[OK]", color=ok_green, size=14)
        elif i < active_step:
            icon = theme.icon_span("[OK]", color=ok_green, size=14)
        elif i == active_step:
            if error_msg:
                icon = theme.icon_span("[ERR]", color="#ff7351", size=14)
            else:
                icon = (
                    '<span style="display:inline-block;width:10px;height:10px;' +
                    'border:2px solid ' + ok_green + ';border-top-color:transparent;' +
                    'border-radius:50%;animation:spin 0.8s linear infinite;' +
                    'vertical-align:middle;margin-right:2px"></span>'
                )
        else:
            icon = f'<span style="color:#2c2c2c;font-size:11px">·</span>'

        active_gray = theme.light_color("#767575", "#555555")
        color = ok_green if (i < active_step or done and not error_msg) else (
                "#ff7351" if (i == active_step and error_msg) else
                active_gray if i == active_step else "#2c2c2c"
        )
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:5px 0;' +
            f'border-bottom:1px solid var(--cm-border, #1a1a1a)">' +
            f'<span style="width:16px;text-align:center;flex-shrink:0">{icon}</span>' +
            f'<span style="font-family:monospace;font-size:11px;' +
            f'color:{color};letter-spacing:0.06em;text-transform:uppercase">{label}</span>' +
            f'</div>'
        )

    spin_css = (
        '<style>@keyframes spin{to{transform:rotate(360deg)}}</style>'
        if not done and not error_msg else ""
    )
    err_row = ""
    if error_msg:
        err_row = (
            f'<div style="margin-top:10px;padding:10px 12px;' +
            f'background:rgba(255,115,81,0.08);border-left:3px solid #ff7351;' +
            f'border-radius:2px;font-family:monospace;' +
            f'font-size:11px;color:#ff7351">{error_msg}</div>'
        )

    html = (
        f'<div class="cm-log-box" style="height:auto;margin-top:0;padding:14px 16px;border:1px solid var(--cm-border, #2c2c2c);background:var(--cm-surface, #131313);">' +
        spin_css +
        "".join(rows) +
        err_row +
        '</div>'
    )
    scraper_status_ph.markdown(html, unsafe_allow_html=True)

if scrape_btn:
    scraper_urls = _parse_scraper_urls(scraper_url)
    if not scraper_urls:
        scraper_error_ph.error("Please enter at least one WhoScored match URL.")
    else:
        scraper_error_ph.empty()
        scraper_queue = queue.Queue()
        scraper_logs  = []
        scraper_results = []
        scraper_error  = None
        app_dir = os.path.dirname(os.path.abspath(__file__))
        save_dir = st.session_state.output_dir or app_dir

        scraper_thread = threading.Thread(
            target=_scrape_url_batch,
            args=(scraper_urls, scraper_queue, app_dir, save_dir),
            daemon=True,
        )
        scraper_thread.start()

        # Map log message keywords → step index so the UI advances as work progresses
        _STEP_SIGNALS = [
            ("connect", 0), ("loading", 1), ("loaded", 1),
            ("primary event", 2), ("extracting", 2), ("event data", 2),
            ("xt values", 3), ("progressive", 3), ("xT", 3),
            ("saving", 4), ("saved", 4), ("csv", 4),
        ]
        active_step = 0
        _render_scraper_steps(active_step)

        while scraper_thread.is_alive() or not scraper_queue.empty():
            updated = False
            while not scraper_queue.empty():
                msg = scraper_queue.get_nowait()
                if msg["type"] == "log":
                    scraper_logs.append(msg["msg"])
                    ml = msg["msg"].lower()
                    for keyword, step in _STEP_SIGNALS:
                        if keyword in ml and step >= active_step:
                            active_step = step
                            updated = True
                elif msg["type"] == "saved":
                    scraper_results.append(msg["result"])
                    active_step = len(_SCRAPER_STEPS) - 1
                    updated = True
                elif msg["type"] == "error":
                    scraper_error = msg.get("msg") or (scraper_logs[-1] if scraper_logs else "Unknown error")
                    updated = True
                elif msg["type"] == "done":
                    scraper_results = msg.get("results", scraper_results)
                    errors = msg.get("errors", [])
                    if errors and not scraper_results:
                        scraper_error = errors[0].get("error", "Unknown error")
                    elif errors:
                        scraper_logs.extend(f"FAILED {e['url']}: {e['error']}" for e in errors)
                    updated = True
            if updated:
                _render_scraper_steps(active_step, error_msg=scraper_error)
            time.sleep(0.3)

        scraper_thread.join()

        if scraper_results:
            first = scraper_results[0]
            scraped_by_path = {
                item["path"]: {k: v for k, v in item.items() if k != "df"}
                for item in scraper_results
                if item.get("path")
            }
            saved_paths = []
            for path in [item["path"] for item in scraper_results if item.get("path")] + _saved_whoscored_csv_paths():
                if path and os.path.exists(path) and path not in saved_paths:
                    saved_paths.append(path)
            st.session_state["scraper_full_df"] = first["df"]
            st.session_state["scraper_home_team"] = first.get("home_team", "")
            st.session_state["scraper_away_team"] = first.get("away_team", "")
            st.session_state["scraped_csv_path"] = first["path"]
            st.session_state["scraped_csv_df"] = first["df"].to_csv(index=False)
            st.session_state["csv_path"] = first["path"]
            st.session_state["shot_map_df"] = first["df"]
            st.session_state["multi_scraped_csv_paths"] = saved_paths
            existing_batch = {
                item.get("path"): item
                for item in st.session_state.get("scraper_batch_results", []) or []
                if item.get("path") and os.path.exists(item.get("path"))
            }
            st.session_state["scraper_batch_results"] = [
                scraped_by_path.get(path) or existing_batch.get(path) or _batch_item_from_saved_csv(path)
                for path in saved_paths
            ]
            existing_setups = st.session_state.get("match_setup_by_csv", {})
            st.session_state["match_setup_by_csv"] = {
                path: existing_setups.get(path, {})
                for path in saved_paths
            }
            st.session_state["active_setup_csv_path"] = first["path"]
            if len(saved_paths) > 1:
                st.session_state["tl_multi_mode"] = True
                st.session_state["tl_selected_matches"] = saved_paths
            _render_scraper_steps(active_step, done=True)
        elif scraper_error:
            _render_scraper_steps(active_step, error_msg=scraper_error)
            with st.expander("Debug log"):
                st.code("\n".join(scraper_logs))

if st.session_state.get("scraper_full_df") is not None:
    import pandas as pd
    _df_scraped = normalize_event_labels(st.session_state["scraper_full_df"])
    _ht = st.session_state.get("scraper_home_team","")
    _at = st.session_state.get("scraper_away_team","")
    _match_label = f"{_ht} vs {_at}" if _ht and _at else "match"
    _batch = st.session_state.get("scraper_batch_results", [])
    if len(_batch) > 1:
        st.success(f"{len(_batch)} matches scraped and saved for multi-match analysis.", icon=theme.icon_shortcode("[OK]"))
        with st.expander("Scraped match batch", expanded=True):
            for item in _batch:
                label = f"{item.get('home_team', '')} vs {item.get('away_team', '')}".strip(" vs ") or os.path.basename(item.get("path", ""))
                st.caption(f"{theme.icon_shortcode('[OK]')} {label} · {item.get('rows', 0)} events · `{os.path.basename(item.get('path', ''))}`")
    else:
        st.success(f"{len(_df_scraped)} events loaded from **{_match_label}**", icon=theme.icon_shortcode("[OK]"))
    _preview_df = _df_scraped
    _preview_label = _match_label
    if len(_batch) > 1:
        _batch_options = [item for item in _batch if item.get("path") and os.path.exists(item.get("path"))]
        if _batch_options:
            with st.expander("View scraped data", expanded=False):
                _selected_item = st.selectbox(
                    "Scraped match",
                    _batch_options,
                    format_func=lambda item: (
                        f"{item.get('home_team', '')} vs {item.get('away_team', '')}".strip(" vs ")
                        or os.path.basename(item.get("path", ""))
                    ),
                    key="scraped_data_preview_match",
                )
                try:
                    _preview_df = read_csv_safe(_selected_item["path"])
                    _preview_label = (
                        f"{_selected_item.get('home_team', '')} vs {_selected_item.get('away_team', '')}".strip(" vs ")
                        or os.path.basename(_selected_item.get("path", "match"))
                    )
                    st.caption(f"{_preview_label} · {len(_preview_df)} rows · `{os.path.basename(_selected_item['path'])}`")
                    st.dataframe(_preview_df, use_container_width=True, hide_index=True)
                except Exception as exc:
                    st.error(f"Could not load scraped preview: {exc}")
    else:
        with st.expander(f"View scraped data ({len(_preview_df)} rows)", expanded=False):
            st.dataframe(_preview_df, use_container_width=True, hide_index=True)


# =============================================================================
# STEP 2 — FILES
# =============================================================================
st.markdown(theme.step_header(2, "Files"), unsafe_allow_html=True)
_render_match_setup_selector()

split_video = st.checkbox(
    "Match is split into two separate video files (1st / 2nd half)",
    value=st.session_state.get("split_video", False)
)
st.session_state["split_video"] = split_video

# Video 1
lbl1 = "1st Half Video" if split_video else "Video file"
if IS_MAC:
    _up1 = st.file_uploader(lbl1, type=["mp4","mkv","avi","mov"], key="up_video1")
    if _up1:
        _p = _save_uploaded_file(_up1)
        if _p != st.session_state.video_path:
            st.session_state.video_path = _p
            st.rerun()
    video_path = st.session_state.video_path
    if video_path: st.caption(f"{theme.icon_shortcode('[OK]')} {os.path.basename(video_path)}")
else:
    vc1, vc2 = st.columns([5, 1])
    with vc1:
        video_path = st.text_input(lbl1, value=st.session_state.video_path,
                                    placeholder="Click Browse or paste full path")
    with vc2:
        st.write(""); st.write("")
        if st.button("Browse", key="browse_video"):
            picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov *.ts"), ("All files", "*.*")])
            if picked:
                st.session_state.video_path = picked
                st.rerun()

# Video 2 (split mode)
if split_video:
    if IS_MAC:
        _up2 = st.file_uploader("2nd Half Video", type=["mp4","mkv","avi","mov"], key="up_video2")
        if _up2:
            _p2 = _save_uploaded_file(_up2)
            if _p2 != st.session_state.video2_path:
                st.session_state.video2_path = _p2
                st.rerun()
        video2_path = st.session_state.video2_path
        if video2_path: st.caption(f"{theme.icon_shortcode('[OK]')} {os.path.basename(video2_path)}")
    else:
        v2c1, v2c2 = st.columns([5, 1])
        with v2c1:
            video2_path = st.text_input("2nd Half Video", value=st.session_state.video2_path,
                                        placeholder="Click Browse or paste full path")
        with v2c2:
            st.write(""); st.write("")
            if st.button("Browse", key="browse_video2"):
                picked = browse_file([("Video files", "*.mp4 *.mkv *.avi *.mov *.ts"), ("All files", "*.*")])
                if picked:
                    st.session_state.video2_path = picked
                    st.rerun()
else:
    video2_path = ""

# CSV
_from_scraper = (st.session_state.get("scraped_csv_path")
                 and st.session_state.csv_path == st.session_state.scraped_csv_path)
if IS_MAC:
    if not _from_scraper:
        _upc = st.file_uploader("Match data CSV", type=["csv"], key="up_csv")
        if _upc:
            _pc = _save_uploaded_file(_upc)
            if _pc != st.session_state.csv_path:
                st.session_state.csv_path = _pc
                st.rerun()
    csv_path = st.session_state.csv_path
else:
    cc1, cc2 = st.columns([5, 1])
    with cc1:
        csv_path = st.text_input("Match data CSV", value=st.session_state.csv_path,
                                  placeholder="Click Browse — or scrape a match first")
    with cc2:
        st.write(""); st.write("")
        if st.button("Browse", key="browse_csv"):
            picked = browse_file([("CSV files", "*.csv"), ("All files", "*.*")])
            if picked:
                st.session_state.csv_path = picked
                st.rerun()

if _from_scraper:
    c1, c2 = st.columns([3, 1])
    c1.caption(f"{theme.icon_shortcode('[OK]')} Loaded from WhoScored Scraper")
    if c2.button("Clear", key="clear_csv", icon=theme.icon_shortcode("[X]")):
        st.session_state.csv_path = ""
        st.session_state["scraped_csv_path"] = ""
        st.session_state["scraped_csv_df"] = ""
        st.rerun()
elif st.session_state.csv_path:
    st.caption(f"{theme.icon_shortcode('[OK]')} {os.path.basename(st.session_state.csv_path)}")

# Persist paths
if video_path and video_path != st.session_state.video_path:
    st.session_state.video_path = video_path
if not split_video:
    st.session_state.video2_path = ""
elif video2_path and video2_path != st.session_state.video2_path:
    st.session_state.video2_path = video2_path
if csv_path and csv_path != st.session_state.csv_path:
    st.session_state.csv_path = csv_path


# =============================================================================
# STEP 3 — KICK-OFF TIMESTAMPS
# =============================================================================
st.markdown(theme.step_header(3, "Kick-off Timestamps"), unsafe_allow_html=True)

if split_video:
    st.caption("Enter timestamps relative to the **start of each video file**")
else:
    st.caption("Type exactly what your video player shows — MM:SS or HH:MM:SS")

kt1, kt2 = st.columns(2)
with kt1:
    half1 = st.text_input("1st Half kick-off", value=st.session_state.half1_time, placeholder="e.g. 4:16")
with kt2:
    half2 = st.text_input("2nd Half kick-off", value=st.session_state.half2_time,
                           placeholder="e.g. 0:45" if split_video else "e.g. 1:00:32")

if half1: st.session_state.half1_time = half1
if half2: st.session_state.half2_time = half2

had_et = st.checkbox("Match went to Extra Time", value=st.session_state.had_extra_time)
st.session_state.had_extra_time = had_et
if had_et:
    et1, et2 = st.columns(2)
    with et1:
        half3 = st.text_input("ET 1st Half kick-off", value=st.session_state.half3_time, placeholder="e.g. 1:35:10")
    with et2:
        half4 = st.text_input("ET 2nd Half kick-off", value=st.session_state.half4_time, placeholder="e.g. 1:50:45")
    if half3: st.session_state.half3_time = half3
    if half4: st.session_state.half4_time = half4
else:
    st.session_state.half3_time = ""
    st.session_state.half4_time = ""

had_pso = st.checkbox("Match went to Penalty Shootout", value=st.session_state.had_penalties)
st.session_state.had_penalties = had_pso
if had_pso:
    half5 = st.text_input("Penalty Shootout start", value=st.session_state.half5_time, placeholder="e.g. 2:05:30")
    if half5: st.session_state.half5_time = half5
else:
    st.session_state.half5_time = ""


# =============================================================================
# STEP 4 — CLIP SETTINGS
# =============================================================================
st.markdown(theme.step_header(4, "Clip Settings"), unsafe_allow_html=True)

cs1, cs2, cs3 = st.columns(3)
with cs1:
    before_buf = st.number_input("Seconds before event", value=int(st.session_state.get("before_buffer", 5)), min_value=0)
with cs2:
    after_buf = st.number_input("Seconds after event", value=int(st.session_state.get("after_buffer", 8)), min_value=0)
with cs3:
    min_gap = st.number_input("Merge gap (s)", value=int(st.session_state.get("min_gap", 6)), min_value=0,
                               help="Events within this many seconds are merged into one clip")

if before_buf != st.session_state.get("before_buffer"):
    st.session_state["before_buffer"] = before_buf
if after_buf != st.session_state.get("after_buffer"):
    st.session_state["after_buffer"] = after_buf
if min_gap != st.session_state.get("min_gap"):
    st.session_state["min_gap"] = min_gap
_capture_match_setup(st.session_state.get("active_setup_csv_path") or st.session_state.get("csv_path"))

st.caption("These values are used when you run ClipMaker from the **Filtering/Output** page.")
timing_color = theme.light_color("#DFFF00", "#3a5000")
st.markdown(
    f"<div style='color:{timing_color};font-size:0.78rem;margin-top:-0.1rem;'>"
    "Timing note: event data can sometimes be tagged a few seconds early or late depending on the broadcast or data source. "
    "Adjust the before/after buffer as needed if clips start too early or too late."
    "</div>",
    unsafe_allow_html=True,
)

# Readiness CTA
st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
ready = bool(
    st.session_state.csv_path and os.path.exists(st.session_state.csv_path) and
    st.session_state.video_path and os.path.exists(st.session_state.video_path) and
    (not st.session_state.get("split_video") or (
        st.session_state.get("video2_path") and os.path.exists(st.session_state.get("video2_path"))
    )) and
    st.session_state.half1_time and st.session_state.half2_time
)
if ready:
    st.success("All set — use the sidebar to go to **Filtering/Output** and build your reel, or visit **The Analyst's Room** for match analysis.", icon=":material/movie:")
else:
    missing = []
    if not st.session_state.csv_path:   missing.append("CSV file")
    if not (st.session_state.video_path and os.path.exists(st.session_state.video_path)):
        missing.append("video file")
    if st.session_state.get("split_video") and not (
        st.session_state.get("video2_path") and os.path.exists(st.session_state.get("video2_path"))
    ):
        missing.append("2nd half video file")
    if not st.session_state.half1_time: missing.append("1st half kick-off")
    if not st.session_state.half2_time: missing.append("2nd half kick-off")
    if missing:
        st.info(f"Still needed: {', '.join(missing)}")

theme.render_support_footer("Home")
