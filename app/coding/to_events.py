"""Coded events (video time) to the match-clock event table scraped matches use.

The clip cutter maps match clock to video time with the kick-off markers:
``video = kickoff[p] + (clock - period_offset[p])`` (``match_clock_to_video_time``
in clipmaker_core). This module is its inverse, so the match clock a coded event
shows in Filter is the one a feed would give it (to the second).

Clips of coded rows are not timed by that clock, though: each row carries its
exact ``video_time`` and the cutter uses it (``clipmaker_core.coded_video_time``).
So a shootout code is cut where it was coded even though the penalty marker
stands for the first kick, not the start of the period."""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import store, templates

# period number, marker key, feed period name, match clock at its kick-off (seconds)
PERIODS = (
    (1, "1H", "FirstHalf", 0),
    (2, "2H", "SecondHalf", 45 * 60),
    (3, "ET1", "FirstPeriodOfExtraTime", 90 * 60),
    (4, "ET2", "SecondPeriodOfExtraTime", 105 * 60),
    (5, "PEN", "PenaltyShootout", 120 * 60),
)
KEY_PERIOD = {key: number for number, key, _, _ in PERIODS}

# The scraped table's core columns first, then what only coded rows carry.
COLUMNS = ["minute", "second", "type", "outcomeType", "period", "playerName", "team", "x", "y", "endX", "endY",
           "depth_zone", "pitch_zone", "homeTeam", "awayTeam", "matchName", "source", "code", "coded_id", "video_time", "video_end",
           "duration", "end_minute", "end_second", "before", "after", "tags", "shirt", *templates.FLAGS]


def depth_zone(x: float) -> str:
    """Third of the pitch from x, as whoscored_scraper._depth_zone labels scraped events."""
    return "Defensive Third" if x < 34 else "Middle Third" if x < 67 else "Attacking Third"


def pitch_zone(y: float) -> str:
    """Channel from y, as whoscored_scraper._pitch_zone(y, flip=True) labels scraped events
    (y 100 is the team's left touchline)."""
    y = 100 - y
    if y < 20:
        return "Left Wing"
    if y < 37:
        return "Left Half Space"
    if y < 63:
        return "Centre"
    return "Right Half Space" if y < 80 else "Right Wing"


