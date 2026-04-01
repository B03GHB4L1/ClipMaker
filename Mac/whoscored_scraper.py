import json
import os
import re
import time

import numpy as np
import pandas as pd


SHOT_TYPES = {"SavedShot", "MissedShots", "Goal", "ShotOnPost", "BlockedShot", "AttemptSaved", "Attempt"}


def _get_xt_grid_path(app_dir):
    path = os.path.join(app_dir, "config", "xT_Grid.csv")
    if not os.path.exists(path):
        raise FileNotFoundError("xT_Grid.csv not found.")
    return path


def _slugify_filename_part(value):
    value = re.sub(r"\s+", "_", str(value).strip())
    value = re.sub(r"[^A-Za-z0-9_-]", "", value)
    return value or "match"


def save_scraped_match_csv(df, home_team, away_team, save_dir):
    save_dir = os.path.join(save_dir, "match data")
    os.makedirs(save_dir, exist_ok=True)
    filename = (
        f"whoscored_{_slugify_filename_part(home_team)}"
        f"_vs_{_slugify_filename_part(away_team)}_all_events.csv"
    )
    save_path = os.path.join(save_dir, filename)
    df.to_csv(save_path, index=False, encoding="utf-8-sig")
    return save_path


def _fuzzy_team_match(name_a, name_b):
    a, b = name_a.lower().strip(), name_b.lower().strip()
    if a == b or a in b or b in a:
        return True
    words_a = {w for w in re.split(r"\W+", a) if len(w) > 3}
    words_b = {w for w in re.split(r"\W+", b) if len(w) > 3}
    return bool(words_a & words_b)


def _fuzzy_player_match(ws_name, fm_name):
    if not ws_name or not fm_name:
        return False
    a, b = ws_name.lower().strip(), fm_name.lower().strip()
    if a == b:
        return True
    last_a = a.split()[-1] if a.split() else a
    last_b = b.split()[-1] if b.split() else b
    if last_a == last_b and len(last_a) > 2:
        return True
    return last_a in b or last_b in a


