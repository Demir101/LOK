"""Evaluation reports: versioned JSON, CSV tables and a Markdown document.

Reports are built only from stored data. Missing values are shown explicitly
("Not Assessed", "No response provided"); nothing is estimated or invented.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any

from lok import APP_NAME, PRODUCT_DESCRIPTION, TAGLINE, __version__
from lok.domain.enums import AssertionStatus, Dimension
from lok.domain.models import EvaluationSession, Scenario, ScoreSummary, utc_now_iso
from lok.domain.scoring import (
    AUTOMATED_WEIGHT,
    HUMAN_RATING_LABELS,
    HUMAN_WEIGHT,
    compute_scores,
    format_score,
)

REPORT_FORMAT = "lok.evaluation_report"
REPORT_SCHEMA_VERSION = 1

LIMITATIONS = [
    "Text assertions verify explicitly defined string conditions; they do not establish semantic correctness.",
    "Human review scores are subjective assessments by the reviewer.",
    "Results depend on the quality and coverage of the scenario and its assertions.",
    "A result describes behaviour on this scenario only; it does not prove general AI reliability.",
    "Demo scenarios shipped with LOK are synthetic examples, not validated benchmark material.",
    "LOK does not use an AI model to judge responses.",
    "Dependency graphs are defined explicitly by scenario authors, not inferred from natural language.",
]


class ReportError(ValueError):
    """Raised when evaluation data is inconsistent and cannot be reported."""


def _check(session: EvaluationSession, scenario: Scenario) -> None:
    if session.scenario_id != scenario.scenario_id or session.scenario_version != scenario.version:
        raise ReportError(
            f"Evaluation {session.evaluation_id} is pinned to {session.scenario_id} "
            f"v{session.scenario_version}, but scenario {scenario.scenario_id} v{scenario.version} was supplied."
        )
    known = {a.assertion_id for a in scenario.assertions}
    unknown = [r.assertion_id for r in session.assertion_results if r.assertion_id not in known]
    if unknown:
        raise ReportError(f"Results reference unknown assertions: {', '.join(unknown)}.")


def build_report(session: EvaluationSession, scenario: Scenario) -> dict[str, Any]:
    """Build the complete, versioned report document for one evaluation."""
    _check(session, scenario)
    summary = compute_scores(session.assertion_results, session.human_reviews)
    results = {r.assertion_id: r for r in session.assertion_results}
    assertions = []
    for a in scenario.assertions:
        r = results.get(a.assertion_id)
        assertions.append(
            {
                **a.to_dict(),
                "status": r.status if r else "not_run",
                "evidence": r.evidence if r else "The evaluation has not been run.",
                "actual_excerpt": r.actual_excerpt if r else "",
                "error_message": r.error_message if r else "",
                "evaluated_at": r.evaluated_at if r else None,
            }
        )
    return {
        "format": REPORT_FORMAT,
        "schema_version": REPORT_SCHEMA_VERSION,
        "generator": {"name": APP_NAME, "tagline": TAGLINE, "version": __version__},
        "exported_at": utc_now_iso(),
        "evaluation": {
            "evaluation_id": session.evaluation_id,
            "status": session.status,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "evaluated_at": session.evaluated_at,
            "completed_at": session.completed_at,
            "notes": session.notes,
        },
        "ai_system": {"name": session.ai_system, "model_label": session.model_label},
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "version": scenario.version,
            "title": scenario.title,
            "description": scenario.description,
            "category": scenario.category,
            "difficulty": scenario.difficulty,
            "origin": scenario.origin,
            "dimensions": scenario.dimensions,
        },
        "responses": [
            {
                "turn_id": t.turn_id,
                "order": t.order,
                "event_type": t.event_type,
                "user_message": t.user_message,
                "response": session.provided_response(t.turn_id),
            }
            for t in scenario.response_turns
        ],
        "assertions": assertions,
        "scores": summary.to_dict(),
        "human_reviews": [session.human_reviews[d].to_dict() for d in session.human_reviews],
        "methodology": {
            "automated_score": "sum(weights passed) / sum(weights passed + failed) * 100",
            "human_score": "rating / 4 * 100",
            "combined_weights": {"automated": AUTOMATED_WEIGHT, "human": HUMAN_WEIGHT},
            "overall_score": "mean of assessed dimension scores (equal weights)",
            "coverage": "assessed dimensions / 5 * 100",
        },
        "limitations": LIMITATIONS,
    }


def to_json(session: EvaluationSession, scenario: Scenario) -> str:
    return json.dumps(build_report(session, scenario), ensure_ascii=False, indent=2)


def _csv_bytes(header: list[str], rows: Iterable[list[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    # UTF-8 with BOM so that Excel detects the encoding correctly.
    return buffer.getvalue().encode("utf-8-sig")


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def assertions_csv(session: EvaluationSession, scenario: Scenario) -> bytes:
    """One row per assertion, with evaluation metadata repeated for analysis tools."""
    report = build_report(session, scenario)
    header = [
        "evaluation_id",
        "ai_system",
        "model_label",
        "scenario_id",
        "scenario_version",
        "assertion_id",
        "turn_id",
        "dimension",
        "operator",
        "expected_value",
        "weight",
        "status",
        "evidence",
        "actual_excerpt",
        "error_message",
    ]
    rows = [
        [
            session.evaluation_id,
            session.ai_system,
            session.model_label,
            scenario.scenario_id,
            scenario.version,
            a["assertion_id"],
            a["turn_id"],
            a["dimension"],
            a["operator"],
            a["expected_value"],
            a["weight"],
            a["status"],
            a["evidence"],
            a["actual_excerpt"],
            a["error_message"],
        ]
        for a in report["assertions"]
    ]
    return _csv_bytes(header, rows)


def dimensions_csv(session: EvaluationSession, scenario: Scenario) -> bytes:
    """One row per dimension with automated, human and combined scores."""
    _check(session, scenario)
    summary = compute_scores(session.assertion_results, session.human_reviews)
    header = [
        "evaluation_id",
        "ai_system",
        "model_label",
        "scenario_id",
        "scenario_version",
        "dimension",
        "automated_score",
        "human_rating",
        "human_score",
        "dimension_score",
        "evidence_type",
        "passed",
        "failed",
        "not_evaluated",
        "errors",
        "overall_score",
        "coverage",
    ]
    rows = [
        [
            session.evaluation_id,
            session.ai_system,
            session.model_label,
            scenario.scenario_id,
            scenario.version,
            d.dimension,
            _round(d.automated_score),
            d.human_rating,
            _round(d.human_score),
            _round(d.combined_score),
            d.evidence_type,
            d.passed,
            d.failed,
            d.not_evaluated,
            d.errors,
            _round(summary.overall_score),
            _round(summary.coverage),
        ]
        for d in summary.dimension_scores.values()
    ]
    return _csv_bytes(header, rows)


def history_csv(rows: Iterable[dict[str, Any]]) -> bytes:
    """One row per evaluation session (Evaluation History export)."""
    header = [
        "evaluation_id",
        "ai_system",
        "model_label",
        "scenario_id",
        "scenario_title",
        "scenario_version",
        "status",
        "created_at",
        "updated_at",
        "evaluated_at",
        "overall_score",
        "coverage",
        "passed",
        "failed",
        "not_evaluated",
        "errors",
    ]
    return _csv_bytes(
        header,
        (
            [
                r["evaluation_id"],
                r["ai_system"],
                r["model_label"],
                r["scenario_id"],
                r["scenario_title"],
                r["scenario_version"],
                r["status"],
                r["created_at"],
                r["updated_at"],
                r["evaluated_at"],
                _round(r["overall_score"]),
                _round(r["coverage"]),
                r["passed"],
                r["failed"],
                r["not_evaluated"],
                r["errors"],
            ]
            for r in rows
        ),
    )


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #


def _md(text: Any) -> str:
    """Escape a value for use inside a Markdown table cell."""
    if text is None or text == "":
        return "—"
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _pct(value: float | None) -> str:
    return "Not Assessed" if value is None else f"{value:.1f}"


def _assertion_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    lines = ["| ID | Turn | Dimension | Check | Weight | Evidence |", "|---|---|---|---|---|---|"]
    for a in rows:
        check = f"{a['operator']} \u201c{a['expected_value']}\u201d"
        lines.append(
            f"| {_md(a['assertion_id'])} | {_md(a['turn_id'])} | {_md(Dimension(a['dimension']).label)} "
            f"| {_md(check)} | {a['weight']:g} | {_md(a['evidence'])} |"
        )
    return [*lines, ""]


def to_markdown(session: EvaluationSession, scenario: Scenario) -> str:
    """Render a complete Markdown report."""
    report = build_report(session, scenario)
    summary: ScoreSummary = compute_scores(session.assertion_results, session.human_reviews)
    by_status: dict[str, list[dict[str, Any]]] = {}
    for a in report["assertions"]:
        by_status.setdefault(a["status"], []).append(a)

    lines = [
        f"# {APP_NAME} — {TAGLINE}",
        f"**{PRODUCT_DESCRIPTION}** · Evaluation report",
        "",
        f"_Generated {report['exported_at']} by {APP_NAME} {__version__}. "
        "All values below come from stored evaluation data._",
        "",
        "## 1. Evaluation overview",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Evaluation ID | {_md(session.evaluation_id)} |",
        f"| Status | {_md(session.status)} |",
        f"| Created | {_md(session.created_at)} |",
        f"| Last evaluated | {_md(session.evaluated_at or 'Not run')} |",
        f"| Completed | {_md(session.completed_at or 'Not completed')} |",
        f"| Overall score | {_pct(summary.overall_score)} |",
        f"| Coverage | {summary.coverage:.0f}% — {summary.coverage_label} |",
        f"| Notes | {_md(session.notes)} |",
        "",
        "## 2. AI system",
        "",
        f"- **AI system:** {_md(session.ai_system)}",
        f"- **Model / version label:** {_md(session.model_label)}",
        "",
        "## 3. Scenario",
        "",
        f"- **Title:** {_md(scenario.title)}",
        f"- **Scenario ID / version:** `{scenario.scenario_id}` v{scenario.version}",
        f"- **Category / difficulty:** {_md(scenario.category)} / {_md(scenario.difficulty)}",
        f"- **Origin:** {'Synthetic demo scenario' if scenario.is_demo else 'Custom scenario'}",
        f"- **Description:** {_md(scenario.description)}",
        "",
        "## 4. Dimension scores",
        "",
        "| Dimension | Automated | Human (0–4) | Dimension score | Evidence | Passed | Failed | Not evaluated | Errors |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in summary.dimension_scores.values():
        rating = "—" if d.human_rating is None else f"{d.human_rating} ({_pct(d.human_score)})"
        lines.append(
            f"| {Dimension(d.dimension).label} | {_pct(d.automated_score)} | {rating} | "
            f"{_pct(d.combined_score)} | {d.evidence_type} | {d.passed} | {d.failed} | "
            f"{d.not_evaluated} | {d.errors} |"
        )
    lines += [
        "",
        f"**Overall score:** {_pct(summary.overall_score)} · **Coverage:** {summary.coverage:.0f}% "
        f"({summary.coverage_label}; {summary.assessed_dimensions} of 5 dimensions assessed)",
        "",
        "## 5. Automated evidence",
        "",
        f"Assertions: {summary.passed} passed, {summary.failed} failed, "
        f"{summary.not_evaluated} not evaluated, {summary.errors} errors"
        + ("" if session.has_run else " — **the evaluation has not been run**")
        + ".",
        "",
        "### Passed assertions",
        "",
        *_assertion_table(by_status.get(AssertionStatus.PASSED.value, [])),
        "### Failed assertions",
        "",
        *_assertion_table(by_status.get(AssertionStatus.FAILED.value, [])),
        "### Assertions not evaluated",
        "",
        *_assertion_table(
            by_status.get(AssertionStatus.NOT_EVALUATED.value, []) + by_status.get("not_run", [])
        ),
        "### Evaluation errors",
        "",
        *_assertion_table(by_status.get(AssertionStatus.ERROR.value, [])),
        "## 6. Human review",
        "",
        "_Human scores are subjective assessments, not objective automated results._",
        "",
    ]
    if session.human_reviews:
        for dimension in Dimension:
            review = session.human_reviews.get(dimension.value)
            if review is None:
                continue
            lines += [
                f"**{dimension.label}** — rating {review.rating}/4 "
                f"({HUMAN_RATING_LABELS[review.rating]}), reviewer: {_md(review.reviewer or 'unnamed')}, "
                f"{review.reviewed_at}",
                "",
                f"- Reviewer notes: {_md(review.reviewer_notes)}",
                f"- Evidence notes: {_md(review.evidence_notes)}",
                f"- Explanation: {_md(review.explanation)}",
                "",
            ]
    else:
        lines += ["_No human review was recorded._", ""]

    lines += ["## 7. Responses", ""]
    for item in report["responses"]:
        lines += [
            f"**Turn {item['order']}** (`{item['turn_id']}`, {item['event_type']})",
            "",
            f"> User: {_md(item['user_message'])}",
            "",
            "```text",
            (item["response"] or "No response provided.").replace("```", "'''"),
            "```",
            "",
        ]
    lines += [
        "## 8. Scoring methodology",
        "",
        "- Automated score = sum of weights of passed assertions / sum of weights of evaluated "
        "(passed + failed) assertions × 100. `not_evaluated` and `error` are excluded.",
        "- Human score = rating / 4 × 100.",
        f"- Dimension score = {AUTOMATED_WEIGHT:.2f} × automated + {HUMAN_WEIGHT:.2f} × human when "
        "both exist; otherwise the available score; otherwise Not Assessed.",
        "- Overall score = mean of assessed dimension scores (equal weights); unassessed dimensions "
        "are excluded, never treated as zero.",
        "- Coverage = assessed dimensions / 5 × 100.",
        "",
        "## 9. Limitations",
        "",
        *[f"- {item}" for item in LIMITATIONS],
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "LIMITATIONS",
    "REPORT_FORMAT",
    "REPORT_SCHEMA_VERSION",
    "ReportError",
    "assertions_csv",
    "build_report",
    "dimensions_csv",
    "format_score",
    "history_csv",
    "to_json",
    "to_markdown",
]
