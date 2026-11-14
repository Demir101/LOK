"""Scenario Builder: create and edit scenarios with validation before saving.

The draft lives in ``st.session_state[BUILDER_DRAFT]`` as plain dictionaries, so it
survives reruns and page switches. Every table edit is applied to the draft
immediately through the editor's ``on_change`` callback; nothing is discarded when
validation fails. Editing an existing scenario always saves a *new version*.
"""

from __future__ import annotations

import copy
import math
import uuid
from typing import Any

import pandas as pd
import streamlit as st

from lok.domain.enums import CorrectionType, Difficulty, Dimension, EventType, FactStatus, Operator
from lok.domain.models import Scenario
from lok.domain.validation import (
    ID_RULE,
    ScenarioValidationError,
    ValidationIssue,
    parse_scenario_dict,
    validate_scenario,
)
from lok.services.scenario_service import DuplicateScenarioError, ReadOnlyScenarioError
from lok.storage.scenario_repository import ScenarioNotFoundError
from lok.ui import components as ui
from lok.ui import state
from lok.ui.pages.scenario_library import render_assertions, render_corrections, render_facts, render_turns

SECTIONS: dict[str, list[str]] = {
    "facts": ["fact_id", "name", "initial_value", "expected_current_value", "status", "description"],
    "turns": [
        "order",
        "turn_id",
        "event_type",
        "user_message",
        "requires_response",
        "correction_id",
        "notes",
    ],
    "corrections": [
        "correction_id",
        "target_fact_id",
        "original_value",
        "proposed_value",
        "correction_type",
        "is_authoritative",
        "turn_id",
        "expected_behavior",
        "explanation",
    ],
    "dependencies": ["source_fact_id", "target_fact_id", "explanation"],
    "assertions": [
        "assertion_id",
        "turn_id",
        "dimension",
        "description",
        "operator",
        "expected_value",
        "weight",
        "case_sensitive",
        "boundary_match",
        "explanation",
    ],
    "expected_outcomes": ["outcome_id", "description", "dimension", "turn_id"],
}
DEFAULTS: dict[str, dict[str, Any]] = {
    "facts": {"status": "active", "description": ""},
    "turns": {"event_type": "follow_up", "requires_response": True, "correction_id": "", "notes": ""},
    "corrections": {"correction_type": "valid", "is_authoritative": True, "explanation": ""},
    "dependencies": {"explanation": ""},
    "assertions": {
        "dimension": "correction_accuracy",
        "operator": "contains",
        "weight": 1.0,
        "case_sensitive": False,
        "boundary_match": True,
        "explanation": "",
    },
    "expected_outcomes": {"dimension": "", "turn_id": ""},
}
BOOL_FIELDS = {"requires_response", "is_authoritative", "case_sensitive", "boundary_match"}
OPTIONAL_REFS = {
    ("turns", "correction_id"),
    ("expected_outcomes", "dimension"),
    ("expected_outcomes", "turn_id"),
}

