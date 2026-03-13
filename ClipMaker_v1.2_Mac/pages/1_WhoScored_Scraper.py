import streamlit as st
import os
import platform
import threading
import queue
import time
import re
import json
import importlib
import pandas as pd

st.set_page_config(page_title="WhoScored Scraper", page_icon="ClipMaker_logo.png", layout="wide")

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

st.markdown("""
<div class="cm-hero">
    <hr>
    <h1><i class="ph ph-magnifying-glass"></i>WhoScored Scraper</h1>
    <p>Pull match event data from WhoScored and load it directly into ClipMaker.</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="cm-info">
    <i class="ph ph-info"></i> This scraper extracts raw event data (type, minute, second, player, period) from WhoScored match pages.<br>
    <b>xT and progressive distance columns</b> will be included as empty columns — ready for Insight90 integration.
</div>
""", unsafe_allow_html=True)

# =============================================================================
# SCRAPER CORE — requests only, no browser needed
# =============================================================================

def scrape_whoscored(url, player_name, log_queue):
    def log(msg):
        log_queue.put({"type": "log", "msg": msg})

    try:
        try:
            cffi_requests = importlib.import_module("curl_cffi.requests")
            USE_CFFI = True
        except ImportError:
            import requests as cffi_requests
            USE_CFFI = False

        log("Sending request to WhoScored...")

        if USE_CFFI:
            session = cffi_requests.Session(impersonate="chrome120")
            log("  Using Chrome TLS fingerprint (curl_cffi).")
        else:
            session = cffi_requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            })
            log("  curl_cffi not installed — using standard requests (may be blocked).")

        log("  Establishing session...")
        try:
            session.get("https://www.whoscored.com", timeout=15)
            time.sleep(1.5)
        except Exception:
            pass

        log("  Loading match page...")
        response = session.get(url, timeout=30)

        if response.status_code == 403:
            raise ValueError(
                "WhoScored blocked the request (403). "
                "Install curl_cffi for Chrome TLS impersonation: pip install curl_cffi"
            )
        if response.status_code != 200:
            raise ValueError(f"WhoScored returned status {response.status_code}.")

        html = response.text
        log(f"  Page received ({len(html):,} bytes). Parsing event data...")

        def extract_json_object(text, start_idx):
            """Extract a complete JSON object starting at start_idx by counting braces."""
            depth = 0
            in_string = False
            escape = False
            for i in range(start_idx, len(text)):
                ch = text[i]
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start_idx:i+1]
            return None

        var_names = [
            "matchCentreData",
            "initialMatchDataForScorers",
            "matchCentreEventTypeJson",
        ]

        match_data = None
        for var in var_names:
            idx = html.find(f"{var} = {{")
            if idx == -1:
                idx = html.find(f"{var}={{")
            if idx == -1:
                idx = html.find(f"{var}: {{")
            if idx == -1:
                idx = html.find(f"{var}:{{")
            if idx == -1:
                continue
            brace_idx = html.index("{", idx)
            raw = extract_json_object(html, brace_idx)
            if raw:
                try:
                    match_data = json.loads(raw)
                    log(f"  Event data found in variable: {var}")
                    break
                except Exception:
                    continue

        if match_data is None:
            log("  Known variable names not found — scanning for event array...")
            for m in re.finditer(r'"events"\s*:\s*\[', html):
                search_back = html[max(0, m.start()-2000):m.start()]
                last_brace = search_back.rfind("{")
                if last_brace == -1:
                    continue
                start = max(0, m.start()-2000) + last_brace
                raw = extract_json_object(html, start)
                if raw:
                    try:
                        candidate = json.loads(raw)
                        events_check = candidate.get("events") or candidate.get("matchEvents")
                        if events_check and len(events_check) > 5:
                            match_data = candidate
                            log(f"  Event data found via fallback scan.")
                            break
                    except Exception:
                        continue

        if match_data is None:
            snippet = ""
            for keyword in ["matchCentre", "events", "playerIdName"]:
                idx = html.find(keyword)
                if idx != -1:
                    snippet += f"  Found '{keyword}' at pos {idx}: ...{repr(html[idx:idx+80])}...\n"
            raise ValueError(
                "Could not find event data in the page source.\n"
                + (snippet or "  No known keywords found — WhoScored may have changed structure.") +
                "\nPlease share this error output with the developer."
            )

        if isinstance(match_data, dict):
            events = match_data.get("events") or match_data.get("matchEvents") or []
        elif isinstance(match_data, list):
            events = match_data
        else:
            events = []

        if not events:
            raise ValueError("Event list is empty — data structure may have changed.")

        from collections import Counter
        period_counts = Counter()
        for ev in events:
            p = ev.get("period", "?")
            if isinstance(p, dict):
                p = p.get("value", "?")
            period_counts[str(p)] += 1
        log(f"  Found {len(events)} raw events. Period breakdown: {dict(period_counts)}")

        player_dict = match_data.get("playerIdNameDictionary", {}) if isinstance(match_data, dict) else {}
        log(f"  Player dictionary has {len(player_dict)} entries.")

        home_team = ""
        away_team = ""
        player_team = {}
        if isinstance(match_data, dict):
            home_data = match_data.get("home") or match_data.get("homeTeam") or {}
            away_data = match_data.get("away") or match_data.get("awayTeam") or {}
            if isinstance(home_data, dict):
                home_team = home_data.get("name") or home_data.get("teamName") or "Home"
                for p in home_data.get("players", []):
                    pid = str(p.get("playerId") or p.get("id") or "")
                    if pid:
                        player_team[pid] = home_team
            if isinstance(away_data, dict):
                away_team = away_data.get("name") or away_data.get("teamName") or "Away"
                for p in away_data.get("players", []):
                    pid = str(p.get("playerId") or p.get("id") or "")
                    if pid:
                        player_team[pid] = away_team
        log(f"  Teams: '{home_team}' vs '{away_team}'")

        target_player_id = None
        if player_name.strip() and player_dict:
            for pid, pname in player_dict.items():
                if player_name.lower() in pname.lower():
                    target_player_id = str(pid)
                    log(f"  Matched '{player_name}' to player ID {target_player_id} ({pname})")
                    break
            if target_player_id is None:
                log(f"  WARNING: '{player_name}' not found in player dictionary.")

        if target_player_id:
            id_matches = sum(1 for ev in events if str(ev.get("playerId","")) == target_player_id)
            log(f"  Events matching player ID {target_player_id}: {id_matches}")

        PERIOD_DISPLAY = {
            1: "FirstHalf", 2: "SecondHalf",
            3: "ExtraTimeFirstHalf", 4: "ExtraTimeSecondHalf",
            5: "PenaltyShootout",
        }
        VALID_PERIODS = {"FirstHalf", "SecondHalf", "ExtraTimeFirstHalf", "ExtraTimeSecondHalf",
                         "FirstPeriodOfExtraTime", "SecondPeriodOfExtraTime", "PenaltyShootout"}

        skipped = 0
        rows = []
        for ev in events:
            try:
                player_id = str(ev.get("playerId", ""))
                player = player_dict.get(player_id, "") or ev.get("playerName", "") or ""

                if player_name.strip():
                    if target_player_id:
                        if player_id != target_player_id:
                            continue
                    else:
                        if player_name.lower() not in player.lower():
                            continue

                minute = ev.get("minute") or ev.get("expandedMinute") or 0
                second = ev.get("second") or 0

                period_raw = ev.get("period", 1)
                if isinstance(period_raw, dict):
                    period_val = int(period_raw.get("value", 1))
                    period_disp = period_raw.get("displayName") or PERIOD_DISPLAY.get(period_val, "FirstHalf")
                elif isinstance(period_raw, (int, float)):
                    period_val = int(period_raw)
                    period_disp = PERIOD_DISPLAY.get(period_val, "FirstHalf")
                else:
                    try:
                        period_val = int(period_raw)
                        period_disp = PERIOD_DISPLAY.get(period_val, "FirstHalf")
                    except (ValueError, TypeError):
                        period_disp = str(period_raw)

                if period_disp not in VALID_PERIODS:
                    continue

                etype = ev.get("type", {})
                type_name = etype.get("displayName", "Unknown") if isinstance(etype, dict) else str(etype)

                outcome = ev.get("outcomeType", {})
                outcome_name = outcome.get("displayName", "") if isinstance(outcome, dict) else str(outcome)

                rows.append({
                    "minute": int(minute),
                    "second": int(second),
                    "type": type_name,
                    "outcomeType": outcome_name,
                    "period": period_disp,
                    "playerName": player,
                    "team": player_team.get(player_id, ""),
                    "x": ev.get("x", ""),
                    "y": ev.get("y", ""),
                    # Reserved for Insight90 integration
                    "xT": "",
                    "prog_pass": "",
                    "prog_carry": "",
                })
            except Exception:
                skipped += 1
                continue

        if skipped > 0:
            log(f"  Note: {skipped} events skipped due to parse errors.")

        if not rows:
            raise ValueError(
                f"No events found for player '{player_name}'. "
                "Check the spelling or leave blank for all players."
            )

        df = pd.DataFrame(rows).sort_values(["period", "minute", "second"])
        log(f"[RESULT] Extracted {len(df)} events for {player_name or 'all players'}.")
        log_queue.put({"type": "data", "df": df, "home_team": home_team, "away_team": away_team})
        log_queue.put({"type": "done"})

    except Exception as e:
        log(f"[ERROR] {e}")
        log_queue.put({"type": "error"})

