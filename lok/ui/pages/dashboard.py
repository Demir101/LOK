"""Dashboard: summary cards, charts, recent activity and descriptive insights from stored data."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lok.domain.enums import Dimension
from lok.domain.scoring import coverage_label
from lok.ui import components as ui
from lok.ui import state


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def render() -> None:
    services = state.services()
    ui.page_header(
        "Dashboard",
        "Overview of stored evaluation sessions. Every figure is computed from the local database; "
        "nothing is estimated or generated.",
        kicker="Overview",
    )
    sessions = services.evaluations.list_summaries()
    scenarios = services.scenarios.list_scenarios()

    if not sessions:
        _empty_state(len(scenarios))
        st.plotly_chart(_category_chart(scenarios), width="stretch", theme="streamlit")
        return

    scored = [s["overall_score"] for s in sessions if s["overall_score"] is not None]
    active = [s for s in sessions if s["evaluated_at"] or s["overall_score"] is not None]
    coverages = [s["coverage"] for s in active if s["coverage"] is not None]
    completed = sum(1 for s in sessions if s["status"] == "completed")

    cols = st.columns(6)
    cols[0].metric("Evaluation sessions", len(sessions), border=True)
    cols[1].metric("Completed", completed, border=True)
    cols[2].metric("Incomplete", len(sessions) - completed, border=True, help="Draft or in progress.")
    cols[3].metric("Scenarios", len(scenarios), border=True)
    cols[4].metric(
        "Average overall score",
        ui.fmt_score(_mean(scored)),
        border=True,
        help=f"Mean over {len(scored)} session(s) that have an overall score. "
        "Sessions without assessable evidence are excluded, not counted as zero.",
    )
    cols[5].metric(
        "Average coverage",
        ui.fmt_pct(_mean(coverages)),
        border=True,
        help=f"Mean over {len(coverages)} session(s) that were run or reviewed.",
    )
    st.caption(
        "Averages mix scenarios and coverage levels; use the Comparison page for like-for-like comparisons."
    )

    dim_rows = pd.DataFrame(services.evaluation_repo.dimension_scores())
    status_counts = services.evaluation_repo.assertion_status_counts()

    left, right = st.columns(2)
    with left, st.container(border=True):
        st.plotly_chart(_dimension_average_chart(dim_rows), width="stretch", theme="streamlit")
    with right, st.container(border=True):
        st.plotly_chart(_history_chart(sessions), width="stretch", theme="streamlit")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.plotly_chart(_status_chart(status_counts), width="stretch", theme="streamlit")
    with right, st.container(border=True):
        st.plotly_chart(_coverage_chart(active), width="stretch", theme="streamlit")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.plotly_chart(_category_chart(scenarios), width="stretch", theme="streamlit")
    with right, st.container(border=True):
        st.plotly_chart(_system_dimension_chart(dim_rows), width="stretch", theme="streamlit")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Recent activity")
        for row in sessions[:8]:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1], vertical_alignment="center")
                c1.markdown(
                    f"**{row['ai_system']}** · {row['model_label']} &nbsp; {ui.SESSION_BADGE[row['status']]}  \n"
                    f"<span class='lok-muted'>{row['scenario_title']} (v{row['scenario_version']}) · "
                    f"score {ui.fmt_score(row['overall_score'])} · coverage {ui.fmt_pct(row['coverage'])} · "
                    f"updated {ui.fmt_time(row['updated_at'])}</span>",
                    unsafe_allow_html=True,
                )
                if c2.button("Open", key=f"dash_open_{row['evaluation_id']}", width="stretch"):
                    state.go("history", **{state.HISTORY_SELECTED: row["evaluation_id"]})
    with right:
        st.subheader("Descriptive insights")
        for line in _insights(sessions, dim_rows, services):
            st.markdown(f"- {line}")
        st.caption(
            "Descriptive statistics over stored data only. They are not explanations of model behaviour."
        )


def _empty_state(scenario_count: int) -> None:
    ui.empty_state(
        "Welcome to LOK",
        "LOK checks how an AI assistant handles **corrections** and keeps **context** consistent across a "
        "multi-turn conversation. You run a scenario with any assistant yourself, paste its replies here, "
        "and LOK evaluates them against explicit, deterministic assertions — optionally complemented by "
        "your own human review.\n\n"
        f"1. Pick one of the **{scenario_count} scenarios** in the Scenario Library.\n"
        "2. Start an evaluation and paste the assistant's response for each turn.\n"
        "3. Run the assertions, inspect the evidence, optionally add a human review, and export a report.\n\n"
        "No evaluation sessions exist yet, so there are no statistics to show.",
    )
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Open Scenario Library", type="primary", width="stretch"):
        state.go("library")
    if c2.button("Start an evaluation", width="stretch"):
        state.go("run")


def _bar_layout(fig: go.Figure, title: str, height: int = 320) -> go.Figure:
    fig.update_layout(
        title=title,
        height=height,
        margin={"l": 10, "r": 20, "t": 50, "b": 40},
        barcornerradius=4,
        bargap=0.35,
    )
    return fig


def _dimension_average_chart(dim_rows: pd.DataFrame) -> go.Figure:
    labels, values, colors, texts = [], [], [], []
    for dimension in Dimension:
        subset = (
            dim_rows[(dim_rows["dimension"] == dimension.value) & dim_rows["combined_score"].notna()]
            if not dim_rows.empty
            else pd.DataFrame()
        )
        labels.append(dimension.label)
        if subset.empty:
            values.append(0)
            colors.append("rgba(0,0,0,0)")
            texts.append("Not assessed")
        else:
            avg = float(subset["combined_score"].mean())
            values.append(avg)
            colors.append(ui.DIMENSION_COLORS[dimension.value])
            texts.append(f"{avg:.1f} (n={len(subset)})")
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
            text=texts,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>Average dimension score: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis={"range": [0, 118], "title": "Average dimension score", "dtick": 25},
        yaxis={"autorange": "reversed"},
    )
    return _bar_layout(fig, "Dimension score comparison (all sessions)")


def _history_chart(sessions: list[dict]) -> go.Figure:
    df = pd.DataFrame([s for s in sessions if s["overall_score"] is not None])
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No session has an overall score yet", showarrow=False)
        return _bar_layout(fig, "Evaluation history")
    df["when"] = pd.to_datetime(df["evaluated_at"].fillna(df["updated_at"]), utc=True)
    df = df.sort_values("when")
    systems = list(dict.fromkeys(df["ai_system"]))
    fig = px.line(
        df,
        x="when",
        y="overall_score",
        color="ai_system",
        markers=True,
        color_discrete_sequence=ui.SERIES_COLORS,
        category_orders={"ai_system": systems},
        custom_data=["scenario_title", "coverage", "model_label"],
    )
    fig.update_traces(
        line_width=2,
        marker_size=9,
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Score %{y:.1f}<br>%{customdata[0]}"
        "<br>%{customdata[2]} · coverage %{customdata[1]:.0f}%<extra></extra>",
    )
    fig.update_layout(
        yaxis={"range": [0, 105], "title": "Overall score"},
        xaxis_title=None,
        legend_title_text="AI system",
        hovermode="closest",
    )
    return _bar_layout(fig, "Evaluation history over time")


def _status_chart(counts: dict[str, int]) -> go.Figure:
    order = ["passed", "failed", "not_evaluated", "error"]
    fig = go.Figure(
        go.Bar(
            x=[s.replace("_", " ") for s in order],
            y=[counts.get(s, 0) for s in order],
            marker_color=[ui.STATUS_COLORS[s] for s in order],
            text=[counts.get(s, 0) for s in order],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}: %{y}<extra></extra>",
        )
    )
    fig.update_layout(yaxis_title="Assertions", showlegend=False)
    return _bar_layout(fig, "Assertion result distribution")


def _coverage_chart(active: list[dict]) -> go.Figure:
    order = ["Full coverage", "Partial coverage", "Limited coverage", "No assessable evidence"]
    labels = [coverage_label(s["coverage"] or 0.0) for s in active]
    values = [labels.count(name) for name in order]
    fig = go.Figure(
        go.Bar(
            x=order,
            y=values,
            marker_color="#2a78d6",
            text=values,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}: %{y} session(s)<extra></extra>",
        )
    )
    fig.update_layout(yaxis_title="Sessions", showlegend=False)
    return _bar_layout(fig, "Coverage distribution (sessions run or reviewed)")


def _category_chart(scenarios: list) -> go.Figure:
    counts = pd.Series([s.category for s in scenarios]).value_counts().sort_values()
    fig = go.Figure(
        go.Bar(
            x=counts.values,
            y=counts.index,
            orientation="h",
            marker_color="#2a78d6",
            hovertemplate="%{y}: %{x} scenario(s)<extra></extra>",
        )
    )
    fig.update_layout(xaxis_title="Scenarios", xaxis_dtick=1)
    return _bar_layout(fig, "Scenario category distribution", height=max(320, 22 * len(counts) + 90))


def _system_dimension_chart(dim_rows: pd.DataFrame) -> go.Figure:
    if dim_rows.empty or dim_rows["combined_score"].notna().sum() == 0:
        fig = go.Figure()
        fig.add_annotation(text="No assessed dimensions yet", showarrow=False)
        return _bar_layout(fig, "Dimension performance by AI system")
    data = dim_rows[dim_rows["combined_score"].notna()].groupby(["ai_system", "dimension"], as_index=False)
    agg = data["combined_score"].agg(["mean", "count"]).reset_index()
    agg["Dimension"] = agg["dimension"].map(ui.dimension_label)
    fig = px.bar(
        agg,
        x="ai_system",
        y="mean",
        color="Dimension",
        barmode="group",
        color_discrete_map={d.label: ui.DIMENSION_COLORS[d.value] for d in Dimension},
        category_orders={"Dimension": [d.label for d in Dimension]},
        custom_data=["count"],
    )
    fig.update_traces(
        hovertemplate="%{x}<br>%{fullData.name}: %{y:.1f} (n=%{customdata[0]})<extra></extra>",
        marker_line_width=2,
        marker_line_color="rgba(252,252,251,1)",
    )
    fig.update_layout(
        yaxis={"range": [0, 105], "title": "Average dimension score"},
        xaxis_title=None,
        legend_title_text=None,
    )
    return _bar_layout(fig, "Dimension performance by AI system", height=360)


def _insights(sessions: list[dict], dim_rows: pd.DataFrame, services) -> list[str]:
    lines: list[str] = []
    assessed = dim_rows[dim_rows["combined_score"].notna()] if not dim_rows.empty else dim_rows
    if not assessed.empty:
        means = assessed.groupby("dimension")["combined_score"].agg(["mean", "count"])
        low = means["mean"].idxmin()
        lines.append(
            f"Lowest average dimension: **{ui.dimension_label(low)}** "
            f"({means.loc[low, 'mean']:.1f} over {int(means.loc[low, 'count'])} session(s))."
        )
    else:
        lines.append("No dimension has been assessed yet.")
    failures = services.evaluation_repo.failures_by_scenario()[:3]
    if failures:
        top = ", ".join(f"{f['title']} ({f['failed']})" for f in failures)
        lines.append(f"Most failed assertions: {top}.")
    by_dim = pd.DataFrame(services.evaluation_repo.results_by_dimension())
    if not by_dim.empty:
        re_rows = by_dim[by_dim["dimension"] == Dimension.REPEATED_ERROR_DETECTION.value]
        failed = int(re_rows.loc[re_rows["status"] == "failed", "n"].sum())
        evaluated = int(re_rows.loc[re_rows["status"].isin(["passed", "failed"]), "n"].sum())
        if evaluated:
            lines.append(
                f"Repeated-error assertions failed {failed} of {evaluated} times "
                f"({failed / evaluated * 100:.0f}%)."
            )
    active = [s for s in sessions if s["evaluated_at"] or s["overall_score"] is not None]
    if active:
        full = sum(1 for s in active if (s["coverage"] or 0) >= 100)
        lines.append(f"{full} of {len(active)} run or reviewed session(s) have full coverage.")
    incomplete = sum(1 for s in sessions if s["status"] != "completed")
    lines.append(f"{incomplete} session(s) are incomplete (draft or in progress).")
    return lines
