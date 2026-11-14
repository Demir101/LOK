"""Transparent scoring methodology.

Formulas (all scores on a 0–100 scale):

* Automated score  = sum(weights of passed) / sum(weights of passed + failed) × 100
  (``not_evaluated`` and ``error`` assertions are excluded; no evaluated
  assertions → automated score unavailable).
* Human score      = rating / 4 × 100.
* Dimension score  = 0.70 × automated + 0.30 × human when both exist,
  otherwise whichever exists, otherwise *Not Assessed*.
* Overall score    = mean of the assessed dimension scores (equal weights).
  Unassessed dimensions are excluded, never counted as zero.
* Coverage         = assessed dimensions / 5 × 100.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lok.domain.enums import AssertionStatus, Dimension, EvidenceType
from lok.domain.models import AssertionResult, DimensionScore, HumanReview, ScoreSummary

AUTOMATED_WEIGHT = 0.70
HUMAN_WEIGHT = 0.30
HUMAN_RATING_MIN = 0
HUMAN_RATING_MAX = 4
DIMENSION_COUNT = len(Dimension)

HUMAN_RATING_LABELS: dict[int, str] = {
    0: "Critical failure",
    1: "Poor",
    2: "Partial",
    3: "Good",
    4: "Excellent",
}

FULL_COVERAGE = 100.0
PARTIAL_COVERAGE_MIN = 60.0


class ScoringError(ValueError):
    """Raised when scoring inputs are invalid (for example an out-of-range rating)."""


def human_rating_to_score(rating: int) -> float:
    """Convert a 0–4 human rating to a percentage."""
    if isinstance(rating, bool) or not isinstance(rating, int):
        raise ScoringError(f"Human rating must be an integer, got {rating!r}.")
    if not HUMAN_RATING_MIN <= rating <= HUMAN_RATING_MAX:
        raise ScoringError(
            f"Human rating must be between {HUMAN_RATING_MIN} and {HUMAN_RATING_MAX}, got {rating}."
        )
    return rating / HUMAN_RATING_MAX * 100.0


def automated_score(results: Iterable[AssertionResult]) -> tuple[float | None, float, float]:
    """Return ``(score, passed_weight, evaluated_weight)`` for a set of results."""
    passed_weight = 0.0
    evaluated_weight = 0.0
    for result in results:
        if result.status == AssertionStatus.PASSED:
            passed_weight += result.weight
            evaluated_weight += result.weight
        elif result.status == AssertionStatus.FAILED:
            evaluated_weight += result.weight
    if evaluated_weight <= 0:
        return None, passed_weight, evaluated_weight
    return passed_weight / evaluated_weight * 100.0, passed_weight, evaluated_weight


def combine(automated: float | None, human: float | None) -> tuple[float | None, EvidenceType]:
    """Combine automated and human scores into a dimension score."""
    if automated is not None and human is not None:
        return automated * AUTOMATED_WEIGHT + human * HUMAN_WEIGHT, EvidenceType.COMBINED
    if automated is not None:
        return automated, EvidenceType.AUTOMATED
    if human is not None:
        return human, EvidenceType.HUMAN
    return None, EvidenceType.NONE


def score_dimension(
    dimension: str,
    results: Iterable[AssertionResult],
    review: HumanReview | None,
) -> DimensionScore:
    """Score one dimension from its assertion results and optional human review."""
    relevant = [result for result in results if result.dimension == dimension]
    auto, passed_weight, evaluated_weight = automated_score(relevant)
    human = human_rating_to_score(review.rating) if review is not None else None
    combined, evidence = combine(auto, human)
    return DimensionScore(
        dimension=dimension,
        automated_score=auto,
        human_score=human,
        combined_score=combined,
        evidence_type=evidence.value,
        passed=sum(1 for r in relevant if r.status == AssertionStatus.PASSED),
        failed=sum(1 for r in relevant if r.status == AssertionStatus.FAILED),
        not_evaluated=sum(1 for r in relevant if r.status == AssertionStatus.NOT_EVALUATED),
        errors=sum(1 for r in relevant if r.status == AssertionStatus.ERROR),
        passed_weight=passed_weight,
        evaluated_weight=evaluated_weight,
        human_rating=review.rating if review is not None else None,
    )


def coverage_label(coverage: float) -> str:
    """Human-readable coverage classification."""
    if coverage >= FULL_COVERAGE:
        return "Full coverage"
    if coverage >= PARTIAL_COVERAGE_MIN:
        return "Partial coverage"
    if coverage > 0:
        return "Limited coverage"
    return "No assessable evidence"


def overall_score(dimension_scores: Iterable[DimensionScore]) -> float | None:
    """Equal-weight mean of assessed dimension scores, or ``None`` if none assessed."""
    assessed = [d.combined_score for d in dimension_scores if d.combined_score is not None]
    if not assessed:
        return None
    return sum(assessed) / len(assessed)


def compute_scores(
    results: Iterable[AssertionResult],
    human_reviews: Mapping[str, HumanReview] | None = None,
) -> ScoreSummary:
    """Compute the full score summary for an evaluation session."""
    result_list = list(results)
    reviews = human_reviews or {}
    unknown = set(reviews) - {d.value for d in Dimension}
    if unknown:
        raise ScoringError(f"Human review for unsupported dimension(s): {', '.join(sorted(unknown))}.")
    dimension_scores = {
        dimension.value: score_dimension(dimension.value, result_list, reviews.get(dimension.value))
        for dimension in Dimension
    }
    assessed = sum(1 for score in dimension_scores.values() if score.is_assessed)
    coverage = assessed / DIMENSION_COUNT * 100.0
    return ScoreSummary(
        dimension_scores=dimension_scores,
        overall_score=overall_score(dimension_scores.values()),
        coverage=coverage,
        coverage_label=coverage_label(coverage),
        assessed_dimensions=assessed,
        passed=sum(1 for r in result_list if r.status == AssertionStatus.PASSED),
        failed=sum(1 for r in result_list if r.status == AssertionStatus.FAILED),
        not_evaluated=sum(1 for r in result_list if r.status == AssertionStatus.NOT_EVALUATED),
        errors=sum(1 for r in result_list if r.status == AssertionStatus.ERROR),
    )


def format_score(value: float | None, unavailable: str = "Not Assessed") -> str:
    """Format a score for display; unavailable values are shown explicitly."""
    return unavailable if value is None else f"{value:.1f}"
