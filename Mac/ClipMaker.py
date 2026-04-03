import sys
import os
import threading
import queue
import time
import platform
import streamlit as st

from whoscored_scraper import scrape_whoscored, save_scraped_match_csv
from clipmaker_core import ping_proxy
import theme

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="ClipMaker v1.2 by B4L1",
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
    q = queue.Queue()
    t = threading.Thread(target=_pick_file_thread, args=(q, filetypes), daemon=True)
    t.start(); t.join(timeout=60)
    try: return q.get_nowait()
    except queue.Empty: return ""

def browse_folder():
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
st.markdown(theme.logo_header("CLIPMAKER v1.2", "Football highlight reel generator · by B4L1", _logo_b64 or None, uppercase_title=False), unsafe_allow_html=True)

# Status banner
if st.session_state.csv_path and os.path.exists(st.session_state.csv_path):
    _name = os.path.basename(st.session_state.csv_path)
    st.markdown(theme.status_ready(_name), unsafe_allow_html=True)
else:
    st.markdown(theme.status_empty(), unsafe_allow_html=True)


# =============================================================================
# STEP 1 — WHOSCORED SCRAPER
# =============================================================================
st.markdown(theme.step_header(1, "WhoScored Scraper"), unsafe_allow_html=True)

scrape_c1, scrape_c2 = st.columns([9.6, 1.0], gap="small")
with scrape_c1:
    scraper_url = st.text_input(
        "WhoScored match URL",
        value=st.session_state.get("whoscored_url", ""),
        placeholder="Paste a WhoScored match URL here to load events automatically",
        label_visibility="collapsed",
    )
    if scraper_url != st.session_state.get("whoscored_url", ""):
        st.session_state["whoscored_url"] = scraper_url
with scrape_c2:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    scrape_btn = st.button("Scrape", use_container_width=True)

st.caption("WhoScored is the data source. Paste a match URL above and click Scrape to load all events.")

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

def _render_scraper_steps(active_step, done=False, error_msg=None):
    """Render a clean step-by-step progress list."""
    rows = []
    for i, label in enumerate(_SCRAPER_STEPS):
        if done and error_msg is None:
            icon = theme.icon_span("[OK]", color="#DFFF00", size=14)
        elif i < active_step:
            icon = theme.icon_span("[OK]", color="#DFFF00", size=14)
        elif i == active_step:
            if error_msg:
                icon = theme.icon_span("[ERR]", color="#ff7351", size=14)
            else:
                icon = (
                    '<span style="display:inline-block;width:10px;height:10px;' +
                    'border:2px solid #DFFF00;border-top-color:transparent;' +
                    'border-radius:50%;animation:spin 0.8s linear infinite;' +
                    'vertical-align:middle;margin-right:2px"></span>'
                )
        else:
            icon = f'<span style="color:#2c2c2c;font-size:11px">·</span>'

        color = "#DFFF00" if (i < active_step or done and not error_msg) else (
                "#ff7351" if (i == active_step and error_msg) else
                "#767575" if i == active_step else "#2c2c2c"
        )
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:5px 0;' +
            f'border-bottom:1px solid #1a1a1a">' +
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
        f'<div style="background:#131313;border:1px solid #2c2c2c;border-radius:2px;' +
        f'padding:14px 16px;margin:10px 0">' +
        spin_css +
        "".join(rows) +
        err_row +
        '</div>'
    )
    scraper_status_ph.markdown(html, unsafe_allow_html=True)