def parse_marker(value: Any) -> float | None:
    """'1:02:03', '62:03' or '3723' as seconds; None when unset or unreadable."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = [float(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(part < 0 for part in parts):
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def kickoffs(markers: dict[str, Any]) -> dict[int, float]:
    found = {}
    for number, key, _, _ in PERIODS:
        seconds = parse_marker((markers or {}).get(key))
        if seconds is not None:
            found[number] = seconds
    return found


def place(event: dict[str, Any], starts: dict[int, float], video_of: Callable[[int], str]) -> tuple[int, int] | None:
    """(period, match-clock seconds) for one coded event, or None before the first kick-off on its video.

    ``video_of(period)`` names the file each period plays from (the server's
    ``video_for_period``): an event coded on the second-half file can only
    belong to a period that plays from that file."""
    source = video_of(KEY_PERIOD[event["src"]])
    best = None
    for number, _, _, offset in PERIODS:
        start = starts.get(number)
        if start is None or start > event["t"] + 1e-6 or video_of(number) != source:
            continue
        if best is None or start >= best[1]:
            best = (number, start, offset)
    if best is None:
        return None
    number, start, offset = best
    return number, offset + int(round(event["t"] - start))


def rows(document: dict[str, Any], markers: dict[str, Any], video_of: Callable[[int], str],
         home: str = "", away: str = "") -> tuple[list[dict[str, Any]], list[str]]:
    """Event rows in the scraped format, and the ids of events with no kick-off before them.

    An interval is one row from its start, with ``duration`` and its end on the
    same period's clock; one still running is left out until it stops. Each row
    carries its code's lead-in and lead-out as ``before`` and ``after``, and its
    exact place in the video as ``video_time`` (and ``video_end``), which the
    clip cutter uses instead of the match clock.

    Tags are listed by name; a tag with an outcome sets ``outcomeType`` and a
    tag with a flag sets that qualifier column, so Filter's Successful and
    Headers qualifiers work on coded rows. A shirt number becomes the player's
    name from the project's squad list (or "#9" when the squad has no name)."""
    codes = store.panel_codes(document)
    tags = store.panel_tags(document)
    squads = document.get("squads") or {}
    starts = kickoffs(markers)
    names = {number: name for number, _, name, _ in PERIODS}
    home, away = home or "Home", away or "Away"
    table, unplaced = [], []
    for event in document.get("events", []):
        interval = codes[event["code"]]["kind"] == "interval"
        if interval and event.get("end") is None:
            continue
        placed = place(event, starts, video_of)
        if placed is None:
            unplaced.append(event["id"])
            continue
        period, clock = placed
        code = codes[event["code"]]
        minute, second = divmod(clock, 60)
        before, after = store.lead(document, event["code"])
        span = {}
        if interval:
            length = round(event["end"] - event["t"], 3)
            end_minute, end_second = divmod(clock + int(round(length)), 60)
            span = {"video_end": event["end"], "duration": length, "end_minute": end_minute, "end_second": end_second}
        chosen = [tags[tag] for tag in event.get("tags", []) if tag in tags]
        outcome = next((tag["outcome"] for tag in reversed(chosen) if tag.get("outcome")), code["outcome"])
        flags = {flag: False for flag in templates.FLAGS}
        flags.update({tag["flag"]: True for tag in chosen if tag.get("flag")})
        player = ""
        if event.get("player") is not None:
            names_by_number = {item["number"]: item["name"] for item in squads.get(event["team"], [])}
            player = names_by_number.get(event["player"]) or f"#{event['player']}"
        table.append((period, clock, {
            "minute": minute, "second": second, "type": code["type"], "outcomeType": outcome,
            "period": names[period], "playerName": player, "team": {"home": home, "away": away}.get(event["team"], ""),
            "x": event.get("x", ""), "y": event.get("y", ""), "endX": event.get("endX", ""), "endY": event.get("endY", ""),
            "depth_zone": depth_zone(event["x"]) if "x" in event else "",
            "pitch_zone": pitch_zone(event["y"]) if "y" in event else "", "homeTeam": home, "awayTeam": away,
            "matchName": f"{home} vs {away}", "source": "coded", "code": code["label"], "coded_id": event["id"],
            "video_time": event["t"], "video_end": "", "duration": "", "end_minute": "", "end_second": "",
            **span, "before": before, "after": after, "tags": "; ".join(tag["label"] for tag in chosen),
            "shirt": event.get("player", ""), **flags,
        }))
    table.sort(key=lambda item: item[:2])
    return [row for _, _, row in table], unplaced


PERIOD_RANK = {name.lower(): number for number, _, name, _ in PERIODS}


def _period_rank(value: Any) -> int:
    text = str(value if value is not None else "").strip()
    if text.lower() in PERIOD_RANK:
        return PERIOD_RANK[text.lower()]
    try:
        return int(float(text))
    except ValueError:
        return 9


def write_merged(feed_path: Path, table: list[dict[str, Any]], path: Path) -> int:
    """The feed's event table with the coded rows added (C4: a project's source is "both").

    Feed rows are kept as they are, marked ``source`` "feed" unless they name a
    source of their own; coded rows join in match-clock order, after feed rows
    at the same second. Written atomically; returns the number of rows."""
    import pandas as pd

    try:  # read as saved: the merged copy must not change the feed's own rows
        feed = pd.read_csv(feed_path, low_memory=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        feed = pd.read_csv(feed_path, low_memory=False, encoding="latin-1")
    if "source" in feed.columns:
        feed["source"] = feed["source"].where(feed["source"].notna() & (feed["source"].astype(str) != "coded"), "feed")
    else:
        feed["source"] = "feed"
    coded = pd.DataFrame(table, columns=COLUMNS)
    merged = pd.concat([feed.assign(_coded=0), coded.assign(_coded=1)], ignore_index=True, sort=False)
    merged["_period"] = merged["period"].map(_period_rank) if "period" in merged.columns else 0
    for column in ("minute", "second"):
        merged[f"_{column}"] = pd.to_numeric(merged.get(column), errors="coerce").fillna(0)
    merged = merged.sort_values(["_period", "_minute", "_second", "_coded"], kind="mergesort")
    merged = merged.drop(columns=["_period", "_minute", "_second", "_coded"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="saving-", suffix=".tmp")
    os.close(fd)
    try:
        merged.to_csv(temporary, index=False, encoding="utf-8-sig")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(merged)


def write_csv(path: Path, table: list[dict[str, Any]]) -> Path:
    """Write the table atomically, UTF-8 with a byte-order mark like scraped tables."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="saving-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(table)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
