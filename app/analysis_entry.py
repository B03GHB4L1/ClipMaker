"""Retain the original analytical views behind the compact project shell."""
import streamlit as st
from streamlit import config as _st_config
from project_analysis import sync_project_state, compact_analysis_style

# preserve_analysis_controls deliberately re-assigns widget state on every rerun
# so inactive-tab filters survive; without this, Streamlit shows users a
# one-off "created with a default value" developer warning.
_st_config.set_option("global.disableWidgetStateDuplicationWarning", True)

st.set_page_config(layout="wide", initial_sidebar_state="collapsed")
try:
    sync_project_state()
except (ValueError, OSError, KeyError) as error:
    st.error(str(error))
    st.stop()
page_name = st.query_params.get("view", "analyst")
# A native-workspace fallback link names the tab to open, once per session.
_requested_tab = st.query_params.get("tab", "")
if _requested_tab and not st.session_state.get("_requested_tab_applied"):
    from analysis_core import TABS
    _view = "tactical" if page_name == "tactical" else "analyst"
    _label = next((item["classic"] for item in TABS[_view] if item["slug"] == _requested_tab), "")
    if _label:
        st.session_state[f"{_view}_tabs"] = _label
    st.session_state["_requested_tab_applied"] = True
page = st.navigation([
    st.Page("pages/2_The_Analysts_Room.py", title="Analyst Room", default=page_name != "tactical"),
    st.Page("pages/3_Tactical_Lab.py", title="Tactical Lab", default=page_name == "tactical"),
], position="hidden")
compact_analysis_style()
page.run()
compact_analysis_style()