if scrape_btn:
    if not scraper_url.strip():
        scraper_error_ph.error("Please enter a WhoScored match URL.")
    else:
        scraper_error_ph.empty()
        scraper_queue = queue.Queue()
        scraper_logs  = []
        scraper_result = None
        scraper_error  = None
        app_dir = os.path.dirname(os.path.abspath(__file__))

        scraper_thread = threading.Thread(
            target=scrape_whoscored,
            args=(scraper_url.strip(), scraper_queue, app_dir),
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
                elif msg["type"] == "data":
                    scraper_result = msg
                    active_step = len(_SCRAPER_STEPS) - 1
                    updated = True
                elif msg["type"] == "error":
                    scraper_error = scraper_logs[-1] if scraper_logs else "Unknown error"
                    updated = True
            if updated:
                _render_scraper_steps(active_step, error_msg=scraper_error)
            time.sleep(0.3)

        scraper_thread.join()

        if scraper_result is not None:
            save_dir = st.session_state.output_dir or os.path.dirname(os.path.abspath(__file__))
            saved_path = save_scraped_match_csv(
                scraper_result["df"],
                scraper_result.get("home_team", ""),
                scraper_result.get("away_team", ""),
                save_dir,
            )
            st.session_state["scraper_full_df"]   = scraper_result["df"]
            st.session_state["scraper_home_team"]  = scraper_result.get("home_team", "")
            st.session_state["scraper_away_team"]  = scraper_result.get("away_team", "")
            st.session_state["scraped_csv_path"]   = saved_path
            st.session_state["scraped_csv_df"]     = scraper_result["df"].to_csv(index=False)
            st.session_state["csv_path"]           = saved_path
            st.session_state["shot_map_df"]        = scraper_result["df"]
            _render_scraper_steps(active_step, done=True)
        elif scraper_error:
            _render_scraper_steps(active_step, error_msg=scraper_error)
            with st.expander("Debug log"):
                st.code("\n".join(scraper_logs))

if st.session_state.get("scraper_full_df") is not None:
    import pandas as pd
    _df_scraped = st.session_state["scraper_full_df"]
    _ht = st.session_state.get("scraper_home_team","")
    _at = st.session_state.get("scraper_away_team","")
    _match_label = f"{_ht} vs {_at}" if _ht and _at else "match"
    st.success(f"{len(_df_scraped)} events loaded from **{_match_label}**", icon=theme.icon_shortcode("[OK]"))
    with st.expander(f"View scraped data ({len(_df_scraped)} rows)", expanded=False):
        st.dataframe(_df_scraped, use_container_width=True, hide_index=True)


# =============================================================================
# STEP 2 — FILES
# =============================================================================
st.markdown(theme.step_header(2, "Files"), unsafe_allow_html=True)

split_video = st.checkbox(
    "Match is split into two separate video files (1st / 2nd half)",
    value=st.session_state.get("split_video", False)
)
st.session_state["split_video"] = split_video

# Video 1
lbl1 = "1st Half Video" if split_video else "Video file"
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
cc1, cc2 = st.columns([5, 1])
with cc1:
    csv_path = st.text_input("Match data CSV", value=st.session_state.csv_path,
                              placeholder="Click Browse — or scrape a match first")
with cc2:
    st.write(""); st.write("")
    if st.button("Browse", key="browse_csv", disabled=_from_scraper):
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

st.caption("These values are used when you run ClipMaker from the **Filtering/Output** page.")
st.markdown(
    "<div style='color:#DFFF00;font-size:0.78rem;margin-top:-0.1rem;'>"
    "Timing note: event data can sometimes be tagged a few seconds early or late depending on the broadcast or data source. "
    "Adjust the before/after buffer as needed if clips start too early or too late."
    "</div>",
    unsafe_allow_html=True,
)

# Readiness CTA
st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
ready = bool(
    st.session_state.csv_path and os.path.exists(st.session_state.csv_path) and
    st.session_state.video_path and
    st.session_state.half1_time and st.session_state.half2_time
)
if ready:
    st.success("All set — use the sidebar to go to **Filtering/Output** and build your reel, or visit **The Analyst's Room** for match analysis.", icon=":material/movie:")
else:
    missing = []
    if not st.session_state.csv_path:   missing.append("CSV file")
    if not st.session_state.video_path: missing.append("video file")
    if not st.session_state.half1_time: missing.append("1st half kick-off")
    if not st.session_state.half2_time: missing.append("2nd half kick-off")
    if missing:
        st.info(f"Still needed: {', '.join(missing)}")

theme.render_support_footer("Home")
