"""Views and tabs of the analysis workspace, shared by API and UI.

``native`` marks tabs whose native implementation is complete. Tabs without
it fall back to the classic Streamlit workspace.
"""
from __future__ import annotations

VIEWS = {
    "analyst": "Analyst Room",
    "tactical": "Tactical Lab",
}

# Order and labels match the classic workspaces.
TABS = {
    "analyst": [
        {"slug": "shot-map", "label": "Shot Map", "classic": "◉ Shot Map", "native": False},
        {"slug": "pass-map", "label": "Pass Map", "classic": "◎ Pass Map", "native": False},
        {"slug": "defensive-actions", "label": "Defensive Actions", "classic": "■ Defensive Actions", "native": False},
        {"slug": "dribbles-carries", "label": "Dribbles & Carries", "classic": "◈ Dribbles & Carries", "native": False},
        {"slug": "goalkeeper", "label": "Goalkeeper", "classic": "⊞ Goalkeeper", "native": False},
        {"slug": "build-up", "label": "Build-Up", "classic": "↗ Build-Up", "native": False},
        {"slug": "pressing", "label": "Pressing", "classic": "◆ Pressing", "native": False},
        {"slug": "comparison", "label": "Comparison", "classic": "⇄ Comparison", "native": False},
    ],
    "tactical": [
        {"slug": "defensive-transitions", "label": "Defensive Transitions", "classic": "Defensive Transitions", "native": False},
        {"slug": "attacking-transitions", "label": "Attacking Transitions", "classic": "Attacking Transitions", "native": False},
        {"slug": "style-profile", "label": "Style Profile", "classic": "Style Profile", "native": False},
        {"slug": "set-pieces", "label": "Set Pieces", "classic": "Set Pieces", "native": False},
        {"slug": "video-lab", "label": "Video Lab", "classic": "Video Lab", "native": False},
    ],
}


def tab_slug(view: str, classic_label: str) -> str:
    return next((tab["slug"] for tab in TABS.get(view, []) if tab["classic"] == classic_label), "")


def validate_tab(view: str, tab: str) -> dict:
    """Return the tab entry or raise ValueError for unknown names."""
    if view not in VIEWS:
        raise ValueError("Unknown analytical view")
    entry = next((item for item in TABS[view] if item["slug"] == tab), None)
    if entry is None:
        raise ValueError("Unknown analytical tab")
    return entry