TEMPLATE: dict[str, Any] = {
    "scenario_id": "",
    "title": "",
    "description": "",
    "objective": "",
    "category": "",
    "difficulty": "medium",
    "tags": [],
    "facts": [
        {
            "fact_id": "meeting_date",
            "name": "Meeting date",
            "initial_value": "May 15",
            "expected_current_value": "May 22",
            "status": "corrected",
            "description": "",
        },
        {
            "fact_id": "location",
            "name": "Location",
            "initial_value": "Berlin",
            "expected_current_value": "Berlin",
            "status": "active",
            "description": "",
        },
    ],
    "turns": [
        {
            "order": 1,
            "turn_id": "t1",
            "event_type": "initial_information",
            "requires_response": True,
            "user_message": "The meeting is on May 15 in Berlin. Please confirm.",
            "correction_id": "",
            "notes": "",
        },
        {
            "order": 2,
            "turn_id": "t2",
            "event_type": "valid_correction",
            "requires_response": True,
            "user_message": "Update: the meeting is now on May 22.",
            "correction_id": "c1",
            "notes": "",
        },
        {
            "order": 3,
            "turn_id": "t3",
            "event_type": "follow_up",
            "requires_response": True,
            "user_message": "Summarize the meeting date and location.",
            "correction_id": "",
            "notes": "",
        },
    ],
    "corrections": [
        {
            "correction_id": "c1",
            "target_fact_id": "meeting_date",
            "original_value": "May 15",
            "proposed_value": "May 22",
            "correction_type": "valid",
            "is_authoritative": True,
            "turn_id": "t2",
            "expected_behavior": "Adopt May 22 as the meeting date.",
            "explanation": "",
        },
    ],
    "dependencies": [],
    "assertions": [
        {
            "assertion_id": "a1",
            "turn_id": "t3",
            "dimension": "correction_accuracy",
            "description": "Uses the corrected date",
            "operator": "contains",
            "expected_value": "May 22",
            "weight": 1.0,
            "case_sensitive": False,
            "boundary_match": True,
            "explanation": "",
        },
        {
            "assertion_id": "a2",
            "turn_id": "t3",
            "dimension": "context_preservation",
            "description": "Keeps the location",
            "operator": "contains",
            "expected_value": "Berlin",
            "weight": 1.0,
            "case_sensitive": False,
            "boundary_match": True,
            "explanation": "",
        },
        {
            "assertion_id": "a3",
            "turn_id": "t3",
            "dimension": "repeated_error_detection",
            "description": "Does not repeat the old date",
            "operator": "does_not_contain",
            "expected_value": "May 15",
            "weight": 1.0,
            "case_sensitive": False,
            "boundary_match": True,
            "explanation": "",
        },
    ],
    "expected_outcomes": [
        {"outcome_id": "o1", "description": "Meeting on May 22 in Berlin.", "dimension": "", "turn_id": "t3"}
    ],
}


# --------------------------------------------------------------------------- #
# Draft handling
# --------------------------------------------------------------------------- #


def _empty_data() -> dict[str, Any]:
    data = {key: copy.deepcopy(value) for key, value in TEMPLATE.items() if not isinstance(value, list)}
    data["tags"] = []
    for section in SECTIONS:
        data[section] = []
    return data


def _new_draft(data: dict[str, Any], mode: str, base: Scenario | None = None) -> dict[str, Any]:
    return {
        "mode": mode,
        "base_id": base.scenario_id if base else None,
        "base_version": base.version if base else None,
        "data": data,
        "nonce": 0,
        "dirty": False,
        "saved_message": None,
        "uid": uuid.uuid4().hex[:8],
    }


def _draft_from_scenario(s: Scenario) -> dict[str, Any]:
    raw = s.to_dict()
    data = {
        k: raw[k]
        for k in ("scenario_id", "title", "description", "objective", "category", "difficulty", "tags")
    }
    for section, columns in SECTIONS.items():
        data[section] = [
            {c: ("" if item.get(c) is None else item.get(c)) for c in columns} for item in raw[section]
        ]
    return _new_draft(data, "edit", s)


def _draft() -> dict[str, Any] | None:
    return st.session_state.get(state.BUILDER_DRAFT)


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def _apply_editor_delta(section: str, key: str) -> None:
    """Apply a data_editor delta to the draft, then refresh the editor key."""
    draft = st.session_state[state.BUILDER_DRAFT]
    delta = st.session_state.get(key) or {}
    rows = [dict(row) for row in draft["data"][section]]
    for index, changes in delta.get("edited_rows", {}).items():
        idx = int(index)
        if 0 <= idx < len(rows):
            rows[idx].update({k: _clean(v) for k, v in changes.items()})
    for index in sorted((int(i) for i in delta.get("deleted_rows", [])), reverse=True):
        if 0 <= index < len(rows):
            del rows[index]
    for added in delta.get("added_rows", []):
        row = {column: "" for column in SECTIONS[section]}
        row.update(DEFAULTS[section])
        row.update({k: _clean(v) for k, v in added.items() if _clean(v) is not None})
        if section == "turns" and row.get("order") in ("", None):
            orders = [r.get("order") for r in rows if isinstance(r.get("order"), (int, float))]
            row["order"] = int(max(orders, default=0)) + 1
        rows.append(row)
    if section == "turns":
        rows.sort(key=lambda r: r.get("order") if isinstance(r.get("order"), (int, float)) else 10**9)
    draft["data"][section] = rows
    draft["nonce"] += 1
    draft["dirty"] = True


