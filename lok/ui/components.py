"""Reusable presentation components. No business logic lives here."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lok import PRODUCT_DESCRIPTION, TAGLINE
from lok.domain.dependency_graph import DependencyGraph
from lok.domain.enums import AssertionStatus, Dimension
from lok.domain.models import AssertionResult, EvaluationSession, Scenario, ScoreSummary
from lok.domain.scoring import HUMAN_RATING_LABELS

# Validated categorical palette (dataviz reference instance), fixed order per dimension.
DIMENSION_COLORS: dict[str, str] = {
    Dimension.CORRECTION_ACCURACY: "#2a78d6",
    Dimension.FALSE_CORRECTION_RESISTANCE: "#eb6834",
    Dimension.DEPENDENCY_UPDATES: "#1baf7a",
    Dimension.CONTEXT_PRESERVATION: "#6250d6",
    Dimension.REPEATED_ERROR_DETECTION: "#e87ba4",
}
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
# Reserved status colors — always shown together with a text label.
STATUS_COLORS = {
    AssertionStatus.PASSED: "#0ca30c",
    AssertionStatus.FAILED: "#d03b3b",
    AssertionStatus.NOT_EVALUATED: "#8a8984",
    AssertionStatus.ERROR: "#fab219",
}
STATUS_BADGE = {
    "passed": ":green-badge[:material/check: passed]",
    "failed": ":red-badge[:material/close: failed]",
    "not_evaluated": ":gray-badge[:material/remove: not evaluated]",
    "error": ":orange-badge[:material/warning: error]",
    "not_run": ":gray-badge[:material/schedule: not run]",
}
SESSION_BADGE = {
    "draft": ":gray-badge[draft]",
    "in_progress": ":blue-badge[in progress]",
    "completed": ":green-badge[:material/check: completed]",
}

CSS = """
<style>
:root { --lok-accent: #2a78d6; }
.block-container { padding-top: 2.2rem; max-width: 1240px; }
.lok-kicker { font-size: .74rem; font-weight: 700; letter-spacing: .16em; text-transform: uppercase;
  color: var(--lok-accent); margin-bottom: .15rem; }
.lok-title { font-size: 1.85rem; font-weight: 700; letter-spacing: -.02em; line-height: 1.15; margin: 0; }
.lok-subtitle { opacity: .72; margin: .35rem 0 1.1rem 0; font-size: .98rem; max-width: 52rem; }
.lok-brand { display: flex; flex-direction: column; gap: .1rem; padding: .25rem 0 .5rem 0; }
.lok-brand b { font-size: 1.35rem; letter-spacing: .08em; }
.lok-brand span { font-size: .68rem; letter-spacing: .2em; font-weight: 700; color: var(--lok-accent); }
.lok-brand small { font-size: .72rem; opacity: .65; }
.lok-turn-meta { font-size: .78rem; opacity: .7; margin-bottom: .2rem; }
.lok-muted { opacity: .7; font-size: .88rem; }
div[data-testid="stMetric"] { padding: .25rem .1rem; }
div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
"""


def inject_css() -> None:
    st.html(CSS)


LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.svg"


def sidebar_brand() -> None:
    st.logo(str(LOGO_PATH), size="large")
    with st.sidebar:
        st.html(
            f'<div class="lok-brand"><b>LOK</b><span>{TAGLINE}</span>'
            f"<small>{PRODUCT_DESCRIPTION}</small></div>"
        )


def page_header(title: str, subtitle: str = "", kicker: str = "LOK") -> None:
    st.html(f'<div class="lok-kicker">{kicker}</div><h1 class="lok-title">{title}</h1>')
    if subtitle:
        st.html(f'<p class="lok-subtitle">{subtitle}</p>')


def fmt_score(value: float | None, suffix: str = "") -> str:
    return "Not assessed" if value is None else f"{value:.1f}{suffix}"


def fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"


def fmt_time(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("T", " ")[:16]


def dimension_label(value: str) -> str:
    try:
        return Dimension(value).label
    except ValueError:
        return value


def score_overview(summary: ScoreSummary, has_run: bool) -> None:
    """KPI row: overall score with coverage, and assertion counts."""
    cols = st.columns(6)
    cols[0].metric(
        "Overall score",
        fmt_score(summary.overall_score),
        border=True,
        help="Mean of assessed dimension scores (equal weights). Unassessed dimensions excluded.",
    )
    cols[1].metric(
        "Coverage",
        f"{summary.coverage:.0f}%",
        summary.coverage_label,
        delta_color="off",
        border=True,
        help="Assessed dimensions / 5 × 100.",
    )
    cols[2].metric("Passed", summary.passed if has_run else "—", border=True)
    cols[3].metric("Failed", summary.failed if has_run else "—", border=True)
    cols[4].metric(
        "Not evaluated",
        summary.not_evaluated if has_run else "—",
        border=True,
        help="Missing or empty responses. Excluded from scoring.",
    )
    cols[5].metric(
        "Errors",
        summary.errors if has_run else "—",
        border=True,
        help="Assertions that could not be executed. Excluded from scoring.",
    )
    if summary.coverage < 100:
        st.caption(
            f"{summary.coverage_label}: {summary.assessed_dimensions} of 5 dimensions assessed. "
            "Scores with different coverage are not directly comparable."
        )


def dimension_table(summary: ScoreSummary) -> pd.DataFrame:
    rows = []
    for d in summary.dimension_scores.values():
        rows.append(
            {
                "Dimension": dimension_label(d.dimension),
                "Automated": fmt_score(d.automated_score),
                "Human (0–4)": "—" if d.human_rating is None else f"{d.human_rating} → {d.human_score:.0f}",
                "Dimension score": fmt_score(d.combined_score),
                "Evidence": d.evidence_type,
                "Passed": d.passed,
                "Failed": d.failed,
                "Not evaluated": d.not_evaluated,
                "Errors": d.errors,
            }
        )
    return pd.DataFrame(rows)


def dimension_chart(summary: ScoreSummary, title: str = "Dimension scores") -> go.Figure:
    labels, values, colors, texts = [], [], [], []
    for d in summary.dimension_scores.values():
        labels.append(dimension_label(d.dimension))
        values.append(d.combined_score if d.combined_score is not None else 0)
        colors.append(DIMENSION_COLORS[d.dimension] if d.combined_score is not None else "rgba(0,0,0,0)")
        texts.append(
            f"{d.combined_score:.1f} ({d.evidence_type})" if d.combined_score is not None else "Not assessed"
        )
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={"color": colors, "cornerradius": 4},
            text=texts,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis={"range": [0, 115], "title": "Score (0–100)", "dtick": 25},
        yaxis={"autorange": "reversed"},
        height=300,
        margin={"l": 10, "r": 30, "t": 50, "b": 40},
        showlegend=False,
    )
    return fig


def status_badge(status: str) -> str:
    return STATUS_BADGE.get(status, status)


def assertion_results_view(
    results: Iterable[AssertionResult],
    scenario: Scenario,
    session: EvaluationSession,
    key: str,
) -> None:
    """Filterable list of assertion results with expandable evidence."""
    results = list(results)
    if not results:
        st.info("Automated assertions have not been run for the current responses.")
        return
    c1, c2 = st.columns(2)
    statuses = c1.multiselect(
        "Status",
        [s.value for s in AssertionStatus],
        key=f"{key}_status",
        format_func=lambda s: s.replace("_", " "),
    )
    dims = c2.multiselect(
        "Dimension", [d.value for d in Dimension], key=f"{key}_dim", format_func=dimension_label
    )
    shown = [
        r for r in results if (not statuses or r.status in statuses) and (not dims or r.dimension in dims)
    ]
    st.caption(f"{len(shown)} of {len(results)} assertions")
    for result in shown:
        turn = scenario.turn(result.turn_id)
        header = f"{result.assertion_id} · {result.description or '(no description)'}"
        with st.expander(header):
            st.markdown(
                f"{status_badge(result.status)} &nbsp; **{dimension_label(result.dimension)}** · "
                f"turn {turn.order if turn else '?'} (`{result.turn_id}`) · weight {result.weight:g}"
            )
            st.markdown(f"**Check:** `{result.operator}` → `{result.expected_value}`")
            st.markdown(f"**Evidence:** {result.evidence}")
            if result.actual_excerpt:
                st.markdown("**Response excerpt (normalised whitespace):**")
                st.code(result.actual_excerpt, language=None, wrap_lines=True)
            if result.error_message:
                st.warning(result.error_message)
            full = session.provided_response(result.turn_id)
            if full and st.toggle("Show full response", key=f"{key}_full_{result.assertion_id}"):
                st.code(full, language=None, wrap_lines=True)
            st.caption(f"Evaluated {fmt_time(result.evaluated_at)} UTC")


def graph_for(scenario: Scenario) -> DependencyGraph | None:
    try:
        return DependencyGraph.build(
            list(dict.fromkeys(f.fact_id for f in scenario.facts)),
            [(d.source_fact_id, d.target_fact_id, d.explanation) for d in scenario.dependencies],
            allow_cycles=True,
        )
    except Exception:
        return None


def dependency_graph_view(scenario: Scenario, key: str) -> None:
    graph = graph_for(scenario)
    if graph is None:
        st.warning("The dependency graph cannot be drawn until its references are valid.")
        return
    if not graph.edges:
        st.info("This scenario defines no dependencies between facts.")
        return
    labels = {f.fact_id: f.name for f in scenario.facts}
    corrected = [c.target_fact_id for c in scenario.corrections if c.is_accepted]
    focus = st.selectbox(
        "Highlight the impact of a change to…",
        ["(none)", *graph.nodes],
        key=f"{key}_focus",
        format_func=lambda n: n if n == "(none)" else f"{labels.get(n, n)} ({n})",
    )
    highlight = [focus] if focus != "(none)" else corrected
    affected = [n for h in highlight for n in graph.dependents(h)]
    st.graphviz_chart(graph.to_dot(labels, highlight=highlight, affected=affected))
    st.caption(
        "Arrows point from a fact to the facts that depend on it. Blue: changed fact(s); amber: "
        "facts affected through the scenario-defined graph. Dependencies are author-defined, "
        "not inferred."
    )
    cycle = graph.find_cycle()
    if cycle:
        st.error(f"Circular dependency: {' -> '.join(cycle)}")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Source": labels.get(s, s),
                    "→ Depends on it": labels.get(t, t),
                    "Explanation": graph.explanation(s, t) or "—",
                }
                for s, t in graph.edges
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def human_rating_label(rating: int) -> str:
    return f"{rating} — {HUMAN_RATING_LABELS[rating]}"


def synced_picker(
    label: str,
    options: list[str],
    state_key: str,
    table_choice: str | None,
    format_func,
    key: str,
) -> str | None:
    """A selectbox kept in sync with a table row selection (keyboard-accessible alternative).

    A *new* table selection overrides the picker; otherwise the picker value wins.
    """
    if not options:
        return None
    last_key = f"{key}__last_table"
    if table_choice is not None and table_choice != st.session_state.get(last_key):
        st.session_state[state_key] = table_choice
    st.session_state[last_key] = table_choice
    current = st.session_state.get(state_key)
    if current in options:
        st.session_state[key] = current
    elif st.session_state.get(key) not in options:
        st.session_state[key] = None
    choice = st.selectbox(label, options, key=key, format_func=format_func, placeholder="Choose…")
    st.session_state[state_key] = choice
    return choice


def empty_state(title: str, body: str) -> None:
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.markdown(body)
