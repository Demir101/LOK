"""LOK — LOOK FOR IT. Streamlit entry point.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from lok import APP_NAME, TAGLINE
from lok.storage.database import DatabaseError
from lok.ui import components, state
from lok.ui.pages import (
    comparison,
    dashboard,
    history,
    methodology,
    run_evaluation,
    scenario_builder,
    scenario_library,
    settings,
)

st.set_page_config(page_title=f"{APP_NAME} · {TAGLINE}", page_icon=":material/manage_search:", layout="wide")
components.inject_css()
components.sidebar_brand()

try:
    state.services()
except DatabaseError as exc:
    st.error(f"The local database could not be opened: {exc}")
    st.stop()

pages = {
    "dashboard": st.Page(
        dashboard.render,
        title="Dashboard",
        icon=":material/space_dashboard:",
        url_path="dashboard",
        default=True,
    ),
    "run": st.Page(
        run_evaluation.render,
        title="Run Evaluation",
        icon=":material/play_circle:",
        url_path="run-evaluation",
    ),
    "history": st.Page(
        history.render, title="Evaluation History", icon=":material/history:", url_path="history"
    ),
    "comparison": st.Page(
        comparison.render, title="Comparison", icon=":material/compare_arrows:", url_path="comparison"
    ),
    "library": st.Page(
        scenario_library.render,
        title="Scenario Library",
        icon=":material/library_books:",
        url_path="scenario-library",
    ),
    "builder": st.Page(
        scenario_builder.render,
        title="Scenario Builder",
        icon=":material/construction:",
        url_path="scenario-builder",
    ),
    "methodology": st.Page(
        methodology.render, title="Methodology", icon=":material/functions:", url_path="methodology"
    ),
    "settings": st.Page(settings.render, title="Settings", icon=":material/settings:", url_path="settings"),
}
state.register_pages(pages)

navigation = st.navigation(
    {
        "Overview": [pages["dashboard"]],
        "Evaluate": [pages["run"], pages["history"], pages["comparison"]],
        "Scenarios": [pages["library"], pages["builder"]],
        "Reference": [pages["methodology"], pages["settings"]],
    }
)

with st.sidebar:
    draft = st.session_state.get(state.BUILDER_DRAFT)
    if draft and draft.get("dirty"):
        st.warning("Unsaved scenario draft in the Scenario Builder.", icon=":material/edit_note:")
    st.caption("Runs locally. No AI model, no API key, no data leaves this machine.")

state.show_flashes()
navigation.run()