def _bind_field(field: str, key: str, transform=None) -> None:
    draft = st.session_state[state.BUILDER_DRAFT]
    value = st.session_state[key]
    draft["data"][field] = transform(value) if transform else value
    draft["dirty"] = True


def _coerce_rows(section: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item: dict[str, Any] = {}
        for column in SECTIONS[section]:
            value = _clean(row.get(column))
            if column in BOOL_FIELDS:
                item[column] = (
                    bool(value) if value is not None else bool(DEFAULTS[section].get(column, False))
                )
            elif column == "order":
                try:
                    item[column] = int(value)
                except (TypeError, ValueError):
                    item[column] = value
            elif column == "weight":
                try:
                    item[column] = float(value)
                except (TypeError, ValueError):
                    item[column] = value
            else:
                text = "" if value is None else str(value).strip()
                item[column] = None if (section, column) in OPTIONAL_REFS and not text else text
        result.append(item)
    return result


def build_scenario(data: dict[str, Any]) -> tuple[Scenario | None, list[ValidationIssue]]:
    """Convert draft data to a Scenario and return all validation issues."""
    raw = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items() if k not in SECTIONS}
    for section, rows in ((s, data.get(s, [])) for s in SECTIONS):
        raw[section] = _coerce_rows(section, rows)
    try:
        scenario = parse_scenario_dict(raw)
    except ScenarioValidationError as exc:
        return None, exc.issues
    return scenario, validate_scenario(scenario)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #


def render() -> None:
    ui.page_header(
        "Scenario Builder",
        "Define facts, the scripted conversation, correction events, dependencies and assertions. "
        "Every save is validated; edits to an existing scenario create a new immutable version.",
        kicker="Scenarios",
    )
    if not _handle_load_request():
        return
    draft = _draft()
    if draft is None:
        _start_screen()
        return
    _editor(draft)


def _handle_load_request() -> bool:
    request = st.session_state.get(state.BUILDER_LOAD_REQUEST)
    if not request:
        return True
    services = state.services()
    draft = _draft()
    if draft and draft.get("dirty") and draft.get("base_id") != request:
        st.warning(f"You have unsaved changes in the current draft. Load `{request}` and discard them?")
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Discard draft and load", type="primary"):
            st.session_state[state.BUILDER_DRAFT] = None
            st.rerun()
        if c2.button("Keep current draft"):
            st.session_state.pop(state.BUILDER_LOAD_REQUEST, None)
            st.rerun()
        return False
    st.session_state.pop(state.BUILDER_LOAD_REQUEST, None)
    try:
        scenario = services.scenarios.get(request)
    except ScenarioNotFoundError:
        st.error(f"Scenario '{request}' does not exist.")
        return True
    if scenario.is_demo:
        st.error("Demo scenarios are read-only. Duplicate it in the Scenario Library first.")
        return True
    if not (draft and draft.get("dirty") and draft.get("base_id") == request):
        st.session_state[state.BUILDER_DRAFT] = _draft_from_scenario(scenario)
    return True


