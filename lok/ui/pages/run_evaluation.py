"""Run Evaluation: start or resume a session, enter responses, run assertions, review, complete."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lok.domain.enums import Dimension
from lok.domain.models import EvaluationSession, HumanReview, Scenario, build_fact_history
from lok.domain.scoring import HUMAN_RATING_LABELS
from lok.services import reporting_service as reporting
from lok.services.evaluation_service import EvaluationIncompleteError, EvaluationInputError
from lok.storage.evaluation_repository import EvaluationNotFoundError
from lok.ui import components as ui
from lok.ui import state

EVENT_LABELS = {
    "initial_information": "Initial information",
    "valid_correction": "Valid correction",
    "invalid_correction": "Invalid / unverified correction",
    "follow_up": "Follow-up",
    "verification_request": "Verification request",
}


def render() -> None:
    services = state.services()
    active_id = st.session_state.get(state.ACTIVE_EVALUATION)
    if active_id:
        try:
            session = services.evaluations.get(active_id)
        except EvaluationNotFoundError:
            st.session_state.pop(state.ACTIVE_EVALUATION, None)
            st.warning("The selected evaluation no longer exists.")
        else:
            _workspace(session)
            return
    ui.page_header(
        "Run Evaluation",
        "Start a new evaluation session or resume an incomplete one. You run the conversation with the "
        "AI assistant yourself and paste each reply; LOK never contacts an AI service.",
        kicker="Evaluate",
    )
    left, right = st.columns([3, 2], gap="large")
    with left:
        _start_form()
    with right:
        _resume_list()


# --------------------------------------------------------------------------- #
# Start / resume
# --------------------------------------------------------------------------- #


def _start_form() -> None:
    services = state.services()
    scenarios = services.scenarios.list_scenarios()
    if not scenarios:
        st.info("No scenarios are available. Create one in the Scenario Builder.")
        return
    ids = [s.scenario_id for s in scenarios]
    by_id = {s.scenario_id: s for s in scenarios}
    preselect = st.session_state.get(state.START_SCENARIO)
    with st.container(border=True):
        st.subheader("New evaluation")
        scenario_id = st.selectbox(
            "Scenario",
            ids,
            index=ids.index(preselect) if preselect in ids else 0,
            format_func=lambda i: f"{by_id[i].title} · v{by_id[i].version} · {by_id[i].category}",
            key="run_start_scenario",
        )
        chosen = by_id[scenario_id]
        st.caption(
            f"{chosen.description}  \n{len(chosen.response_turns)} responses required · "
            f"{len(chosen.assertions)} assertions · dimensions: "
            f"{', '.join(ui.dimension_label(d) for d in chosen.dimensions)}"
        )
        known_systems = sorted({row["ai_system"] for row in services.evaluations.list_summaries()})
        with st.form("run_start_form", border=False):
            c1, c2 = st.columns(2)
            ai_system = c1.text_input(
                "AI system name",
                placeholder="e.g. Assistant A",
                help="Free text. " + (f"Used before: {', '.join(known_systems)}" if known_systems else ""),
            )
            model = c2.text_input("Model / version label", placeholder="e.g. 2026-11 release")
            notes = st.text_area(
                "Notes (optional)", height=80, placeholder="Settings, temperature, interface used, …"
            )
            submitted = st.form_submit_button("Start evaluation", type="primary")
        if submitted:
            try:
                session = services.evaluations.start(scenario_id, ai_system, model, notes)
            except EvaluationInputError as exc:
                st.error(str(exc))
            else:
                st.session_state.pop(state.START_SCENARIO, None)
                st.session_state[state.ACTIVE_EVALUATION] = session.evaluation_id
                state.flash(f"Evaluation {session.evaluation_id} created as a draft.")
                st.rerun()


def _resume_list() -> None:
    services = state.services()
    incomplete = [r for r in services.evaluations.list_summaries() if r["status"] != "completed"]
    with st.container(border=True):
        st.subheader("Resume an incomplete evaluation")
        if not incomplete:
            st.caption("No draft or in-progress evaluations.")
            return
        for row in incomplete[:12]:
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(
                f"**{row['ai_system']}** · {row['model_label']} {ui.SESSION_BADGE[row['status']]}  \n"
                f"<span class='lok-muted'>{row['scenario_title']} · {row['evaluation_id']} · "
                f"{ui.fmt_time(row['updated_at'])}</span>",
                unsafe_allow_html=True,
            )
            if c2.button("Resume", key=f"resume_{row['evaluation_id']}", width="stretch"):
                st.session_state[state.ACTIVE_EVALUATION] = row["evaluation_id"]
                st.rerun()


# --------------------------------------------------------------------------- #
# Workspace
# --------------------------------------------------------------------------- #


def _drafts(session: EvaluationSession) -> dict[str, str]:
    """Unsaved response drafts for a session, kept in session state across page switches."""
    store = st.session_state.setdefault(state.RESPONSE_DRAFTS, {})
    if session.evaluation_id not in store:
        store[session.evaluation_id] = dict(session.responses)
    return store[session.evaluation_id]


def _cleaned(responses: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in responses.items() if v and v.strip()}


def _workspace(session: EvaluationSession) -> None:
    services = state.services()
    scenario = services.evaluations.scenario_for(session)
    summary = services.evaluations.summarize(session)
    drafts = _drafts(session)
    unsaved = _cleaned(drafts) != session.responses

    ui.page_header(
        f"{session.ai_system} · {session.model_label}",
        f"Evaluation <code>{session.evaluation_id}</code> on <b>{scenario.title}</b> "
        f"(scenario v{scenario.version}, pinned). Created {ui.fmt_time(session.created_at)} UTC.",
        kicker="Run evaluation",
    )
    c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="center")
    missing = services.evaluations.missing_responses(session, scenario)
    c1.markdown(
        f"{ui.SESSION_BADGE[session.status]} &nbsp; "
        f"{len(scenario.response_turns) - len(missing)} of {len(scenario.response_turns)} responses saved · "
        + ("assertions run " + ui.fmt_time(session.evaluated_at) if session.has_run else "assertions not run")
        + (" · :orange-badge[unsaved response changes]" if unsaved else "")
    )
    if c2.button("History view", width="stretch"):
        state.go("history", **{state.HISTORY_SELECTED: session.evaluation_id})
    if c3.button("Close session", width="stretch", help="Unsaved drafts are kept until you leave the app."):
        st.session_state.pop(state.ACTIVE_EVALUATION, None)
        st.rerun()

    tabs = st.tabs(["1 · Responses", "2 · Results & evidence", "3 · Human review", "4 · Complete & export"])
    with tabs[0]:
        _responses_tab(session, scenario, drafts, unsaved)
    with tabs[1]:
        _results_tab(session, scenario, summary)
    with tabs[2]:
        _review_tab(session, summary)
    with tabs[3]:
        _complete_tab(session, scenario, summary, missing, unsaved)


def _scenario_briefing(scenario: Scenario) -> None:
    with st.expander("Scenario briefing: objective, facts and corrections", expanded=False):
        st.markdown(f"**Objective:** {scenario.objective or '—'}")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Fact": f.name,
                        "ID": f.fact_id,
                        "Initial": f.initial_value,
                        "Expected current": f.expected_current_value,
                        "Status": f.status,
                        "History": " → ".join(
                            e.value + ("" if e.accepted else " (not accepted)")
                            for e in build_fact_history(scenario, f.fact_id)
                        ),
                    }
                    for f in scenario.facts
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        for c in scenario.corrections:
            authority = "authoritative" if c.is_authoritative else "not authoritative"
            st.markdown(
                f"- **{c.correction_id}** ({c.correction_type}, {authority}) on `{c.target_fact_id}`: "
                f"{c.original_value} → {c.proposed_value}. *Expected:* {c.expected_behavior}"
            )


def _sync_draft(eid: str, turn_id: str, key: str) -> None:
    st.session_state[state.RESPONSE_DRAFTS][eid][turn_id] = st.session_state[key]


def _responses_tab(
    session: EvaluationSession, scenario: Scenario, drafts: dict[str, str], unsaved: bool
) -> None:
    services = state.services()
    st.markdown(
        "Send each user message to the assistant in order, in a single conversation, and paste the "
        "assistant's reply below. Leave a field empty if you have no reply yet — it stays "
        "**not evaluated**, never passed."
    )
    _scenario_briefing(scenario)
    for turn in scenario.ordered_turns:
        with st.container(border=True):
            st.html(
                f'<div class="lok-turn-meta">Turn {turn.order} · {EVENT_LABELS.get(turn.event_type, turn.event_type)}'
                f"{' · correction ' + turn.correction_id if turn.correction_id else ''}</div>"
            )
            with st.chat_message("user"):
                st.markdown(turn.user_message)
                if turn.notes:
                    st.caption(turn.notes)
            if turn.requires_response:
                key = f"resp_{session.evaluation_id}_{turn.turn_id}"
                if key not in st.session_state:
                    st.session_state[key] = drafts.get(turn.turn_id, "")
                with st.chat_message("assistant"):
                    st.text_area(
                        f"Assistant response to turn {turn.order}",
                        key=key,
                        height=110,
                        label_visibility="collapsed",
                        placeholder="Paste the assistant's reply…",
                        on_change=_sync_draft,
                        args=(session.evaluation_id, turn.turn_id, key),
                    )
            else:
                st.caption("No assistant response is required for this turn.")

    if unsaved:
        st.warning(
            "You have unsaved response changes. Saving replaces the stored responses; any existing "
            "automated results are cleared and must be re-run."
        )
    c1, c2, _ = st.columns([1, 1, 3])
    save = c1.button("Save draft", width="stretch")
    run = c2.button("Save & run evaluation", type="primary", width="stretch")
    if save or run:
        try:
            services.evaluations.save_responses(session.evaluation_id, dict(drafts))
            if run:
                _, summary = services.evaluations.run_evaluation(session.evaluation_id)
                state.flash(
                    f"Evaluation run: {summary.passed} passed, {summary.failed} failed, "
                    f"{summary.not_evaluated} not evaluated, {summary.errors} errors. "
                    "See “Results & evidence”."
                )
            else:
                state.flash("Responses saved as draft.")
        except EvaluationInputError as exc:
            st.error(str(exc))
            return
        st.rerun()


def _results_tab(session: EvaluationSession, scenario: Scenario, summary) -> None:
    services = state.services()
    if not session.has_run:
        st.info(
            "Automated assertions have not been run for the stored responses. Save the responses and "
            "run the evaluation on the Responses tab."
            + (" Scores below are based on human review only." if session.human_reviews else "")
        )
        if session.responses and st.button("Run evaluation now", type="primary"):
            services.evaluations.run_evaluation(session.evaluation_id)
            st.rerun()
    ui.score_overview(summary, session.has_run)
    left, right = st.columns([3, 2])
    with left:
        st.dataframe(ui.dimension_table(summary), hide_index=True, width="stretch")
    with right:
        st.plotly_chart(ui.dimension_chart(summary), width="stretch", theme="streamlit")
    st.subheader("Assertion evidence")
    st.caption(
        "Each assertion verifies one explicitly defined text condition. A pass shows that the "
        "condition holds, not that the assistant understood the conversation."
    )
    ui.assertion_results_view(
        session.assertion_results, scenario, session, key=f"run_{session.evaluation_id}"
    )
    if session.has_run and st.button("Verify reproducibility"):
        report = services.evaluations.verify_reproducibility(session.evaluation_id)
        if report.reproducible:
            st.success(
                f"Re-executed {report.checked} assertions against scenario v{scenario.version}: "
                "all stored results reproduced exactly."
            )
        else:
            st.error("Stored results differ from a fresh run: " + "; ".join(report.differences))


def _review_tab(session: EvaluationSession, summary) -> None:
    services = state.services()
    st.markdown(
        "Human review is **optional** and **subjective**. Ratings are shown separately from "
        "automated results and are combined as 70 % automated + 30 % human where both exist."
    )
    st.caption(" · ".join(f"{k} = {v}" for k, v in HUMAN_RATING_LABELS.items()))
    for dimension in Dimension:
        existing = session.human_reviews.get(dimension.value)
        auto = summary.dimension_scores[dimension.value]
        title = f"{dimension.label} — " + (f"rated {existing.rating}/4" if existing else "not reviewed")
        with st.expander(title, expanded=False):
            st.caption(
                f"{dimension.summary} Automated: {ui.fmt_score(auto.automated_score)} "
                f"({auto.passed} passed, {auto.failed} failed)."
            )
            with st.form(f"review_{session.evaluation_id}_{dimension.value}", border=False):
                rating = st.radio(
                    "Rating",
                    list(HUMAN_RATING_LABELS),
                    horizontal=True,
                    index=existing.rating if existing else None,
                    format_func=ui.human_rating_label,
                )
                reviewer = st.text_input("Reviewer", value=existing.reviewer if existing else "")
                notes = st.text_area(
                    "Reviewer notes", value=existing.reviewer_notes if existing else "", height=70
                )
                evidence = st.text_area(
                    "Evidence notes (quote turns or passages)",
                    value=existing.evidence_notes if existing else "",
                    height=70,
                )
                explanation = st.text_area(
                    "Explanation (optional)", value=existing.explanation if existing else "", height=70
                )
                c1, c2 = st.columns([1, 4])
                save = c1.form_submit_button("Save review", type="primary")
                remove = c2.form_submit_button("Remove review", disabled=existing is None)
            if save:
                if rating is None:
                    st.error("Select a rating before saving.")
                else:
                    try:
                        services.evaluations.save_human_review(
                            session.evaluation_id,
                            HumanReview(
                                dimension.value,
                                int(rating),
                                reviewer.strip(),
                                notes.strip(),
                                evidence.strip(),
                                explanation.strip(),
                            ),
                        )
                    except EvaluationInputError as exc:
                        st.error(str(exc))
                    else:
                        state.flash(f"Human review saved for {dimension.label}.")
                        st.rerun()
            if remove:
                services.evaluations.remove_human_review(session.evaluation_id, dimension.value)
                state.flash(f"Human review removed for {dimension.label}.")
                st.rerun()
            if existing:
                st.caption(f"Last reviewed {ui.fmt_time(existing.reviewed_at)} UTC")


@st.dialog("Delete evaluation")
def _confirm_delete(evaluation_id: str) -> None:
    st.write(
        f"Permanently delete evaluation **{evaluation_id}** with all responses, results and reviews? "
        "This cannot be undone."
    )
    c1, c2 = st.columns(2)
    if c1.button("Delete permanently", type="primary", width="stretch"):
        state.services().evaluations.delete(evaluation_id)
        st.session_state.pop(state.ACTIVE_EVALUATION, None)
        st.session_state.get(state.RESPONSE_DRAFTS, {}).pop(evaluation_id, None)
        state.flash(f"Evaluation {evaluation_id} deleted.")
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


def _complete_tab(session: EvaluationSession, scenario: Scenario, summary, missing, unsaved: bool) -> None:
    services = state.services()
    st.subheader("Completion checklist")
    checks = [
        (
            not missing,
            f"All {len(scenario.response_turns)} required responses saved"
            + (f" — missing turn(s) {', '.join(str(t.order) for t in missing)}" if missing else ""),
        ),
        (session.has_run, "Automated assertions run on the saved responses"),
        (not unsaved, "No unsaved response changes"),
    ]
    for ok, text in checks:
        st.markdown(f"{':material/check_circle:' if ok else ':material/radio_button_unchecked:'} {text}")
    st.markdown(f":material/info: Human review: {len(session.human_reviews)} of 5 dimensions (optional)")

    if session.status == "completed":
        st.success(f"Completed {ui.fmt_time(session.completed_at)} UTC.")
        if st.button("Reopen evaluation"):
            services.evaluations.reopen(session.evaluation_id)
            st.rerun()
    elif st.button("Mark as completed", type="primary", disabled=not all(ok for ok, _ in checks)):
        try:
            services.evaluations.complete(session.evaluation_id)
        except EvaluationIncompleteError as exc:
            st.error(str(exc))
        else:
            state.flash("Evaluation marked as completed.")
            st.rerun()

    with st.expander("Edit session details"), st.form(f"details_{session.evaluation_id}", border=False):
        ai = st.text_input("AI system name", value=session.ai_system)
        model = st.text_input("Model / version label", value=session.model_label)
        notes = st.text_area("Notes", value=session.notes)
        if st.form_submit_button("Save details"):
            try:
                services.evaluations.update_details(session.evaluation_id, ai, model, notes)
            except EvaluationInputError as exc:
                st.error(str(exc))
            else:
                state.flash("Session details saved.")
                st.rerun()

    st.subheader("Export")
    export_buttons(session, scenario, key=f"run_{session.evaluation_id}")
    st.divider()
    if st.button("Delete evaluation…", icon=":material/delete:"):
        _confirm_delete(session.evaluation_id)


def export_buttons(session: EvaluationSession, scenario: Scenario, key: str) -> None:
    """Download buttons for all report formats (shared with the History page)."""
    try:
        json_doc = reporting.to_json(session, scenario)
        markdown = reporting.to_markdown(session, scenario)
        assertions_csv = reporting.assertions_csv(session, scenario)
        dimensions_csv = reporting.dimensions_csv(session, scenario)
    except reporting.ReportError as exc:
        st.error(f"Report cannot be generated: {exc}")
        return
    base = f"lok_{session.evaluation_id}"
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button(
        "JSON report",
        json_doc,
        f"{base}.json",
        "application/json",
        key=f"{key}_json",
        width="stretch",
    )
    c2.download_button(
        "Markdown report", markdown, f"{base}.md", "text/markdown", key=f"{key}_md", width="stretch"
    )
    c3.download_button(
        "Assertions CSV",
        assertions_csv,
        f"{base}_assertions.csv",
        "text/csv",
        key=f"{key}_csv_a",
        width="stretch",
    )
    c4.download_button(
        "Dimensions CSV",
        dimensions_csv,
        f"{base}_dimensions.csv",
        "text/csv",
        key=f"{key}_csv_d",
        width="stretch",
    )
