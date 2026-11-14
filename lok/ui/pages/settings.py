"""Settings: storage information, privacy, demo data, bulk exports and maintenance."""

from __future__ import annotations

import json

import streamlit as st

from lok import PRODUCT_DESCRIPTION, TAGLINE, __version__
from lok.config import SEED_PATH
from lok.domain.normalization import DEFAULT_POLICY
from lok.services import reporting_service as reporting
from lok.services.import_export_service import export_scenarios
from lok.ui import components as ui
from lok.ui import state


@st.dialog("Delete all evaluations")
def _confirm_delete_all(count: int) -> None:
    st.write(
        f"This permanently deletes **all {count} evaluation sessions** with their responses, results "
        "and reviews. Scenarios are kept. This cannot be undone."
    )
    typed = st.text_input("Type DELETE to confirm")
    c1, c2 = st.columns(2)
    if c1.button("Delete all", type="primary", disabled=typed != "DELETE", width="stretch"):
        removed = state.services().evaluations.delete_all()
        for key in (
            state.ACTIVE_EVALUATION,
            state.HISTORY_SELECTED,
            state.COMPARE_A,
            state.COMPARE_B,
            state.RESPONSE_DRAFTS,
        ):
            st.session_state.pop(key, None)
        state.flash(f"Deleted {removed} evaluation session(s).")
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


def render() -> None:
    services = state.services()
    settings = state.settings()
    ui.page_header("Settings", f"LOK {__version__} · {TAGLINE} · {PRODUCT_DESCRIPTION}", kicker="Reference")
    scenarios = services.scenarios.list_scenarios()
    sessions = services.evaluations.list_summaries()

    left, right = st.columns(2, gap="large")
    with left, st.container(border=True):
        st.subheader("Local storage")
        path = services.database.path
        size = path.stat().st_size if path.exists() else 0
        st.markdown(
            f"- **Database:** `{path}`\n"
            f"- **Schema version:** {services.database.schema_version()}\n"
            f"- **File size:** {size / 1024:,.0f} KiB\n"
            f"- **Scenarios:** {len(scenarios)} ({sum(s.is_demo for s in scenarios)} demo, "
            f"{sum(not s.is_demo for s in scenarios)} custom)\n"
            f"- **Evaluation sessions:** {len(sessions)}"
        )
        st.caption("Set the environment variable LOK_DB_PATH (or a .env file) to use another database file.")
    with right, st.container(border=True):
        st.subheader("Privacy and offline operation")
        usage_stats = st.get_option("browser.gatherUsageStats")
        st.markdown(
            "- No AI model, API key, account or cloud service is used.\n"
            "- Responses and results are stored only in the local SQLite file.\n"
            f"- Streamlit usage statistics: **{'enabled' if usage_stats else 'disabled'}** "
            "(`browser.gatherUsageStats` in `.streamlit/config.toml`).\n"
            "- Conversation content is not written to logs."
        )
        if usage_stats:
            st.warning("Usage statistics are enabled in your Streamlit configuration.")

    left, right = st.columns(2, gap="large")
    with left, st.container(border=True):
        st.subheader("Demo scenarios")
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        missing = [
            s["scenario_id"] for s in seed["scenarios"] if not services.scenarios.exists(s["scenario_id"])
        ]
        st.markdown(
            f"{len(seed['scenarios'])} synthetic demo scenarios ship with LOK; "
            f"{len(missing)} are missing from this database."
        )
        if st.button("Restore missing demo scenarios", disabled=not missing):
            inserted = services.scenarios.seed_demo_scenarios(SEED_PATH)
            state.flash(f"Restored {inserted} demo scenario(s).")
            st.rerun()
        st.caption("Demo scenarios are inserted only when missing; existing ones are never duplicated.")
    with right, st.container(border=True):
        st.subheader("Bulk exports")
        st.download_button(
            "All scenarios (JSON)",
            export_scenarios(scenarios),
            "lok_scenarios.json",
            "application/json",
            width="stretch",
        )
        st.download_button(
            "Evaluation history (CSV)",
            reporting.history_csv(sessions),
            "lok_history.csv",
            "text/csv",
            width="stretch",
            disabled=not sessions,
        )

    with st.container(border=True):
        st.subheader("Evaluation engine")
        st.markdown(
            f"- Text normalisation: {DEFAULT_POLICY.describe()}\n"
            f"- Maximum import size: {settings.max_import_bytes // 1024:,} KiB\n"
            f"- History page size: {settings.history_page_size}"
        )

    with st.container(border=True):
        st.subheader("Maintenance")
        c1, c2 = st.columns(2)
        if c1.button(
            "Clear the Scenario Builder draft", disabled=not st.session_state.get(state.BUILDER_DRAFT)
        ):
            st.session_state[state.BUILDER_DRAFT] = None
            state.flash("Builder draft cleared.")
            st.rerun()
        if c2.button("Delete all evaluations…", disabled=not sessions, icon=":material/delete_forever:"):
            _confirm_delete_all(len(sessions))
