"""Scenario Library: browse, filter, inspect, duplicate, delete, import and export scenarios."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lok.domain.enums import Difficulty, Dimension
from lok.domain.models import Scenario, build_fact_history
from lok.services.import_export_service import (
    ScenarioImportError,
    apply_import,
    export_scenarios,
    preview_import,
)
from lok.services.scenario_service import ScenarioFilter, filter_scenarios
from lok.storage.scenario_repository import ScenarioInUseError, ScenarioNotFoundError
from lok.ui import components as ui
from lok.ui import state
from lok.ui.pages.run_evaluation import EVENT_LABELS


def render() -> None:
    services = state.services()
    ui.page_header(
        "Scenario Library",
        "Versioned scenarios with explicit facts, corrections, dependencies and assertions. Demo scenarios "
        "are <b>synthetic examples</b> shipped with LOK and are read-only; duplicate one to edit it.",
        kicker="Scenarios",
    )
    scenarios = services.scenarios.list_scenarios()
    browse, transfer = st.tabs(["Browse", "Import / export"])
    with transfer:
        _import_export(scenarios)
    with browse:
        _browse(scenarios)


def _browse(scenarios: list[Scenario]) -> None:
    services = state.services()
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1.4, 1])
        query = c1.text_input("Search title and description", key="lib_query")
        categories = c2.multiselect("Category", services.scenarios.categories(scenarios), key="lib_cat")
        difficulties = c3.multiselect("Difficulty", [d.value for d in Difficulty], key="lib_diff")
        c4, c5, c6 = st.columns([2, 1.4, 1])
        dims = c4.multiselect(
            "Evaluation dimension",
            [d.value for d in Dimension],
            key="lib_dims",
            format_func=ui.dimension_label,
        )
        tags = c5.multiselect("Tags", services.scenarios.tags(scenarios), key="lib_tags")
        origins = c6.multiselect("Origin", ["demo", "custom"], key="lib_origin")
    shown = filter_scenarios(scenarios, ScenarioFilter(query, categories, difficulties, dims, tags, origins))
    st.caption(f"{len(shown)} of {len(scenarios)} scenarios")
    if not shown:
        st.info("No scenario matches the current filters.")
        return
    table = pd.DataFrame(
        [
            {
                "Title": s.title,
                "Category": s.category,
                "Difficulty": s.difficulty,
                "Dimensions": len(s.dimensions),
                "Turns": len(s.turns),
                "Corrections": len(s.corrections),
                "Assertions": len(s.assertions),
                "Version": f"v{s.version}",
                "Origin": s.origin,
                "ID": s.scenario_id,
            }
            for s in shown
        ]
    )
    event = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="lib_table",
    )
    table_choice = (
        shown[event.selection.rows[0]].scenario_id
        if event and event.selection and event.selection.rows
        else None
    )
    titles = {s.scenario_id: s.title for s in shown}
    selected = ui.synced_picker(
        "Open scenario",
        list(titles),
        state.LIBRARY_SELECTED,
        table_choice,
        lambda i: f"{titles[i]} ({i})",
        key="lib_pick",
    )
    if selected is None:
        st.info("Select a scenario in the table or the picker above to see its details.")
        return
    _details(services.scenarios.get(selected))


@st.dialog("Delete scenario")
def _confirm_delete(scenario: Scenario) -> None:
    st.write(
        f"Permanently delete **{scenario.title}** (`{scenario.scenario_id}`) and all of its versions? "
        "This cannot be undone."
    )
    c1, c2 = st.columns(2)
    if c1.button("Delete permanently", type="primary", width="stretch"):
        try:
            state.services().scenarios.delete(scenario.scenario_id)
        except (ScenarioInUseError, ScenarioNotFoundError, PermissionError) as exc:
            st.error(str(exc))
            return
        st.session_state.pop(state.LIBRARY_SELECTED, None)
        state.flash(f"Scenario {scenario.scenario_id} deleted.")
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Duplicate scenario")
def _duplicate(scenario: Scenario) -> None:
    services = state.services()
    new_id = st.text_input(
        "New scenario ID", value=services.scenarios.suggest_id(f"{scenario.scenario_id}-copy")
    )
    title = st.text_input("Title", value=f"{scenario.title} (copy)")
    open_builder = st.checkbox("Open the copy in the Scenario Builder", value=True)
    if st.button("Create copy", type="primary"):
        try:
            copy_ = services.scenarios.duplicate(scenario.scenario_id, new_id.strip(), title.strip())
        except Exception as exc:
            st.error(str(exc))
            return
        state.flash(f"Created {copy_.scenario_id} (custom, v1).")
        if open_builder:
            state.go("builder", **{state.BUILDER_LOAD_REQUEST: copy_.scenario_id})
        st.session_state[state.LIBRARY_SELECTED] = copy_.scenario_id
        st.rerun()


def _details(s: Scenario) -> None:
    services = state.services()
    st.divider()
    origin = ":blue-badge[synthetic demo · read-only]" if s.is_demo else ":violet-badge[custom]"
    st.subheader(s.title)
    st.markdown(
        f"{origin} :gray-badge[{s.category}] :gray-badge[{s.difficulty}] :gray-badge[v{s.version}] "
        + " ".join(f":gray-badge[#{t}]" for t in s.tags)
    )
    st.markdown(s.description)
    if s.objective:
        st.markdown(f"**Objective:** {s.objective}")
    st.caption(
        "Dimensions: "
        + ", ".join(ui.dimension_label(d) for d in s.dimensions)
        + f" · ID `{s.scenario_id}` · updated {ui.fmt_time(s.updated_at)}"
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    if c1.button("Start evaluation", type="primary", width="stretch"):
        state.go("run", **{state.START_SCENARIO: s.scenario_id, state.ACTIVE_EVALUATION: None})
    if c2.button("Duplicate", width="stretch"):
        _duplicate(s)
    if c3.button(
        "Edit" if not s.is_demo else "Edit (duplicate first)",
        width="stretch",
        disabled=s.is_demo,
        help="Demo scenarios are read-only." if s.is_demo else "Edits are saved as a new version.",
    ):
        state.go("builder", **{state.BUILDER_LOAD_REQUEST: s.scenario_id})
    c4.download_button(
        "Export JSON",
        export_scenarios([s]),
        f"{s.scenario_id}.json",
        "application/json",
        width="stretch",
    )
    if c5.button(
        "Delete",
        width="stretch",
        disabled=s.is_demo,
        help="Demo scenarios cannot be deleted." if s.is_demo else None,
    ):
        _confirm_delete(s)

    tabs = st.tabs(
        [
            "Facts",
            "Corrections",
            "Conversation",
            "Dependency graph",
            "Assertions",
            "Expected outcomes",
            "Versions",
        ]
    )
    with tabs[0]:
        render_facts(s)
    with tabs[1]:
        render_corrections(s)
    with tabs[2]:
        render_turns(s)
    with tabs[3]:
        ui.dependency_graph_view(s, key=f"lib_graph_{s.scenario_id}")
    with tabs[4]:
        render_assertions(s)
    with tabs[5]:
        if not s.expected_outcomes:
            st.caption("No expected outcomes defined.")
        for o in s.expected_outcomes:
            extra = " · ".join(
                x
                for x in (
                    ui.dimension_label(o.dimension) if o.dimension else "",
                    f"turn {o.turn_id}" if o.turn_id else "",
                )
                if x
            )
            st.markdown(f"- **{o.outcome_id}** {o.description}" + (f" _({extra})_" if extra else ""))
    with tabs[6]:
        versions = services.scenarios.versions(s.scenario_id)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Version": f"v{v['version']}",
                        "Created (UTC)": ui.fmt_time(v["created_at"]),
                        "Title": v["title"],
                        "Change note": v["change_note"] or "—",
                        "Evaluations": v["evaluations"],
                    }
                    for v in versions
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption("Versions are immutable. Evaluations stay pinned to the version they were run against.")


def render_facts(s: Scenario) -> None:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ID": f.fact_id,
                    "Fact": f.name,
                    "Initial value": f.initial_value,
                    "Expected current value": f.expected_current_value,
                    "Status": f.status,
                    "Value history": " → ".join(
                        e.value + ("" if e.accepted else " ✗") for e in build_fact_history(s, f.fact_id)
                    ),
                    "Description": f.description or "—",
                }
                for f in s.facts
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "✗ marks proposed values that are invalid or unverified and therefore not accepted. "
        "Historical values are never erased."
    )


def render_corrections(s: Scenario) -> None:
    if not s.corrections:
        st.caption("No correction events.")
        return
    for c in s.corrections:
        with st.container(border=True):
            badge = {
                "valid": ":green-badge[valid]",
                "invalid": ":red-badge[invalid]",
                "unverified": ":orange-badge[unverified]",
            }.get(c.correction_type, c.correction_type)
            st.markdown(
                f"**{c.correction_id}** {badge} {'authoritative' if c.is_authoritative else 'not authoritative'}"
                f" · fact `{c.target_fact_id}` · turn `{c.turn_id}`"
            )
            st.markdown(f"`{c.original_value}` → `{c.proposed_value}`")
            st.markdown(f"*Expected behaviour:* {c.expected_behavior}")
            if c.explanation:
                st.caption(c.explanation)


def render_turns(s: Scenario) -> None:
    for t in s.ordered_turns:
        with st.chat_message("user"):
            st.html(
                f'<div class="lok-turn-meta">Turn {t.order} · {EVENT_LABELS.get(t.event_type, t.event_type)} · '
                f"{'response required' if t.requires_response else 'no response required'}"
                f"{' · ' + t.correction_id if t.correction_id else ''}</div>"
            )
            st.markdown(t.user_message)
            if t.notes:
                st.caption(t.notes)


def render_assertions(s: Scenario) -> None:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ID": a.assertion_id,
                    "Turn": a.turn_id,
                    "Dimension": ui.dimension_label(a.dimension),
                    "Description": a.description,
                    "Operator": a.operator,
                    "Expected value": a.expected_value,
                    "Weight": a.weight,
                    "Case-sensitive": a.case_sensitive,
                    "Boundary match": a.boundary_match,
                    "Explanation": a.explanation or "—",
                }
                for a in s.assertions
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def _import_export(scenarios: list[Scenario]) -> None:
    services = state.services()
    settings = state.settings()
    left, right = st.columns(2, gap="large")
    with left, st.container(border=True):
        st.subheader("Import scenarios")
        st.caption(
            f"JSON in the LOK scenario format (schema version 1), up to "
            f"{settings.max_import_bytes // 1024:,} KiB. The file is only read, never modified."
        )
        upload = st.file_uploader("Scenario file", type=["json"], key="lib_import_file")
        if upload is None:
            return
        data = upload.getvalue()
        preview = preview_import(data, services.scenario_repo, settings.max_import_bytes)
        for error in preview.file_errors:
            st.error(error)
        for c in preview.candidates:
            with st.container(border=True):
                status = (
                    ":red-badge[invalid]"
                    if not c.is_valid
                    else ":orange-badge[exists — new version]"
                    if c.is_conflict
                    else ":green-badge[new]"
                )
                st.markdown(f"{status} **{c.title or '(untitled)'}** `{c.scenario_id or '?'}`")
                for issue in c.errors:
                    st.markdown(f"- :red[{issue}]")
                for issue in c.warnings:
                    st.markdown(f"- :orange[{issue}]")
        if preview.has_errors:
            st.error("Fix the problems above and upload the file again. Nothing has been imported.")
            return
        replace = False
        if preview.conflicts:
            replace = st.checkbox(
                f"Replace {len(preview.conflicts)} existing scenario(s) — the imported definitions are stored "
                "as new versions; older versions and their evaluations are preserved.",
                key="lib_import_replace",
            )
        if st.button("Import", type="primary", disabled=bool(preview.conflicts) and not replace):
            try:
                report = apply_import(preview, services.scenario_repo, replace_existing=replace)
            except ScenarioImportError as exc:
                st.error(str(exc))
                return
            state.flash(
                f"Imported {len(report.created)} new scenario(s) and {len(report.new_versions)} new "
                "version(s)."
            )
            st.rerun()
    with right, st.container(border=True):
        st.subheader("Export scenarios")
        choice = st.multiselect(
            "Scenarios to export (empty = all)", [s.scenario_id for s in scenarios], key="lib_export_choice"
        )
        chosen = [s for s in scenarios if not choice or s.scenario_id in choice]
        st.download_button(
            f"Download {len(chosen)} scenario(s) as JSON",
            export_scenarios(chosen),
            "lok_scenarios.json",
            "application/json",
            type="primary",
        )
        st.caption("Exports contain the latest version of each scenario.")
