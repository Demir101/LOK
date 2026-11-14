import pytest

from lok.domain.models import HumanReview
from lok.services.comparison_service import assertion_fingerprint, compare_sessions
from lok.services.evaluation_service import EvaluationService
from lok.services.scenario_service import ScenarioService
from lok.storage.evaluation_repository import EvaluationRepository
from lok.storage.scenario_repository import ScenarioRepository
from tests.conftest import make_scenario

GOOD = {"t1": "ok", "t2": "May 22, owner Priya", "t3": "Deadline May 22, reminder May 20."}
WEAK = {"t1": "ok", "t2": "May 22", "t3": "Deadline May 15."}


@pytest.fixture
def env(db, scenario):
    repo = ScenarioRepository(db)
    ScenarioService(repo).create(scenario)
    ScenarioService(repo).create(make_scenario("other-scenario"))
    return EvaluationService(repo, EvaluationRepository(db)), repo


def run(svc, scenario_id, responses, label="A"):
    session = svc.start(scenario_id, label, "v1")
    svc.save_responses(session.evaluation_id, responses)
    session, _ = svc.run_evaluation(session.evaluation_id)
    return session


def compare(svc, a, b):
    return compare_sessions(a, svc.scenario_for(a), b, svc.scenario_for(b))


def test_same_scenario_and_version_is_compatible(env, scenario):
    svc, _ = env
    a, b = run(svc, scenario.scenario_id, GOOD), run(svc, scenario.scenario_id, WEAK, "B")
    result = compare(svc, a, b)
    assert result.compatible
    assert result.overall_delta == pytest.approx(
        result.summary_b.overall_score - result.summary_a.overall_score
    )
    ca = next(row for row in result.dimension_rows if row["dimension"] == "correction_accuracy")
    assert ca["score_delta"] == pytest.approx(-100.0)
    changed = {row["assertion_id"] for row in result.assertion_rows if row["changed"]}
    assert {"a1", "a2", "a3"} <= changed
    assert {row["assertion_id"] for row in result.repeated_error_rows} == {"a2"}


def test_different_scenario_is_incompatible(env, scenario):
    svc, _ = env
    a = run(svc, scenario.scenario_id, GOOD)
    b = run(svc, "other-scenario", GOOD)
    result = compare(svc, a, b)
    assert not result.compatible
    assert "different scenarios" in result.reasons[0]
    assert result.overall_delta is None and result.dimension_rows == []


def test_different_versions_are_incompatible(env, scenario):
    svc, repo = env
    a = run(svc, scenario.scenario_id, GOOD)
    edited = repo.get(scenario.scenario_id)
    edited.description = "new version"
    ScenarioService(repo).update(edited)
    b = run(svc, scenario.scenario_id, GOOD)
    result = compare(svc, a, b)
    assert not result.compatible
    assert "different versions" in result.reasons[0]


def test_incompatible_assertion_definitions(env, scenario):
    svc, _ = env
    a = run(svc, scenario.scenario_id, GOOD)
    b = run(svc, scenario.scenario_id, GOOD, "B")
    scenario_a = svc.scenario_for(a)
    scenario_b = svc.scenario_for(b)
    scenario_b.assertions[0].weight = 5.0  # simulate diverging definitions under the same version
    assert assertion_fingerprint(scenario_a) != assertion_fingerprint(scenario_b)
    result = compare_sessions(a, scenario_a, b, scenario_b)
    assert not result.compatible
    assert "assertion definitions differ" in result.reasons[0]


def test_same_session_rejected(env, scenario):
    svc, _ = env
    a = run(svc, scenario.scenario_id, GOOD)
    assert not compare(svc, a, a).compatible


def test_different_coverage_and_missing_dimensions_warn(env, scenario):
    svc, _ = env
    a = run(svc, scenario.scenario_id, GOOD)
    b = run(svc, scenario.scenario_id, GOOD, "B")
    svc.save_human_review(b.evaluation_id, HumanReview("false_correction_resistance", 3))
    b = svc.get(b.evaluation_id)
    result = compare(svc, a, b)
    assert result.compatible
    assert result.coverage_delta == pytest.approx(20.0)
    assert any("Coverage differs" in w for w in result.warnings)
    assert any("assessed only in session B" in w for w in result.warnings)
    fcr = next(r for r in result.dimension_rows if r["dimension"] == "false_correction_resistance")
    assert fcr["score_delta"] is None  # never compare against a missing value
