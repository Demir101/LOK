"""Evaluation History: search, filter, sort, paginate, inspect, compare, export and delete."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import streamlit as st

from lok.domain.scoring import HUMAN_RATING_LABELS
from lok.services import reporting_service as reporting
from lok.storage.evaluation_repository import EvaluationNotFoundError
from lok.ui import components as ui
from lok.ui import state
from lok.ui.pages.run_evaluation import export_buttons

SORTS = {
    "Last updated (newest first)": ("updated_at", False),
    "Last updated (oldest first)": ("updated_at", True),
    "Overall score (high to low)": ("overall_score", False),
    "Overall score (low to high)": ("overall_score", True),
}


def render() -> None:
    services = state.services()
    ui.page_header(
        "Evaluation History",
        "All stored evaluation sessions. Select a row to inspect its evidence and reviews.",
        kicker="Evaluate",
    )
    rows = services.evaluations.list_summaries()
    if not rows:
        ui.empty_state(
            "No evaluations yet", "Start an evaluation from the Run Evaluation page or the Scenario Library."
        )
        if st.button("Start an evaluation", type="primary"):
            state.go("run")
        return

    df = pd.DataFrame(rows)
    df["updated_date"] = pd.to_datetime(df["updated_at"], utc=True).dt.date
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2, 1.3, 1.3, 1])
        query = c1.text_input("Search", placeholder="ID, AI system, model or scenario", key="hist_query")
        systems = c2.multiselect("AI system", sorted(df["ai_system"].unique()), key="hist_systems")
        scen = c3.multiselect("Scenario", sorted(df["scenario_title"].unique()), key="hist_scenarios")
        statuses = c4.multiselect("Status", ["draft", "in_progress", "completed"], key="hist_status")
        c5, c6, c7 = st.columns([2, 2, 1])
        lo, hi = df["updated_date"].min(), df["updated_date"].max()
        dates = c5.date_input("Updated between", (lo, hi), key="hist_dates")
        sort = c6.selectbox("Sort by", list(SORTS), key="hist_sort")
        page_size = state.settings().history_page_size

    mask = pd.Series(True, index=df.index)
    if query.strip():
        q = query.strip().casefold()
        mask &= df.apply(
            lambda r: any(
                q in str(r[c]).casefold()
                for c in ("evaluation_id", "ai_system", "model_label", "scenario_title")
            ),
            axis=1,
        )
    if systems:
        mask &= df["ai_system"].isin(systems)
    if scen:
        mask &= df["scenario_title"].isin(scen)
    if statuses:
        mask &= df["status"].isin(statuses)
    if isinstance(dates, tuple) and len(dates) == 2 and all(isinstance(d, date) for d in dates):
        mask &= (df["updated_date"] >= dates[0]) & (df["updated_date"] <= dates[1])
    filtered = df[mask]
    column, ascending = SORTS[sort]
    filtered = filtered.sort_values(column, ascending=ascending, na_position="last")

    pages = max(1, math.ceil(len(filtered) / page_size))
    page = c7.number_input("Page", 1, pages, 1, key="hist_page") if pages > 1 else 1
    window = filtered.iloc[(page - 1) * page_size : page * page_size]

    table = pd.DataFrame(
        {
            "Evaluation ID": window["evaluation_id"],
            "AI system": window["ai_system"],
            "Model / version": window["model_label"],
            "Scenario": window["scenario_title"],
            "Version": window["scenario_version"].map(lambda v: f"v{v}"),
            "Updated (UTC)": window["updated_at"].map(ui.fmt_time),
            "Status": window["status"].str.replace("_", " "),
            "Overall": window["overall_score"].map(lambda v: ui.fmt_score(None if pd.isna(v) else v)),
            "Coverage": window["coverage"].map(lambda v: ui.fmt_pct(None if pd.isna(v) else v)),
            "Passed / failed": window["passed"].astype(str) + " / " + window["failed"].astype(str),
        }
    )
    st.caption(f"{len(filtered)} of {len(df)} sessions · page {page} of {pages}")
    event = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="hist_table",
    )
    st.download_button(
        "Export filtered history (CSV)",
        reporting.history_csv(filtered.to_dict("records")),
        "lok_history.csv",
        "text/csv",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    table_choice = window.iloc[selected_rows[0]]["evaluation_id"] if selected_rows else None
    labels = {
        r[
            "evaluation_id"
        ]: f"{r['ai_system']} · {r['model_label']} — {r['scenario_title']} ({r['evaluation_id']})"
        for r in filtered.to_dict("records")
    }
    selected = ui.synced_picker(
        "Open session", list(labels), state.HISTORY_SELECTED, table_choice, labels.get, key="hist_pick"
    )
    if selected:
        _details(selected)
    else:
        st.info("Select a session in the table or the picker above to see its details.")


@st.dialog("Delete evaluation")
def _confirm_delete(evaluation_id: str) -> None:
    st.write(
        f"Permanently delete **{evaluation_id}** and all its responses, results and reviews? "
        "This cannot be undone."
    )
    c1, c2 = st.columns(2)
    if c1.button("Delete permanently", type="primary", width="stretch"):
        state.services().evaluations.delete(evaluation_id)
        st.session_state.pop(state.HISTORY_SELECTED, None)
        if st.session_state.get(state.ACTIVE_EVALUATION) == evaluation_id:
            st.session_state.pop(state.ACTIVE_EVALUATION, None)
        state.flash(f"Evaluation {evaluation_id} deleted.")
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


def _details(evaluation_id: str) -> None:
    services = state.services()
    try:
        session = services.evaluations.get(evaluation_id)
    except EvaluationNotFoundError:
        st.session_state.pop(state.HISTORY_SELECTED, None)
        st.warning("The selected evaluation no longer exists.")
        return
    scenario = services.evaluations.scenario_for(session)
    summary = services.evaluations.summarize(session)
    st.divider()
    st.subheader(f"{session.ai_system} · {session.model_label}")
    st.markdown(
        f"{ui.SESSION_BADGE[session.status]} &nbsp; `{session.evaluation_id}` · **{scenario.title}** "
        f"v{scenario.version} · created {ui.fmt_time(session.created_at)} · "
        f"evaluated {ui.fmt_time(session.evaluated_at)}"
    )
    if session.notes:
        st.caption(f"Notes: {session.notes}")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Open in Run Evaluation", type="primary", width="stretch"):
        state.go("run", **{state.ACTIVE_EVALUATION: session.evaluation_id})
    if c2.button("Compare…", width="stretch"):
        state.go("comparison", **{state.COMPARE_A: session.evaluation_id})

    ui.score_overview(summary, session.has_run)
    tabs = st.tabs(["Dimensions", "Assertion evidence", "Human reviews", "Responses", "Export & delete"])
    with tabs[0]:
        st.dataframe(ui.dimension_table(summary), hide_index=True, width="stretch")
        st.plotly_chart(ui.dimension_chart(summary), width="stretch", theme="streamlit")
    with tabs[1]:
        ui.assertion_results_view(session.assertion_results, scenario, session, key=f"hist_{evaluation_id}")
    with tabs[2]:
        if not session.human_reviews:
            st.info("No human review was recorded for this session.")
        st.caption("Human ratings are subjective assessments.")
        for dim, review in session.human_reviews.items():
            with st.container(border=True):
                st.markdown(
                    f"**{ui.dimension_label(dim)}** — {review.rating}/4 "
                    f"({HUMAN_RATING_LABELS[review.rating]}) · {review.reviewer or 'unnamed reviewer'} · "
                    f"{ui.fmt_time(review.reviewed_at)}"
                )
                for label, text in (
                    ("Reviewer notes", review.reviewer_notes),
                    ("Evidence notes", review.evidence_notes),
                    ("Explanation", review.explanation),
                ):
                    st.markdown(f"*{label}:* {text or '—'}")
    with tabs[3]:
        for turn in scenario.response_turns:
            st.markdown(f"**Turn {turn.order}** — {turn.user_message}")
            text = session.provided_response(turn.turn_id)
            if text:
                st.code(text, language=None, wrap_lines=True)
            else:
                st.caption("No response provided.")
    with tabs[4]:
        export_buttons(session, scenario, key=f"hist_{evaluation_id}")
        st.divider()
        if st.button("Delete evaluation…", icon=":material/delete:", key=f"hist_delete_{evaluation_id}"):
            _confirm_delete(evaluation_id)