def insert_ball_carries(events_df, log_func=None):
    if log_func is None:
        log_func = lambda x: None

    try:
        match_events = events_df.copy().reset_index(drop=True)
        if "cumulative_mins" not in match_events.columns:
            match_events["cumulative_mins"] = match_events["minute"] + (match_events["second"] / 60)

        for col in ["x", "y", "endX", "endY", "minute", "second"]:
            if col in match_events.columns:
                match_events[col] = pd.to_numeric(match_events[col], errors="coerce")

        match_events.loc[match_events["endX"].isna(), "endX"] = match_events.loc[match_events["endX"].isna(), "x"]
        match_events.loc[match_events["endY"].isna(), "endY"] = match_events.loc[match_events["endY"].isna(), "y"]

        match_carries = pd.DataFrame()
        for idx in range(len(match_events) - 1):
            match_event = match_events.iloc[idx]
            prev_evt_team = match_event.get("team", "")
            next_evt_idx = idx + 1
            init_next_evt = match_events.iloc[next_evt_idx]
            incorrect_next_evt = True

            while incorrect_next_evt and next_evt_idx < len(match_events):
                next_evt = match_events.iloc[next_evt_idx]
                if (
                    next_evt.get("type") == "TakeOn"
                    and next_evt.get("outcomeType") == "Successful"
                ):
                    incorrect_next_evt = True
                elif (
                    (
                        next_evt.get("type") == "TakeOn"
                        and next_evt.get("outcomeType") == "Unsuccessful"
                    )
                    or (next_evt.get("type") == "Foul")
                    or (next_evt.get("type") == "Card")
                ):
                    incorrect_next_evt = True
                else:
                    incorrect_next_evt = False
                next_evt_idx += 1

            if next_evt_idx >= len(match_events):
                continue

            next_evt = match_events.iloc[next_evt_idx - 1]
            try:
                dx = 105 * (match_event.get("endX", 0) - next_evt.get("x", 0)) / 100
                dy = 68 * (match_event.get("endY", 0) - next_evt.get("y", 0)) / 100
                dt = 60 * (
                    next_evt.get("cumulative_mins", 0) - match_event.get("cumulative_mins", 0)
                )
            except (TypeError, ValueError):
                continue

            valid_carry = (
                prev_evt_team == next_evt.get("team", "")
                and match_event.get("type") != "BallTouch"
                and dx**2 + dy**2 >= 3.0**2
                and dx**2 + dy**2 <= 100.0**2
                and dt >= 1.0
                and dt < 50.0
                and match_event.get("period") == next_evt.get("period")
            )

            if valid_carry:
                carry = {
                    "minute": int(np.floor((((init_next_evt.get("minute", 0) * 60 + init_next_evt.get("second", 0))
                                             + (match_event.get("minute", 0) * 60 + match_event.get("second", 0))) / 2) / 60)),
                    "second": int((((init_next_evt.get("minute", 0) * 60 + init_next_evt.get("second", 0))
                                    + (match_event.get("minute", 0) * 60 + match_event.get("second", 0))) / 2) % 60),
                    "type": "Carry",
                    "outcomeType": "Successful",
                    "period": next_evt.get("period", ""),
                    "playerName": next_evt.get("playerName", ""),
                    "team": next_evt.get("team", ""),
                    "x": match_event.get("endX", ""),
                    "y": match_event.get("endY", ""),
                    "endX": next_evt.get("x", ""),
                    "endY": next_evt.get("y", ""),
                    "goal_mouth_y": "",
                    "goal_mouth_z": "",
                    "is_key_pass": False,
                    "is_cross": False,
                    "is_long_ball": False,
                    "is_through_ball": False,
                    "is_corner": False,
                    "is_freekick": False,
                    "is_header": False,
                    "is_big_chance": False,
                    "is_big_chance_shot": False,
                    "xT": np.nan,
                    "prog_pass": np.nan,
                    "prog_carry": np.nan,
                    "matchName": next_evt.get("matchName", ""),
                    "homeTeam": next_evt.get("homeTeam", ""),
                    "awayTeam": next_evt.get("awayTeam", ""),
                }
                match_carries = pd.concat([match_carries, pd.DataFrame([carry])], ignore_index=True, sort=False)

        if len(match_carries) > 0:
            result_df = pd.concat([events_df, match_carries], ignore_index=True, sort=False)
            result_df = result_df.sort_values(["period", "minute", "second"]).reset_index(drop=True)
            log_func(f"  Inserted {len(match_carries)} synthetic Carry events.")
            return result_df
    except Exception as exc:
        log_func(f"  Warning: Could not insert carry events: {exc}")
    return events_df


