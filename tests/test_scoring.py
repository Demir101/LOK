import pytest

from lok.domain.enums import Dimension, EvidenceType
from lok.domain.models import AssertionResult, HumanReview
from lok.domain.scoring import (
    ScoringError,
    compute_scores,
    coverage_label,
    human_rating_to_score,
    score_dimension,
)

CA = Dimension.CORRECTION_ACCURACY.value
CP = Dimension.CONTEXT_PRESERVATION.value
RE = Dimension.REPEATED_ERROR_DETECTION.value


def res(status: str, weight: float = 1.0, dimension: str = CA, aid: str = "a") -> AssertionResult:
    return AssertionResult(aid, "t1", dimension, "contains", "x", weight, status, "evidence")


def test_all_passed():
    score = score_dimension(CA, [res("passed"), res("passed")], None)
    assert score.automated_score == 100.0
    assert score.evidence_type == EvidenceType.AUTOMATED


def test_all_failed():
    score = score_dimension(CA, [res("failed"), res("failed")], None)
    assert score.automated_score == 0.0
    assert score.combined_score == 0.0


def test_mixed_results_unweighted():
    score = score_dimension(CA, [res("passed"), res("failed"), res("passed"), res("failed")], None)
    assert score.automated_score == 50.0


def test_weighted_assertions():
    # passed weights 3 + 1 = 4; evaluated 3 + 1 + 4 = 8 -> 50 %
    results = [res("passed", 3), res("passed", 1), res("failed", 4)]
    score = score_dimension(CA, results, None)
    assert score.automated_score == pytest.approx(50.0)
    assert score.passed_weight == 4
    assert score.evaluated_weight == 8


def test_zero_evaluated_assertions_is_unavailable():
    score = score_dimension(CA, [res("not_evaluated"), res("error")], None)
    assert score.automated_score is None
    assert score.combined_score is None
    assert score.evidence_type == EvidenceType.NONE
    assert score.not_evaluated == 1
    assert score.errors == 1


def test_error_and_not_evaluated_excluded_from_score():
    results = [res("passed", 1), res("failed", 1), res("error", 10), res("not_evaluated", 10)]
    assert score_dimension(CA, results, None).automated_score == 50.0


def test_human_only_dimension():
    score = score_dimension(CA, [], HumanReview(CA, 3))
    assert score.human_score == 75.0
    assert score.combined_score == 75.0
    assert score.evidence_type == EvidenceType.HUMAN


def test_combined_dimension_score():
    # 0.7 * 50 + 0.3 * 100 = 65
    score = score_dimension(CA, [res("passed"), res("failed")], HumanReview(CA, 4))
    assert score.combined_score == pytest.approx(65.0)
    assert score.evidence_type == EvidenceType.COMBINED


def test_human_rating_conversion_and_bounds():
    assert [human_rating_to_score(r) for r in range(5)] == [0.0, 25.0, 50.0, 75.0, 100.0]
    for bad in (-1, 5, 2.5, True):
        with pytest.raises(ScoringError):
            human_rating_to_score(bad)  # type: ignore[arg-type]


def test_overall_excludes_unassessed_dimensions():
    results = [res("passed", dimension=CA), res("failed", dimension=CP)]
    summary = compute_scores(results)
    # CA = 100, CP = 0, three others unassessed -> overall = 50, not 20
    assert summary.overall_score == pytest.approx(50.0)
    assert summary.assessed_dimensions == 2
    assert summary.coverage == pytest.approx(40.0)
    assert summary.coverage_label == "Limited coverage"
    assert summary.dimension_scores[RE].combined_score is None


def test_overall_normalization_with_mixed_evidence():
    results = [res("passed", dimension=CA), res("passed", dimension=CP), res("failed", dimension=CP)]
    reviews = {RE: HumanReview(RE, 2)}
    summary = compute_scores(results, reviews)
    # CA 100, CP 50, RE 50 -> mean 66.666...
    assert summary.overall_score == pytest.approx(200 / 3)
    assert summary.coverage == pytest.approx(60.0)
    assert summary.coverage_label == "Partial coverage"


def test_full_coverage():
    results = [res("passed", dimension=d.value) for d in Dimension]
    summary = compute_scores(results)
    assert summary.coverage == 100.0
    assert summary.coverage_label == "Full coverage"
    assert summary.overall_score == 100.0


def test_no_evidence_at_all():
    summary = compute_scores([res("not_evaluated")])
    assert summary.overall_score is None
    assert summary.coverage == 0.0
    assert summary.coverage_label == "No assessable evidence"
    assert summary.not_evaluated == 1


def test_counts_in_summary():
    summary = compute_scores([res("passed"), res("failed"), res("error"), res("not_evaluated")])
    assert (summary.passed, summary.failed, summary.errors, summary.not_evaluated) == (1, 1, 1, 1)


def test_coverage_label_thresholds():
    assert coverage_label(100) == "Full coverage"
    assert coverage_label(80) == "Partial coverage"
    assert coverage_label(60) == "Partial coverage"
    assert coverage_label(20) == "Limited coverage"
    assert coverage_label(0) == "No assessable evidence"


def test_review_for_unknown_dimension_rejected():
    with pytest.raises(ScoringError):
        compute_scores([], {"memory": HumanReview("memory", 3)})
