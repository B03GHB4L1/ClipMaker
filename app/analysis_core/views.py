"""The shared native view format for map-style tabs.

Every map tab returns a dict with these keys, rendered by
ui/analysis/tabs/event-tab.js:

- ``filters``: [{key, label, type: "segmented"|"select", options: [{value, label}], value}]
- ``share``: {home, away} percentages or None; ``stats``: [{label, home, away?}] or None
- ``components``: [{role: "aux"|"map", args}] in display order; clicks on "map"
  components select an item
- ``legend``, ``notice`` (a prompt such as "Select a player") and ``empty`` (a
  no-data message), each text or None
- ``picker``: {label, placeholder, items: [{id, label}]} or None
- ``selected``: {id, title, is_home, subtitle, badges: [{text, tone}],
  fields: [{label, value}], event: {minute, second, period, player}} or None
- ``controls``: the validated control values the view used
"""
from __future__ import annotations

from .common import PITCH_ZONE_OPTIONS, fmt_time

DEPTH_ZONE_OPTIONS = ["", "Defensive Third", "Middle Third", "Attacking Third"]


def view(**values):
    base = {"filters": [], "share": None, "stats": None, "components": [], "legend": None, "notice": None,
            "empty": None, "picker": None, "selected": None, "controls": {}}
    base.update(values)
    return base


def choice(value, options, default=None):
    """The value if it is one of the options, else the default (first option)."""
    values = [option["value"] if isinstance(option, dict) else option for option in options]
    if value in values:
        return value
    return values[0] if default is None and values else default


def segmented(key, label, options, value):
    return {"key": key, "label": label, "type": "segmented",
            "options": [{"value": option, "label": option} for option in options], "value": value}


def select(key, label, options, value, labels=None):
    labels = labels or {}
    return {"key": key, "label": label, "type": "select",
            "options": [{"value": option, "label": labels.get(option, option)} for option in options], "value": value}


def pitch_zone_filter(value, key="zone"):
    return select(key, "Pitch zone", PITCH_ZONE_OPTIONS, value, {"": "Any pitch zone"})


def depth_zone_filter(value, key="depth"):
    return select(key, "Depth zone", DEPTH_ZONE_OPTIONS, value, {"": "Any depth zone"})


def as_index(value, index):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number in index else None


def team_options(frame, home_team, away_team):
    options = [team for team in (home_team, away_team) if team]
    return options or sorted(frame["team"].dropna().unique().tolist())[:2]


def picker(label, placeholder, frame, label_fn):
    return {"label": label, "placeholder": placeholder,
            "items": [{"id": int(idx), "label": label_fn(row)} for idx, row in frame.iterrows()]}


def event_of(row):
    return {"minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
            "period": str(row.get("period", "FirstHalf")), "player": str(row.get("playerName", ""))}


def selected_panel(frames, idx, row, badges, fields):
    team = row.get("team", "")
    return {
        "id": int(idx),
        "title": str(row.get("playerName", "Unknown")),
        "is_home": team == frames.home_team,
        "subtitle": f"{team} · {fmt_time(row.get('minute', 0), row.get('second', 0), row.get('period', ''))}",
        "badges": badges,
        "fields": fields,
        "event": event_of(row),
    }


def badge(text, tone="neutral"):
    """Badge text without the classic page's bracketed icon code."""
    import re
    return {"text": re.sub(r"\[[A-Z ]+\]\s*", "", str(text)).strip(), "tone": tone}


def clip_event(build):
    """A clip handler that resolves the selected event through the view builder."""
    def handler(frames, controls):
        selected = build(frames, controls).get("selected")
        if not selected:
            raise ValueError("Select an event before cutting its clip.")
        return selected["event"]
    return handler