def _apply_xt_and_progressive(df, app_dir, log):
    df = df.copy()
    for col in ["x", "y", "endX", "endY"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "endX" in df.columns and "x" in df.columns:
        df.loc[df["endX"].isna(), "endX"] = df.loc[df["endX"].isna(), "x"]
    if "endY" in df.columns and "y" in df.columns:
        df.loc[df["endY"].isna(), "endY"] = df.loc[df["endY"].isna(), "y"]

    try:
        xT_grid = pd.read_csv(_get_xt_grid_path(app_dir), header=None)
        xT_array = np.array(xT_grid, dtype=float)
        xT_rows, xT_cols = xT_array.shape
        dfxT = df[(df["type"].isin(["Pass", "Carry"])) & (df["outcomeType"] == "Successful")].copy()
        if len(dfxT) > 0:
            dfxT["x1_bin_xT"] = pd.cut(dfxT["x"], bins=xT_cols, labels=False)
            dfxT["y1_bin_xT"] = pd.cut(dfxT["y"], bins=xT_rows, labels=False)
            dfxT["x2_bin_xT"] = pd.cut(dfxT["endX"], bins=xT_cols, labels=False)
            dfxT["y2_bin_xT"] = pd.cut(dfxT["endY"], bins=xT_rows, labels=False)

            def get_zone_value(x_idx, y_idx):
                try:
                    x_idx = int(x_idx)
                    y_idx = int(y_idx)
                    if 0 <= x_idx < xT_cols and 0 <= y_idx < xT_rows:
                        return float(xT_array[y_idx, x_idx])
                except (ValueError, TypeError, IndexError):
                    pass
                return np.nan

            dfxT["start_zone_value_xT"] = dfxT[["x1_bin_xT", "y1_bin_xT"]].apply(
                lambda row: get_zone_value(row[0], row[1]), axis=1
            )
            dfxT["end_zone_value_xT"] = dfxT[["x2_bin_xT", "y2_bin_xT"]].apply(
                lambda row: get_zone_value(row[0], row[1]), axis=1
            )
            dfxT["xT"] = dfxT["end_zone_value_xT"] - dfxT["start_zone_value_xT"]
            df["xT"] = np.nan
            df.loc[dfxT.index, "xT"] = dfxT["xT"]
            log(f"  xT values calculated for {dfxT['xT'].notna().sum()} successful pass/carry events.")
    except Exception as exc:
        log(f"  Warning: Could not calculate xT values: {exc}")
        df["xT"] = np.nan

    try:
        df["prog_pass"] = np.nan
        df["prog_carry"] = np.nan
        pass_mask = (df["type"] == "Pass") & (df["outcomeType"] == "Successful")
        if pass_mask.any():
            df.loc[pass_mask, "prog_pass"] = (
                np.sqrt((105 - df.loc[pass_mask, "x"]) ** 2 + (34 - df.loc[pass_mask, "y"]) ** 2)
                - np.sqrt((105 - df.loc[pass_mask, "endX"]) ** 2 + (34 - df.loc[pass_mask, "endY"]) ** 2)
            )
        carry_mask = (df["type"] == "Carry") & (df["outcomeType"] == "Successful")
        if carry_mask.any():
            df.loc[carry_mask, "prog_carry"] = (
                np.sqrt((105 - df.loc[carry_mask, "x"]) ** 2 + (34 - df.loc[carry_mask, "y"]) ** 2)
                - np.sqrt((105 - df.loc[carry_mask, "endX"]) ** 2 + (34 - df.loc[carry_mask, "endY"]) ** 2)
            )
        log("  Progressive pass/carry distances calculated.")
    except Exception as exc:
        log(f"  Warning: Could not calculate progressive pass/carry: {exc}")

    df = insert_ball_carries(df, log_func=log)
    if "endX" in df.columns and "x" in df.columns:
        df.loc[df["endX"].isna(), "endX"] = df.loc[df["endX"].isna(), "x"]
    if "endY" in df.columns and "y" in df.columns:
        df.loc[df["endY"].isna(), "endY"] = df.loc[df["endY"].isna(), "y"]

    try:
        carry_mask = (df["type"] == "Carry") & (df["outcomeType"] == "Successful") & (df["prog_carry"].isna())
        if carry_mask.any():
            df.loc[carry_mask, "prog_carry"] = (
                np.sqrt((105 - df.loc[carry_mask, "x"]) ** 2 + (34 - df.loc[carry_mask, "y"]) ** 2)
                - np.sqrt((105 - df.loc[carry_mask, "endX"]) ** 2 + (34 - df.loc[carry_mask, "endY"]) ** 2)
            )
            log(f"  Progressive carry distances calculated for {carry_mask.sum()} inserted carry events.")
    except Exception as exc:
        log(f"  Warning: Could not calculate prog_carry for inserted carries: {exc}")

    try:
        xT_grid = pd.read_csv(_get_xt_grid_path(app_dir), header=None)
        xT_array = np.array(xT_grid, dtype=float)
        xT_rows, xT_cols = xT_array.shape
        dfxT_new = df[(df["type"] == "Carry") & (df["outcomeType"] == "Successful") & (df["xT"].isna())].copy()
        if len(dfxT_new) > 0:
            dfxT_new["x1_bin_xT"] = pd.cut(dfxT_new["x"], bins=xT_cols, labels=False)
            dfxT_new["y1_bin_xT"] = pd.cut(dfxT_new["y"], bins=xT_rows, labels=False)
            dfxT_new["x2_bin_xT"] = pd.cut(dfxT_new["endX"], bins=xT_cols, labels=False)
            dfxT_new["y2_bin_xT"] = pd.cut(dfxT_new["endY"], bins=xT_rows, labels=False)

            def get_zone_value(x_idx, y_idx):
                try:
                    x_idx = int(x_idx)
                    y_idx = int(y_idx)
                    if 0 <= x_idx < xT_cols and 0 <= y_idx < xT_rows:
                        return float(xT_array[y_idx, x_idx])
                except (ValueError, TypeError, IndexError):
                    pass
                return np.nan

            dfxT_new["start_zone_value_xT"] = dfxT_new[["x1_bin_xT", "y1_bin_xT"]].apply(
                lambda row: get_zone_value(row[0], row[1]), axis=1
            )
            dfxT_new["end_zone_value_xT"] = dfxT_new[["x2_bin_xT", "y2_bin_xT"]].apply(
                lambda row: get_zone_value(row[0], row[1]), axis=1
            )
            dfxT_new["xT"] = dfxT_new["end_zone_value_xT"] - dfxT_new["start_zone_value_xT"]
            df.loc[dfxT_new.index, "xT"] = dfxT_new["xT"]
            log(f"  xT values calculated for {len(dfxT_new)} inserted carry events.")
    except Exception as exc:
        log(f"  Warning: Could not calculate xT for inserted carries: {exc}")

    return df


def scrape_whoscored(url, log_queue, app_dir, enrich_xg=True):
    def log(msg):
        log_queue.put({"type": "log", "msg": msg})

    try:
        try:
            from curl_cffi import requests as cffi_requests
            use_cffi = True
        except ImportError:
            import requests as cffi_requests
            use_cffi = False

        session = cffi_requests.Session(impersonate="chrome120") if use_cffi else cffi_requests.Session()
        if not use_cffi:
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
        try:
            session.get("https://www.whoscored.com", timeout=15)
            time.sleep(1.5)
        except Exception:
            pass

        response = session.get(url, timeout=30)
        if response.status_code == 403:
            raise ValueError("WhoScored blocked the request (403). Install curl_cffi for Chrome TLS impersonation: pip install curl_cffi")
        if response.status_code != 200:
            raise ValueError(f"WhoScored returned status {response.status_code}.")
        html = response.text

        def extract_json_object(text, start_idx):
            depth = 0
            in_string = False
            escape = False
            for idx in range(start_idx, len(text)):
                ch = text[idx]
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start_idx:idx + 1]
            return None

        match_data = None
        for var_name in ["matchCentreData", "initialMatchDataForScorers", "matchCentreEventTypeJson", "matchCentreEventData", "matchCentreEventsData", "matchData", "matchCentreJsonData"]:
            for sep in [f"{var_name} = {{", f"{var_name}={{", f"{var_name}: {{", f"{var_name}:{{"]:
                start = html.find(sep)
                if start != -1:
                    break
            else:
                continue
            raw = extract_json_object(html, html.index("{", start))
            if not raw:
                continue
            try:
                candidate = json.loads(raw)
                events_check = candidate.get("events") or candidate.get("matchEvents")
                if events_check and len(events_check) > 5:
                    match_data = candidate
                    break
            except Exception:
                continue

        if match_data is None:
            for match in re.finditer(r'"events"\s*:\s*\[', html):
                search_back = html[max(0, match.start() - 2000):match.start()]
                last_brace = search_back.rfind("{")
                if last_brace == -1:
                    continue
                start = max(0, match.start() - 2000) + last_brace
                raw = extract_json_object(html, start)
                if not raw:
                    continue
                try:
                    candidate = json.loads(raw)
                    events_check = candidate.get("events") or candidate.get("matchEvents")
                    if events_check and len(events_check) > 5:
                        match_data = candidate
                        break
                except Exception:
                    continue

        if match_data is None:
            raise ValueError("Could not find event data in the page source.")

        match_date = None
        if isinstance(match_data, dict):
            for date_field in ("startTime", "matchDate", "date", "kickOffTime", "dtStamp"):
                value = match_data.get(date_field, "")
                if value and isinstance(value, str) and len(value) >= 10:
                    match_date = value[:10]
                    break
            if not match_date:
                date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", url)
                if date_match:
                    match_date = date_match.group(0)

        events = match_data.get("events") or match_data.get("matchEvents") or []
        if not events:
            raise ValueError("Event list is empty - data structure may have changed.")

        player_dict = match_data.get("playerIdNameDictionary", {})
        home_team = ""
        away_team = ""
        player_team = {}
        goalkeeper_names = set()   # names of all GK-position players in this match
        home_data = match_data.get("home") or match_data.get("homeTeam") or {}
        away_data = match_data.get("away") or match_data.get("awayTeam") or {}
        if isinstance(home_data, dict):
            home_team = home_data.get("name") or home_data.get("teamName") or "Home"
            for player in home_data.get("players", []):
                pid = str(player.get("playerId") or player.get("id") or "")
                if pid:
                    player_team[pid] = home_team
                pos = (player.get("position") or player.get("role") or "").strip().upper()
                if pos in ("GK", "GOALKEEPER"):
                    pname = player_dict.get(pid, "") or player.get("name") or player.get("playerName") or ""
                    if pname:
                        goalkeeper_names.add(pname)
        if isinstance(away_data, dict):
            away_team = away_data.get("name") or away_data.get("teamName") or "Away"
            for player in away_data.get("players", []):
                pid = str(player.get("playerId") or player.get("id") or "")
                if pid:
                    player_team[pid] = away_team
                pos = (player.get("position") or player.get("role") or "").strip().upper()
                if pos in ("GK", "GOALKEEPER"):
                    pname = player_dict.get(pid, "") or player.get("name") or player.get("playerName") or ""
                    if pname:
                        goalkeeper_names.add(pname)

        match_name = f"{home_team} vs {away_team}" if home_team or away_team else "WhoScored Match"
        period_display = {1: "FirstHalf", 2: "SecondHalf", 3: "ExtraTimeFirstHalf", 4: "ExtraTimeSecondHalf", 5: "PenaltyShootout"}
        valid_periods = {"FirstHalf", "SecondHalf", "ExtraTimeFirstHalf", "ExtraTimeSecondHalf", "FirstPeriodOfExtraTime", "SecondPeriodOfExtraTime", "PenaltyShootout"}

        rows = []
        for event in events:
            try:
                player_id = str(event.get("playerId", ""))
                player = player_dict.get(player_id, "") or event.get("playerName", "") or ""
                minute = event.get("minute") or event.get("expandedMinute") or 0
                second = event.get("second") or 0
                period_raw = event.get("period", 1)
                if isinstance(period_raw, dict):
                    period_val = int(period_raw.get("value", 1))
                    period_disp = period_raw.get("displayName") or period_display.get(period_val, "FirstHalf")
                elif isinstance(period_raw, (int, float)):
                    period_disp = period_display.get(int(period_raw), "FirstHalf")
                else:
                    try:
                        period_disp = period_display.get(int(period_raw), "FirstHalf")
                    except (ValueError, TypeError):
                        period_disp = str(period_raw)
                if period_disp not in valid_periods:
                    continue

                event_type = event.get("type", {})
                outcome = event.get("outcomeType", {})
                type_name = event_type.get("displayName", "Unknown") if isinstance(event_type, dict) else str(event_type)
                outcome_name = outcome.get("displayName", "") if isinstance(outcome, dict) else str(outcome)

                qualifiers = event.get("qualifiers", [])
                qualifier_map = {}
                qualifier_names = set()
                if isinstance(qualifiers, list):
                    for qualifier in qualifiers:
                        if not isinstance(qualifier, dict):
                            continue
                        qtype = qualifier.get("type", {})
                        qname = qtype.get("displayName", "") if isinstance(qtype, dict) else str(qtype)
                        qvalue = qualifier.get("value", qualifier.get("qualifierValue", ""))
                        if qname:
                            qualifier_names.add(qname)
                            qualifier_map[qname] = qvalue

                rows.append({
                    "minute": int(minute),
                    "second": int(second),
                    "type": type_name,
                    "outcomeType": outcome_name,
                    "period": period_disp,
                    "playerName": player,
                    "team": player_team.get(player_id, ""),
                    "x": event.get("x", ""),
                    "y": event.get("y", ""),
                    "endX": event.get("endX", ""),
                    "endY": event.get("endY", ""),
                    "goal_mouth_y": event.get("goalMouthY") or event.get("goal_mouth_y") or qualifier_map.get("GoalMouthY") or qualifier_map.get("GoalMouthYCoordinate") or "",
                    "goal_mouth_z": event.get("goalMouthZ") or event.get("goal_mouth_z") or qualifier_map.get("GoalMouthZ") or qualifier_map.get("GoalMouthZCoordinate") or "",
                    "is_key_pass": "KeyPass" in qualifier_names,
                    "is_cross": "Cross" in qualifier_names,
                    "is_long_ball": "Longball" in qualifier_names,
                    "is_through_ball": "Throughball" in qualifier_names,
                    "is_corner": "CornerTaken" in qualifier_names,
                    "is_freekick": "FreekickTaken" in qualifier_names,
                    "is_header": "Head" in qualifier_names,
                    "is_big_chance": "BigChanceCreated" in qualifier_names,
                    "is_big_chance_shot": "BigChance" in qualifier_names,
                    "is_gk_save": type_name == "Save" and player in goalkeeper_names,
                    "xT": "",
                    "prog_pass": "",
                    "prog_carry": "",
                    "matchName": match_name,
                    "homeTeam": home_team,
                    "awayTeam": away_team,
                })
            except Exception:
                continue

        if not rows:
            raise ValueError(
                "No events were extracted from the match. "
                "This competition may not be supported."
            )

        df = pd.DataFrame(rows).sort_values(["period", "minute", "second"]).reset_index(drop=True)

        # ── Reclassify SavedShot vs BlockedShot ───────────────────────────────
        # Each SavedShot has a paired Save event at the same minute+second+period.
        # If that Save is by a goalkeeper (is_gk_save=True) → keep as SavedShot.
        # If by an outfield player → reclassify to BlockedShot.
        save_events = df[df["type"] == "Save"][["minute","second","period","is_gk_save"]].copy()
        # Build a lookup: (minute, second, period) → is_gk_save
        save_lookup = {}
        for _, srow in save_events.iterrows():
            key = (int(srow["minute"]), int(srow["second"]), str(srow["period"]))
            # If multiple saves at same timestamp, prefer the one that IS a gk save
            existing = save_lookup.get(key)
            if existing is None or (not existing and srow["is_gk_save"]):
                save_lookup[key] = bool(srow["is_gk_save"])

        def reclassify_saved_shot(row):
            if row["type"] != "SavedShot":
                return row["type"]
            key = (int(row["minute"]), int(row["second"]), str(row["period"]))
            is_gk = save_lookup.get(key)
            if is_gk is None:
                # No paired Save event found — keep original (can happen with data gaps)
                return "SavedShot"
            return "SavedShot" if is_gk else "BlockedShot"

        def reclassify_save(row):
            if row["type"] != "Save":
                return row["type"]
            return "Save" if row["is_gk_save"] else "Block"

        df["type"] = df.apply(reclassify_saved_shot, axis=1)
        df["type"] = df.apply(reclassify_save, axis=1)
        df["type"] = df["type"].replace("MissedShots", "MissedShot")

        log("Primary event data loaded from WhoScored.")

        df = _apply_xt_and_progressive(df, app_dir, log)
        log_queue.put({"type": "data", "df": df, "home_team": home_team, "away_team": away_team, "match_name": match_name})
        log_queue.put({"type": "done"})
    except Exception as exc:
        log_queue.put({"type": "log", "msg": f"ERROR: {exc}"})
        log_queue.put({"type": "error"})
