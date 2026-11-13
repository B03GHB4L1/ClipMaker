"""Streamlit-free analysis logic shared by the classic and native workspaces.

See docs/ANALYSIS_MIGRATION_PLAN.md. Nothing in this package may import
``streamlit``; ``tests/test_analysis_core.py`` enforces that.
"""

from .frames import (  # noqa: F401
    DEF_ACTIONS,
    GK_ACTIONS,
    PERIOD_MAP,
    SHOT_TYPES,
    AnalystFrames,
    FrameCache,
    build_analyst_frames,
    defensive_actions_df,
)
from .registry import TABS, VIEWS, tab_slug, validate_tab  # noqa: F401
