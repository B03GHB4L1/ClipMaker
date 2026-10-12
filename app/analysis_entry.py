"""Retain the original analytical views behind the compact project shell."""
import streamlit as st
from project_analysis import sync_project_state, compact_analysis_style

st.set_page_config(layout="wide", initial_sidebar_state="collapsed")
try:
    sync_project_state()
except (ValueError, OSError, KeyError) as error:
    st.error(str(error))
    st.stop()
page_name = st.query_params.get("view", "analyst")
page = st.navigation([
    st.Page("pages/2_The_Analysts_Room.py", title="Analyst Room", default=page_name != "tactical"),
    st.Page("pages/3_Tactical_Lab.py", title="Tactical Lab", default=page_name == "tactical"),
], position="hidden")
compact_analysis_style()
page.run()
compact_analysis_style()