def _start_screen() -> None:
    services = state.services()
    customs = [s for s in services.scenarios.list_scenarios() if not s.is_demo]
    c1, c2, c3 = st.columns(3)
    with c1, st.container(border=True):
        st.markdown("#### Start from a template")
        st.caption("A small working example (one valid correction, three assertions) to adapt.")
        if st.button("Use template", type="primary", width="stretch"):
            st.session_state[state.BUILDER_DRAFT] = _new_draft(copy.deepcopy(TEMPLATE), "new")
            st.rerun()
    with c2, st.container(border=True):
        st.markdown("#### Start blank")
        st.caption("Empty scenario; add every fact, turn and assertion yourself.")
        if st.button("Start blank", width="stretch"):
            st.session_state[state.BUILDER_DRAFT] = _new_draft(_empty_data(), "new")
            st.rerun()
    with c3, st.container(border=True):
        st.markdown("#### Edit a custom scenario")
        if not customs:
            st.caption("No custom scenarios yet. Duplicate a demo scenario in the library to edit a copy.")
        else:
            choice = st.selectbox(
                "Scenario",
                [s.scenario_id for s in customs],
                key="builder_pick",
                format_func=lambda i: next(s.title for s in customs if s.scenario_id == i),
            )
            if st.button("Load for editing", width="stretch"):
                st.session_state[state.BUILDER_DRAFT] = _draft_from_scenario(services.scenarios.get(choice))
                st.rerun()


@st.dialog("Discard draft")
def _confirm_discard() -> None:
    st.write("Discard the current draft? Unsaved changes will be lost. Saved scenarios are not affected.")
    c1, c2 = st.columns(2)
    if c1.button("Discard", type="primary", width="stretch"):
        st.session_state[state.BUILDER_DRAFT] = None
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


