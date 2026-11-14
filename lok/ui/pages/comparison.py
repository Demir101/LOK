"""Comparison of two evaluation sessions under strict compatibility rules."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lok.services.comparison_service import compare_sessions
from lok.ui import components as ui
from lok.ui import state


def _delta(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}"


def render() -> None:
    services = state.services()
    ui.page_header(
        "Comparison",
        "Compare two sessions evaluated against the <b>same scenario, same version and identical "
        "assertions</b>. Other combinations are refused, because their scores measure different things.",
        kicker="Evaluate",
    )
    rows = services.evaluations.list_summaries()
    if len(rows) < 2:
        ui.empty_state("Not enough sessions", "At least two evaluation sessions are needed for a comparison.")
        return
    by_id = {r["evaluation_id"]: r for r in rows}
    ids = list(by_id)

    def label(eid: str) -> str:
        r = by_id[eid]
        return (
            f"{r['ai_system']} · {r['model_label']} — {r['scenario_title']} v{r['scenario_version']} "
            f"({r['status'].replace('_', ' ')}, {eid})"
        )

    pre_a = st.session_state.get(state.COMPARE_A)
    c1, c2 = st.columns(2)
    a_id = c1.selectbox(
        "Session A (baseline)",
        ids,
        index=ids.index(pre_a) if pre_a in ids else 0,
        format_func=label,
        key="cmp_a",
    )
    a_row = by_id[a_id]
    compatible = [
        i
        for i in ids
        if i != a_id
        and by_id[i]["scenario_id"] == a_row["scenario_id"]
        and by_id[i]["scenario_version"] == a_row["scenario_version"]
    ]
    others = [i for i in ids if i != a_id and i not in compatible]
    b_options = compatible + others
    pre_b = st.session_state.get(state.COMPARE_B)
    b_id = c2.selectbox(
        "Session B",
        b_options,
        index=b_options.index(pre_b) if pre_b in b_options else 0,
        format_func=lambda i: ("✓ " if i in compatible else "✗ ") + label(i),
        key="cmp_b",
        help="✓ same scenario and version as A · ✗ incompatible",
    )
    st.session_state[state.COMPARE_A], st.session_state[state.COMPARE_B] = a_id, b_id
    if not compatible:
        st.caption("No other session uses the same scenario version as A.")

    a = services.evaluations.get(a_id)
    b = services.evaluations.get(b_id)
    result = compare_sessions(
        a, services.evaluations.scenario_for(a), b, services.evaluations.scenario_for(b)
    )
    if not result.compatible:
        st.error(
            "These sessions cannot be compared directly.\n\n" + "\n".join(f"- {r}" for r in result.reasons),
            icon=":material/block:",
        )
        st.caption("No score differences are shown, to avoid misleading conclusions.")
        return

    st.success(
        "Compatible: same scenario, same version, identical assertion definitions.",
        icon=":material/check_circle:",
    )
    for warning in result.warnings:
        st.warning(warning)
    sa, sb = result.summary_a, result.summary_b
    cols = st.columns(4)
    cols[0].metric("Overall A", ui.fmt_score(sa.overall_score), border=True)
    cols[1].metric(
        "Overall B",
        ui.fmt_score(sb.overall_score),
        None if result.overall_delta is None else f"{result.overall_delta:+.1f}",
        border=True,
    )
    cols[2].metric("Coverage A", f"{sa.coverage:.0f}%", border=True)
    cols[3].metric(
        "Coverage B",
        f"{sb.coverage:.0f}%",
        f"{result.coverage_delta:+.0f} pts",
        delta_color="off",
        border=True,
    )

    table = pd.DataFrame(
        [
            {
                "Dimension": r["label"],
                "Automated A": ui.fmt_score(r["automated_a"]),
                "Automated B": ui.fmt_score(r["automated_b"]),
                "Human A": ui.fmt_score(r["human_a"]),
                "Human B": ui.fmt_score(r["human_b"]),
                "Score A": ui.fmt_score(r["score_a"]),
                "Score B": ui.fmt_score(r["score_b"]),
                "Δ score": _delta(r["score_delta"]),
                "Passed A/B": f"{r['passed_a']} / {r['passed_b']}",
                "Failed A/B": f"{r['failed_a']} / {r['failed_b']}",
            }
            for r in result.dimension_rows
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")
    st.plotly_chart(_chart(result), width="stretch", theme="streamlit")

    st.subheader("Assertion-level differences")
    only_changed = st.toggle("Show only assertions whose result changed", value=True, key="cmp_changed")
    arows = [r for r in result.assertion_rows if r["changed"] or not only_changed]
    if arows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Assertion": r["assertion_id"],
                        "Dimension": ui.dimension_label(r["dimension"]),
                        "Turn": r["turn_id"],
                        "Description": r["description"],
                        "A": r["status_a"].replace("_", " "),
                        "B": r["status_b"].replace("_", " "),
                        "Evidence B": r["evidence_b"],
                    }
                    for r in arows
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No assertion results differ between the two sessions.")

    st.subheader("Repeated-error results")
    re_rows = result.repeated_error_rows
    if not re_rows:
        st.caption("This scenario has no repeated-error assertions.")
    for r in re_rows:
        st.markdown(
            f"- **{r['assertion_id']}** {r['description']}: A {ui.status_badge(r['status_a'])} · "
            f"B {ui.status_badge(r['status_b'])}"
        )


def _chart(result) -> go.Figure:
    labels = [r["label"] for r in result.dimension_rows]
    fig = go.Figure()
    for name, field, color in (("Session A", "score_a", "#2a78d6"), ("Session B", "score_b", "#eb6834")):
        values = [r[field] for r in result.dimension_rows]
        fig.add_bar(
            name=name,
            x=labels,
            y=[v if v is not None else 0 for v in values],
            marker_color=color,
            text=[f"{v:.1f}" if v is not None else "n/a" for v in values],
            textposition="outside",
            cliponaxis=False,
            marker_line_width=2,
            marker_line_color="rgba(252,252,251,1)",
            hovertemplate="%{x}<br>" + name + ": %{text}<extra></extra>",
        )
    fig.update_layout(
        barmode="group",
        title="Dimension scores, A vs B",
        barcornerradius=4,
        yaxis={"range": [0, 110], "title": "Dimension score"},
        height=360,
        margin={"l": 10, "r": 10, "t": 50, "b": 40},
        legend={"orientation": "h", "y": 1.12},
    )
    return fig
