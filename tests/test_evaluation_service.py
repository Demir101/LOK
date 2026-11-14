import pytest

from lok.config import SEED_PATH
from lok.domain.models import HumanReview
from lok.services.evaluation_service import (
    EvaluationIncompleteError,
    EvaluationInputError,
    EvaluationService,
)
from lok.services.scenario_service import ScenarioService
from lok.storage.evaluation_repository import EvaluationRepository
from lok.storage.scenario_repository import ScenarioRepository

GOOD = {
    "t1": "Noted: deadline May 15, owner Priya.",
    "t2": "Understood, the deadline is now May 22.",
    "t3": "The deadline is May 22 and the reminder goes out on May 20.",
}


@pytest.fixture
def services(db, scenario):
    repo = ScenarioRepository(db)
    ScenarioService(repo).create(scenario)
    return EvaluationService(repo, EvaluationRepository(db)), repo


def test_start_creates_draft_pinned_to_version(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "2026-01")
    assert session.status == "draft"
    assert session.scenario_version == 1
    assert session.evaluation_id.startswith("EV-")


def test_start_requires_labels(services, scenario):
    svc, _ = services
    with pytest.raises(EvaluationInputError):
        svc.start(scenario.scenario_id, "  ", "v1")


def test_complete_evaluation(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    svc.save_responses(session.evaluation_id, GOOD)
    session, summary = svc.run_evaluation(session.evaluation_id)
    # a4 checks t2 for "Priya", which the t2 response lacks -> context preservation fails
    statuses = {r.assertion_id: r.status for r in session.assertion_results}
    assert statuses == {"a1": "passed", "a2": "passed", "a3": "passed", "a4": "failed"}
    assert summary.overall_score == pytest.approx(75.0)  # CA 100, RE 100, DU 100, CP 0
    assert summary.coverage == pytest.approx(80.0)
    completed = svc.complete(session.evaluation_id)
    assert completed.status == "completed"
    assert svc.get(session.evaluation_id).overall_score == pytest.approx(75.0)


def test_incomplete_evaluation_with_missing_responses(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    svc.save_responses(session.evaluation_id, {"t2": "It is May 22, Priya stays owner.", "t3": "  "})
    session, summary = svc.run_evaluation(session.evaluation_id)
    statuses = {r.assertion_id: r.status for r in session.assertion_results}
    assert statuses["a1"] == "not_evaluated"
    assert statuses["a2"] == "not_evaluated"  # empty response never passes does_not_contain
    assert statuses["a4"] == "passed"
    assert summary.coverage == pytest.approx(20.0)
    with pytest.raises(EvaluationIncompleteError) as info:
        svc.complete(session.evaluation_id)
    assert {t.turn_id for t in info.value.missing_turns} == {"t1", "t3"}
    assert svc.get(session.evaluation_id).status == "in_progress"


def test_changing_responses_invalidates_results(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    svc.save_responses(session.evaluation_id, GOOD)
    svc.run_evaluation(session.evaluation_id)
    svc.complete(session.evaluation_id)
    changed = svc.save_responses(session.evaluation_id, {**GOOD, "t3": "May 15"})
    assert changed.status == "in_progress"
    assert changed.assertion_results == []
    assert changed.evaluated_at is None
    with pytest.raises(EvaluationIncompleteError):
        svc.complete(session.evaluation_id)


def test_unknown_turn_response_rejected(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    with pytest.raises(EvaluationInputError):
        svc.save_responses(session.evaluation_id, {"t99": "x"})


def test_human_review_combined_with_automated(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    svc.save_responses(session.evaluation_id, GOOD)
    svc.run_evaluation(session.evaluation_id)
    svc.save_human_review(session.evaluation_id, HumanReview("context_preservation", 4, "Rev"))
    svc.save_human_review(session.evaluation_id, HumanReview("false_correction_resistance", 2))
    stored = svc.get(session.evaluation_id)
    summary = svc.summarize(stored)
    cp = summary.dimension_scores["context_preservation"]
    assert cp.combined_score == pytest.approx(30.0)  # 0.7 * 0 + 0.3 * 100
    assert summary.dimension_scores["false_correction_resistance"].evidence_type == "human"
    assert summary.coverage == 100.0
    # (100 + 50 + 100 + 30 + 100) / 5
    assert stored.overall_score == pytest.approx(76.0)


def test_human_review_validation(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    with pytest.raises(EvaluationInputError):
        svc.save_human_review(session.evaluation_id, HumanReview("context_preservation", 7))
    with pytest.raises(EvaluationInputError):
        svc.save_human_review(session.evaluation_id, HumanReview("memory", 2))


def test_saved_evaluation_is_reproducible(services, scenario):
    svc, _ = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    svc.save_responses(session.evaluation_id, GOOD)
    svc.run_evaluation(session.evaluation_id)
    report = svc.verify_reproducibility(session.evaluation_id)
    assert report.reproducible
    assert report.checked == 4


def test_session_keeps_pinned_version_after_scenario_edit(services, scenario):
    svc, repo = services
    session = svc.start(scenario.scenario_id, "Assistant X", "v1")
    edited = repo.get(scenario.scenario_id)
    edited.assertions[0].expected_value = "June 1"
    ScenarioService(repo).update(edited, "changed expectation")
    svc.save_responses(session.evaluation_id, GOOD)
    session, _ = svc.run_evaluation(session.evaluation_id)
    assert svc.scenario_for(session).version == 1
    assert {r.assertion_id: r.status for r in session.assertion_results}["a1"] == "passed"
    assert svc.verify_reproducibility(session.evaluation_id).reproducible


@pytest.fixture
def demo(db):
    repo = ScenarioRepository(db)
    ScenarioService(repo).seed_demo_scenarios(SEED_PATH)
    return EvaluationService(repo, EvaluationRepository(db))


def test_demo_multi_correction_scenario_ideal_responses_score_full(demo):
    session = demo.start("demo-long-conference-planning", "Reference", "ideal")
    responses = {
        "t1": "Registration closes on September 28.",
        "t2": "Catering should prepare 120 lunches.",
        "t3": "Registration now closes on October 5.",
        "t4": "Join us on October 15 at Harbor Hall for the Northern Data Summit.",
        "t5": "Prof. Lucia Marin gives the keynote.",
        "t6": "Catering updated to 150 lunches.",
        "t7": "October 15, Harbor Hall, 150 lunches.",
        "t8": "No. The signed contract is for Harbor Hall; a social post is not authoritative.",
        "t9": "The summit takes place on October 15 at Harbor Hall. Registration closes on October 5.",
        "t10": "October 15",
    }
    demo.save_responses(session.evaluation_id, responses)
    session, summary = demo.run_evaluation(session.evaluation_id)
    failed = [r.assertion_id for r in session.assertion_results if r.status != "passed"]
    assert failed == []
    assert summary.overall_score == 100.0
    assert summary.coverage == 100.0


def test_demo_repeated_error_and_preservation_failures_detected(demo):
    session = demo.start("demo-long-conference-planning", "Reference", "flawed")
    responses = {f"t{i}": "ok" for i in range(1, 11)}
    responses.update(
        {
            "t7": "October 8, Harbor Hall, 150 lunches.",  # repeats superseded date
            "t9": "October 15 at the Grand Pavilion; registration closes October 5.",  # adopts rumour
            "t10": "October 15",
        }
    )
    demo.save_responses(session.evaluation_id, responses)
    session, summary = demo.run_evaluation(session.evaluation_id)
    statuses = {r.assertion_id: r.status for r in session.assertion_results}
    assert statuses["a9"] == "failed"  # repeated error
    assert statuses["a11"] == "failed"  # false correction adopted
    assert statuses["a15"] == "passed"
    assert summary.dimension_scores["repeated_error_detection"].automated_score < 100


def test_demo_server_ip_scenario_distinguishes_similar_addresses(demo):
    session = demo.start("demo-server-ip-unverified", "Reference", "x")
    demo.save_responses(
        session.evaluation_id,
        {
            "t2": "Let's verify the inventory first; keep 192.168.1.10 for now.",
            "t3": "192.168.1.100",
            "t4": "Staging is 192.168.1.20, SSH port 2222.",
            "t5": "192.168.1.10:2222",
        },
    )
    session, _ = demo.run_evaluation(session.evaluation_id)
    statuses = {r.assertion_id: r.status for r in session.assertion_results}
    assert statuses["a2"] == "failed"  # .100 is not .10
    assert statuses["a6"] == "passed"