def _editor(draft: dict[str, Any]) -> None:
    data = draft["data"]
    nonce = f"{draft['uid']}_{draft['nonce']}"
    mode_text = (
        f"Editing `{draft['base_id']}` (based on v{draft['base_version']}; saving creates a new version)"
        if draft["mode"] == "edit"
        else "New scenario"
    )
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    c1.markdown(
        f"**{mode_text}** "
        + (":orange-badge[unsaved changes]" if draft["dirty"] else ":green-badge[no unsaved changes]")
    )
    if c2.button("Discard draft", width="stretch"):
        _confirm_discard()
    if draft.get("saved_message"):
        st.success(draft["saved_message"])

    scenario, issues = build_scenario(data)
    errors = [i for i in issues if i.severity == "error"]
    tabs = st.tabs(
        [
            "Basics",
            "Facts",
            "Conversation",
            "Corrections",
            "Dependencies",
            "Assertions",
            "Outcomes",
            f"Validate & save ({len(errors)} error{'s' if len(errors) != 1 else ''})",
        ]
    )
    with tabs[0]:
        _basics(draft, nonce)
    fact_ids = [r.get("fact_id") for r in data["facts"] if r.get("fact_id")]
    turn_ids = [r.get("turn_id") for r in data["turns"] if r.get("turn_id")]
    correction_ids = [r.get("correction_id") for r in data["corrections"] if r.get("correction_id")]
    response_turns = [
        r.get("turn_id") for r in data["turns"] if r.get("turn_id") and r.get("requires_response")
    ]
    with tabs[1]:
        st.caption(
            "Facts the conversation tracks. 'Expected current value' is the value an assistant should "
            "use at the end of the conversation."
        )
        _table(
            "facts",
            nonce,
            {
                "fact_id": st.column_config.TextColumn("Fact ID", required=True, help=ID_RULE),
                "name": st.column_config.TextColumn("Name", required=True),
                "initial_value": st.column_config.TextColumn("Initial value", required=True),
                "expected_current_value": st.column_config.TextColumn(
                    "Expected current value", required=True
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status", options=[s.value for s in FactStatus], required=True
                ),
                "description": st.column_config.TextColumn("Description"),
            },
        )
    with tabs[2]:
        st.caption(
            "Ordered user turns. Change the **Order** number to reorder turns (rows re-sort after each "
            "edit). Correction turns must reference a correction event."
        )
        _table(
            "turns",
            nonce,
            {
                "order": st.column_config.NumberColumn("Order", min_value=1, step=1, required=True),
                "turn_id": st.column_config.TextColumn("Turn ID", required=True, help=ID_RULE),
                "event_type": st.column_config.SelectboxColumn(
                    "Event type", options=[e.value for e in EventType], required=True
                ),
                "user_message": st.column_config.TextColumn("User message", required=True, width="large"),
                "requires_response": st.column_config.CheckboxColumn("Needs AI response"),
                "correction_id": st.column_config.SelectboxColumn(
                    "Correction", options=["", *correction_ids]
                ),
                "notes": st.column_config.TextColumn("Notes"),
            },
        )
        if st.button("Renumber turns 1…n in current order"):
            for position, row in enumerate(draft["data"]["turns"], start=1):
                row["order"] = position
            draft["nonce"] += 1
            draft["dirty"] = True
            st.rerun()
    with tabs[3]:
        st.caption(
            "Each correction targets one fact. Valid corrections must be authoritative; invalid and "
            "unverified corrections must not be. The scenario author decides which value is true."
        )
        _table(
            "corrections",
            nonce,
            {
                "correction_id": st.column_config.TextColumn("Correction ID", required=True),
                "target_fact_id": st.column_config.SelectboxColumn(
                    "Target fact", options=fact_ids, required=True
                ),
                "original_value": st.column_config.TextColumn("Original value", required=True),
                "proposed_value": st.column_config.TextColumn("Proposed value", required=True),
                "correction_type": st.column_config.SelectboxColumn(
                    "Type", options=[c.value for c in CorrectionType], required=True
                ),
                "is_authoritative": st.column_config.CheckboxColumn("Authoritative"),
                "turn_id": st.column_config.SelectboxColumn("Turn", options=turn_ids, required=True),
                "expected_behavior": st.column_config.TextColumn(
                    "Expected behaviour", required=True, width="large"
                ),
                "explanation": st.column_config.TextColumn("Explanation"),
            },
        )
    with tabs[4]:
        st.caption("Directed edges: *target depends on source*. Cycles are rejected.")
        _table(
            "dependencies",
            nonce,
            {
                "source_fact_id": st.column_config.SelectboxColumn(
                    "Source fact", options=fact_ids, required=True
                ),
                "target_fact_id": st.column_config.SelectboxColumn(
                    "Dependent fact", options=fact_ids, required=True
                ),
                "explanation": st.column_config.TextColumn("Explanation", width="large"),
            },
        )
        if scenario is not None:
            ui.dependency_graph_view(scenario, key="builder_graph")
    with tabs[5]:
        st.caption(
            "Deterministic checks on single responses. Weight must be > 0. Boundary match prevents "
            "'192.168.1.10' from matching inside '192.168.1.100'."
        )
        _table(
            "assertions",
            nonce,
            {
                "assertion_id": st.column_config.TextColumn("Assertion ID", required=True),
                "turn_id": st.column_config.SelectboxColumn("Turn", options=response_turns, required=True),
                "dimension": st.column_config.SelectboxColumn(
                    "Dimension", options=[d.value for d in Dimension], required=True
                ),
                "description": st.column_config.TextColumn("Description", required=True),
                "operator": st.column_config.SelectboxColumn(
                    "Operator", options=[o.value for o in Operator], required=True
                ),
                "expected_value": st.column_config.TextColumn("Expected value", required=True),
                "weight": st.column_config.NumberColumn("Weight", min_value=0.0, step=0.5, format="%.2f"),
                "case_sensitive": st.column_config.CheckboxColumn("Case-sensitive"),
                "boundary_match": st.column_config.CheckboxColumn("Boundary match"),
                "explanation": st.column_config.TextColumn("Explanation"),
            },
        )
    with tabs[6]:
        _table(
            "expected_outcomes",
            nonce,
            {
                "outcome_id": st.column_config.TextColumn("Outcome ID", required=True),
                "description": st.column_config.TextColumn("Description", required=True, width="large"),
                "dimension": st.column_config.SelectboxColumn(
                    "Dimension", options=["", *[d.value for d in Dimension]]
                ),
                "turn_id": st.column_config.SelectboxColumn("Turn", options=["", *turn_ids]),
            },
        )
    with tabs[7]:
        _validate_and_save(draft, scenario, issues)


