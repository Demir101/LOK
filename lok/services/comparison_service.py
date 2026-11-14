"""Comparison of two evaluation sessions.

A numerical comparison is only produced when both sessions were evaluated
against the same scenario ID, the same scenario version and identical
assertion definitions. Otherwise the result explains why, and contains no
score differences that could suggest a misleading conclusion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from lok.domain.enums import Dimension, SessionStatus
from lok.domain.models import EvaluationSession, Scenario, ScoreSummary
from lok.domain.scoring import compute_scores


def assertion_fingerprint(scenario: Scenario) -> str:
    """Stable hash of every assertion definition in a scenario version."""
    payload = sorted((a.to_dict() for a in scenario.assertions), key=lambda item: item["assertion_id"])
    for item in payload:
        item["weight"] = float(item["weight"])
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


@dataclass
class ComparisonResult:
    """Outcome of comparing session A (baseline) with session B."""

    session_a: EvaluationSession
    session_b: EvaluationSession
    compatible: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_a: ScoreSummary | None = None
    summary_b: ScoreSummary | None = None
    overall_delta: float | None = None
    coverage_delta: float | None = None
    dimension_rows: list[dict[str, Any]] = field(default_factory=list)
    assertion_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def repeated_error_rows(self) -> list[dict[str, Any]]:
        return [
            row for row in self.assertion_rows if row["dimension"] == Dimension.REPEATED_ERROR_DETECTION.value
        ]


def compatibility_reasons(
    a: EvaluationSession, scenario_a: Scenario, b: EvaluationSession, scenario_b: Scenario
) -> list[str]:
    """Return the reasons the two sessions cannot be compared (empty when compatible)."""
    reasons: list[str] = []
    if a.evaluation_id == b.evaluation_id:
        reasons.append("Both selections are the same evaluation session.")
    if a.scenario_id != b.scenario_id:
        reasons.append(
            f"The sessions use different scenarios ('{a.scenario_id}' vs '{b.scenario_id}'). "
            "Scores from different scenarios measure different conditions."
        )
    elif a.scenario_version != b.scenario_version:
        reasons.append(
            f"The sessions use different versions of '{a.scenario_id}' "
            f"(v{a.scenario_version} vs v{b.scenario_version}); assertions or turns may differ."
        )
    if not reasons and assertion_fingerprint(scenario_a) != assertion_fingerprint(scenario_b):
        reasons.append("The assertion definitions differ between the two sessions.")
    return reasons


def compare_sessions(
    a: EvaluationSession, scenario_a: Scenario, b: EvaluationSession, scenario_b: Scenario
) -> ComparisonResult:
    """Compare session ``b`` against baseline ``a``."""
    reasons = compatibility_reasons(a, scenario_a, b, scenario_b)
    if reasons:
        return ComparisonResult(a, b, compatible=False, reasons=reasons)

    summary_a = compute_scores(a.assertion_results, a.human_reviews)
    summary_b = compute_scores(b.assertion_results, b.human_reviews)
    warnings: list[str] = []
    for label, session in (("A", a), ("B", b)):
        if not session.has_run:
            warnings.append(f"Session {label} has not been run; it has no automated results.")
        if session.status != SessionStatus.COMPLETED:
            warnings.append(f"Session {label} is not completed ({session.status}).")
    if abs(summary_a.coverage - summary_b.coverage) > 1e-9:
        warnings.append(
            f"Coverage differs (A {summary_a.coverage:.0f}% vs B {summary_b.coverage:.0f}%). "
            "Overall scores are based on different sets of dimensions and are not directly comparable."
        )

    dimension_rows: list[dict[str, Any]] = []
    for dimension in Dimension:
        da = summary_a.dimension_scores[dimension.value]
        db = summary_b.dimension_scores[dimension.value]
        if da.is_assessed != db.is_assessed:
            assessed_in = "A" if da.is_assessed else "B"
            warnings.append(f"{dimension.label} is assessed only in session {assessed_in}.")
        elif da.evidence_type != db.evidence_type:
            warnings.append(
                f"{dimension.label} uses different evidence types "
                f"(A {da.evidence_type}, B {db.evidence_type})."
            )
        dimension_rows.append(
            {
                "dimension": dimension.value,
                "label": dimension.label,
                "automated_a": da.automated_score,
                "automated_b": db.automated_score,
                "automated_delta": _delta(da.automated_score, db.automated_score),
                "human_a": da.human_score,
                "human_b": db.human_score,
                "human_delta": _delta(da.human_score, db.human_score),
                "score_a": da.combined_score,
                "score_b": db.combined_score,
                "score_delta": _delta(da.combined_score, db.combined_score),
                "evidence_a": da.evidence_type,
                "evidence_b": db.evidence_type,
                "passed_a": da.passed,
                "passed_b": db.passed,
                "failed_a": da.failed,
                "failed_b": db.failed,
            }
        )

    results_a = {r.assertion_id: r for r in a.assertion_results}
    results_b = {r.assertion_id: r for r in b.assertion_results}
    assertion_rows = []
    for assertion in scenario_a.assertions:
        ra, rb = results_a.get(assertion.assertion_id), results_b.get(assertion.assertion_id)
        status_a = ra.status if ra else "not_run"
        status_b = rb.status if rb else "not_run"
        assertion_rows.append(
            {
                "assertion_id": assertion.assertion_id,
                "dimension": assertion.dimension,
                "description": assertion.description,
                "turn_id": assertion.turn_id,
                "status_a": status_a,
                "status_b": status_b,
                "changed": status_a != status_b,
                "evidence_a": ra.evidence if ra else "",
                "evidence_b": rb.evidence if rb else "",
            }
        )

    return ComparisonResult(
        a,
        b,
        compatible=True,
        warnings=warnings,
        summary_a=summary_a,
        summary_b=summary_b,
        overall_delta=_delta(summary_a.overall_score, summary_b.overall_score),
        coverage_delta=summary_b.coverage - summary_a.coverage,
        dimension_rows=dimension_rows,
        assertion_rows=assertion_rows,
    )