# =============================================================================
# FILE / FOLDER DIALOG HELPERS
# =============================================================================

def _pick_folder_thread(result_queue):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw()
    try:
        import platform as _pl
        if _pl.system() == "Windows":
            root.wm_attributes("-topmost", True)
    except Exception:
        pass
    path = filedialog.askdirectory()
    root.destroy()
    result_queue.put(path)

def browse_folder():
    if IS_MAC:
        return ""
    q = queue.Queue()
    t = threading.Thread(target=_pick_folder_thread, args=(q,), daemon=True)
    t.start(); t.join(timeout=60)
    try: return q.get_nowait()
    except queue.Empty: return ""

IS_MAC = platform.system() == "Darwin"

# =============================================================================
# SESSION STATE
# =============================================================================
if "scraper_full_df" not in st.session_state:
    st.session_state["scraper_full_df"] = None

# =============================================================================
# UI
# =============================================================================

col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.markdown('<div class="cm-section first"><i class="ph ph-link"></i>Match URL</div>', unsafe_allow_html=True)
    url = st.text_input(
        "WhoScored match page URL",
        placeholder="https://www.whoscored.com/matches/123456/live/...",
        help="Paste the full URL of the WhoScored match page — the one with all the live event data."
    )
    st.markdown("""
    <div class="cm-info">
        Paste the URL of any WhoScored match page. The scraper pulls the event data directly
        from the page source — no login or browser extension required.
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown('<div class="cm-section first"><i class="ph ph-folder-open"></i>Save Location</div>', unsafe_allow_html=True)
    _ss_out = st.session_state.get("output_dir", "")
    if IS_MAC:
        out_dir = st.text_input(
            "Save CSV to folder",
            value=_ss_out,
            placeholder="Paste folder path, e.g. /Users/yourname/Desktop/Clips",
        )
        if out_dir and out_dir != _ss_out:
            st.session_state["output_dir"] = out_dir
    else:
        soc1, soc2 = st.columns([4, 1])
        with soc1:
            out_dir = st.text_input(
                "Save CSV to folder",
                value=_ss_out,
                placeholder="Click Browse, or leave blank to save next to the app",
            )
        with soc2:
            st.write(""); st.write("")
            if st.button("Browse", key="scraper_browse_out"):
                picked = browse_folder()
                if picked:
                    st.session_state["output_dir"] = picked
                    st.rerun()
    if _ss_out:
        st.caption("Output folder carried over from ClipMaker — edit if needed.")
    out_filename = st.text_input("CSV filename", value="whoscored_events.csv")
    st.markdown("""
    <div class="cm-info">
        <b>xT and prog_pass / prog_carry</b> columns will be present but empty.<br>
        Reserved for Insight90 integration.
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr>', unsafe_allow_html=True)

run_col, run_hint = st.columns([1, 3])
with run_col:
    run_btn = st.button("Scrape Match", type="primary", use_container_width=True)
with run_hint:
    st.caption("Paste the WhoScored match URL above, then click Scrape Match.")

log_placeholder = st.empty()

if run_btn:
    if not url:
        st.error("Please enter a WhoScored match URL.")
    else:
        log_queue = queue.Queue()
        log_lines = []
        result_df = None

        thread = threading.Thread(
            target=scrape_whoscored,
            args=(url, "", log_queue),
            daemon=True
        )
        thread.start()

        while thread.is_alive() or not log_queue.empty():
            while not log_queue.empty():
                msg = log_queue.get_nowait()
                if isinstance(msg, dict):
                    if msg["type"] == "log":
                        log_lines.append(msg["msg"])
                    elif msg["type"] == "data":
                        result_df = msg["df"]
                        st.session_state["scraper_home_team"] = msg.get("home_team", "")
                        st.session_state["scraper_away_team"] = msg.get("away_team", "")
            log_placeholder.markdown(
                f'<div class="log-box">{"<br>".join(log_lines)}</div>',
                unsafe_allow_html=True
            )
            time.sleep(0.3)

        thread.join()

        log_placeholder.markdown(
            f'<div class="log-box">{"<br>".join(log_lines)}</div>',
            unsafe_allow_html=True
        )

        if result_df is not None:
            st.session_state["scraper_full_df"] = result_df

# =============================================================================
# RESULTS — filter, save, download
# =============================================================================
if st.session_state.get("scraper_full_df") is not None:
    full_df = st.session_state["scraper_full_df"]

    home_team = st.session_state.get("scraper_home_team", "")
    away_team = st.session_state.get("scraper_away_team", "")

    st.markdown('<hr>', unsafe_allow_html=True)
    st.markdown('<div class="cm-section"><i class="ph ph-funnel"></i>Filter Results</div>', unsafe_allow_html=True)

    if home_team and away_team:
        team_options = ["All players", f"Players from {home_team}", f"Players from {away_team}"]
    else:
        team_options = ["All players"]

    team_choice = st.radio("Filter by team", options=team_options, horizontal=True, label_visibility="collapsed")

    if team_choice == f"Players from {home_team}" and home_team:
        pool_df = full_df[full_df["team"] == home_team]
        team_suffix = f"_{home_team.replace(' ', '_')}"
    elif team_choice == f"Players from {away_team}" and away_team:
        pool_df = full_df[full_df["team"] == away_team]
        team_suffix = f"_{away_team.replace(' ', '_')}"
    else:
        pool_df = full_df
        team_suffix = ""

    player_options = (
        ["All players"] + sorted(pool_df["playerName"].dropna().unique().tolist())
        if "playerName" in pool_df.columns else ["All players"]
    )
    selected_player = st.selectbox(
        "Specific player (optional)",
        options=player_options,
        label_visibility="collapsed",
        placeholder="All players in selected team"
    )

    if selected_player != "All players":
        display_df = pool_df[pool_df["playerName"] == selected_player]
        player_suffix = f"_{selected_player.replace(' ', '_')}"
        team_suffix = player_suffix
    else:
        display_df = pool_df
        player_suffix = ""

    final_filename = out_filename.replace(".csv", f"{team_suffix}.csv") if team_suffix else out_filename

    save_col, dl_col = st.columns([1, 1])
    with save_col:
        if st.button("Save & Load into ClipMaker", type="primary", use_container_width=True):
            save_dir = out_dir.strip() if 'out_dir' in dir() and out_dir.strip() else os.path.dirname(os.path.abspath(__file__))
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, final_filename)
            display_df.to_csv(save_path, index=False, encoding="utf-8-sig")
            st.session_state["scraped_csv_path"] = save_path
            st.session_state["scraped_csv_df"] = display_df.to_csv(index=False)
            st.success(f"Saved {len(display_df)} events to: {save_path}")
            st.info("CSV loaded into ClipMaker — switch to that page to continue.")
    with dl_col:
        st.download_button(
            label="Download CSV",
            data=display_df.to_csv(index=False).encode("utf-8"),
            file_name=final_filename,
            mime="text/csv",
            use_container_width=True
        )

    st.caption(f"Showing {len(display_df)} events")
    st.dataframe(display_df, use_container_width=True)

st.markdown('<div class="footer">@B03GHB4L1 · WhoScored Scraper</div>', unsafe_allow_html=True)