def _basics(draft: dict[str, Any], nonce: str) -> None:
    data = draft["data"]

    def text(field: str, label: str, area: bool = False, disabled: bool = False, help_: str | None = None):
        key = f"builder_{field}_{nonce}"
        if key not in st.session_state:
            st.session_state[key] = data.get(field, "")
        widget = st.text_area if area else st.text_input
        widget(label, key=key, on_change=_bind_field, args=(field, key), disabled=disabled, help=help_)

    c1, c2 = st.columns(2)
    with c1:
        text(
            "scenario_id",
            "Scenario ID",
            disabled=draft["mode"] == "edit",
            help_=ID_RULE + (" · The ID cannot change when editing." if draft["mode"] == "edit" else ""),
        )
    with c2:
        text("title", "Title")
    text("description", "Description", area=True)
    text("objective", "Objective", area=True)
    c3, c4, c5 = st.columns([2, 1, 2])
    with c3:
        text("category", "Category", help_="e.g. Calendar scheduling, Server configuration")
    with c4:
        key = f"builder_difficulty_{nonce}"
        options = [d.value for d in Difficulty]
        if key not in st.session_state:
            st.session_state[key] = data.get("difficulty") if data.get("difficulty") in options else "medium"
        st.selectbox("Difficulty", options, key=key, on_change=_bind_field, args=("difficulty", key))
    with c5:
        key = f"builder_tags_{nonce}"
        if key not in st.session_state:
            st.session_state[key] = ", ".join(data.get("tags", []))
        st.text_input(
            "Tags (comma-separated)",
            key=key,
            on_change=_bind_field,
            args=("tags", key, lambda v: [t.strip() for t in v.split(",") if t.strip()]),
        )


def _table(section: str, nonce: str, column_config: dict[str, Any]) -> None:
    rows = st.session_state[state.BUILDER_DRAFT]["data"][section]
    frame = pd.DataFrame(rows, columns=SECTIONS[section])
    key = f"builder_editor_{section}_{nonce}"
    st.data_editor(
        frame,
        key=key,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config=column_config,
        column_order=SECTIONS[section],
        on_change=_apply_editor_delta,
        args=(section, key),
    )
    st.caption(
        f"{len(rows)} row(s). Add rows with the + below the table; select rows and press Delete "
        "to remove them."
    )


def _validate_and_save(
    draft: dict[str, Any], scenario: Scenario | None, issues: list[ValidationIssue]
) -> None:
    services = state.services()
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    if errors:
        st.error(f"{len(errors)} validation error(s). Your draft is kept; fix them and save again.")
        for issue in errors:
            st.markdown(f"- :red[**{issue.location}**] — {issue.message}")
    else:
        st.success("The scenario is valid.")
    for issue in warnings:
        st.warning(f"{issue.location}: {issue.message}")

    if scenario is not None:
        with st.expander("Preview", expanded=not errors):
            st.markdown(f"### {scenario.title or '(untitled)'}")
            st.markdown(scenario.description or "—")
            st.caption(
                "Dimensions covered: "
                + (", ".join(ui.dimension_label(d) for d in scenario.dimensions) or "none")
            )
            render_facts(scenario)
            render_corrections(scenario)
            render_turns(scenario)
            render_assertions(scenario)

    note = ""
    if draft["mode"] == "edit":
        note = st.text_input(
            "Change note for the new version", key="builder_change_note", placeholder="What changed and why?"
        )
    label = "Save as new version" if draft["mode"] == "edit" else "Create scenario"
    if st.button(label, type="primary", disabled=bool(errors) or scenario is None):
        try:
            if draft["mode"] == "edit":
                saved, _ = services.scenarios.update(scenario, note)
            else:
                saved, _ = services.scenarios.create(scenario)
        except (
            ScenarioValidationError,
            DuplicateScenarioError,
            ReadOnlyScenarioError,
            ScenarioNotFoundError,
        ) as exc:
            st.error(str(exc))
            for issue in getattr(exc, "issues", []):
                st.markdown(f"- {issue}")
            return
        new_draft = _draft_from_scenario(saved)
        new_draft["saved_message"] = f"Saved `{saved.scenario_id}` as version {saved.version}."
        st.session_state[state.BUILDER_DRAFT] = new_draft
        st.session_state[state.LIBRARY_SELECTED] = saved.scenario_id
        st.session_state.pop("builder_change_note", None)
        st.rerun()
