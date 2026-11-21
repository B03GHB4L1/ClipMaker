"""Coded events (video time) to the match-clock event table scraped matches use.

The clip cutter maps match clock to video time with the kick-off markers:
``video = kickoff[p] + (clock - period_offset[p])`` (``match_clock_to_video_time``
in clipmaker_core). This module is its inverse, so a coded event cuts at the
second it was coded (to within half a second, as the table keeps whole seconds).

The penalty shootout marker is the first kick, not the start of the period
(``resolve_period_starts_for_video``), so shootout codes line up when the first
of them is coded on that kick."""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import store

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
           "homeTeam", "awayTeam", "matchName", "source", "code", "coded_id", "video_time"]


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
    """Event rows in the scraped format, and the ids of events with no kick-off before them."""
    codes = {code["id"]: code for code in store.CODES}
    starts = kickoffs(markers)
    names = {number: name for number, _, name, _ in PERIODS}
    home, away = home or "Home", away or "Away"
    table, unplaced = [], []
    for event in document.get("events", []):
        placed = place(event, starts, video_of)
        if placed is None:
            unplaced.append(event["id"])
            continue
        period, clock = placed
        code = codes[event["code"]]
        minute, second = divmod(clock, 60)
        table.append((period, clock, {
            "minute": minute, "second": second, "type": code["type"], "outcomeType": code["outcome"],
            "period": names[period], "playerName": "", "team": {"home": home, "away": away}.get(event["team"], ""),
            "x": "", "y": "", "endX": "", "endY": "", "homeTeam": home, "awayTeam": away,
            "matchName": f"{home} vs {away}", "source": "coded", "code": code["label"], "coded_id": event["id"],
            "video_time": event["t"],
        }))
    table.sort(key=lambda item: item[:2])
    return [row for _, _, row in table], unplaced


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
