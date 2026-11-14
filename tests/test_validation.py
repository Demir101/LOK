import copy

import pytest

from lok.domain.models import Assertion, DependencyEdge, build_fact_history
from lok.domain.validation import (
    ScenarioValidationError,
    ensure_valid,
    errors_only,
    parse_scenario_dict,
    structural_issues,
    validate_scenario,
)
from tests.conftest import make_scenario


def messages(scenario):
    return [str(issue) for issue in errors_only(validate_scenario(scenario))]


def test_valid_scenario_has_no_errors(scenario):
    assert messages(scenario) == []
    ensure_valid(scenario)


def test_duplicate_ids_detected(scenario):
    scenario.facts.append(copy.deepcopy(scenario.facts[0]))
    scenario.assertions.append(copy.deepcopy(scenario.assertions[0]))
    found = messages(scenario)
    assert any("Duplicate fact ID 'deadline'" in m for m in found)
    assert any("Duplicate assertion ID 'a1'" in m for m in found)


def test_missing_required_fields(scenario):
    scenario.title = " "
    scenario.facts[0].name = ""
    found = messages(scenario)
    assert any(m.startswith("title:") for m in found)
    assert any(m.startswith("facts[0].name:") for m in found)


def test_invalid_id_format(scenario):
    scenario.scenario_id = "bad id with spaces"
    assert any("Invalid ID" in m for m in messages(scenario))


def test_invalid_fact_reference_in_correction_and_dependency(scenario):
    scenario.corrections[0].target_fact_id = "ghost"
    scenario.dependencies.append(DependencyEdge("deadline", "ghost2"))
    found = messages(scenario)
    assert any("Unknown fact 'ghost'" in m for m in found)
    assert any("Unknown target fact 'ghost2'" in m for m in found)


def test_invalid_turn_reference_in_assertion(scenario):
    scenario.assertions[0].turn_id = "t42"
    assert any("Unknown turn 't42'" in m for m in messages(scenario))


def test_circular_dependency_rejected(scenario):
    scenario.dependencies.append(DependencyEdge("reminder", "deadline"))
    assert any("Circular dependency" in m for m in messages(scenario))


def test_invalid_assertion_operator_and_weight(scenario):
    scenario.assertions[0].operator = "fuzzy"
    scenario.assertions[1].weight = 0
    scenario.assertions[2].weight = -2
    scenario.assertions[3].dimension = "memory"
    found = messages(scenario)
    assert any("assertions[0].operator" in m for m in found)
    assert any("assertions[1].weight" in m and "greater than zero" in m for m in found)
    assert any("assertions[2].weight" in m for m in found)
    assert any("assertions[3].dimension" in m for m in found)


def test_invalid_correction_events(scenario):
    correction = scenario.corrections[0]
    correction.is_authoritative = False  # valid but not authoritative
    correction.proposed_value = correction.original_value
    found = messages(scenario)
    assert any("must be marked authoritative" in m for m in found)
    assert any("must differ" in m for m in found)


def test_correction_turn_type_mismatch(scenario):
    scenario.corrections[0].correction_type = "invalid"
    scenario.corrections[0].is_authoritative = False
    assert any("'invalid_correction' turn" in m for m in messages(scenario))


def test_turn_references_unknown_correction(scenario):
    scenario.turns[1].correction_id = "c404"
    assert any("Unknown correction reference 'c404'" in m for m in messages(scenario))


def test_duplicate_turn_order(scenario):
    scenario.turns[2].order = 2
    assert any("Duplicate turn order 2" in m for m in messages(scenario))


def test_only_negative_assertions_produces_warning():
    scenario = make_scenario(
        assertions=[Assertion("a1", "t3", "repeated_error_detection", "d", "does_not_contain", "May 15")]
    )
    issues = validate_scenario(scenario)
    assert errors_only(issues) == []
    assert any(issue.severity == "warning" for issue in issues)


def test_ensure_valid_raises_with_all_issues(scenario):
    scenario.title = ""
    scenario.assertions[0].operator = "bad"
    with pytest.raises(ScenarioValidationError) as info:
        ensure_valid(scenario)
    assert len(info.value.issues) >= 2


def test_structural_validation_of_raw_data(scenario):
    data = scenario.to_dict()
    data["turns"][0]["order"] = "first"
    del data["facts"][0]["name"]
    data["assertions"][0]["weight"] = True
    issues = [str(i) for i in structural_issues(data)]
    assert any("turns[0].order" in m for m in issues)
    assert any("facts[0].name" in m for m in issues)
    assert any("assertions[0].weight" in m for m in issues)
    with pytest.raises(ScenarioValidationError):
        parse_scenario_dict(data)


def test_structural_rejects_non_object():
    assert structural_issues(["not", "a", "scenario"])[0].message == "Scenario must be a JSON object."


def test_round_trip_dict(scenario):
    restored = parse_scenario_dict(scenario.to_dict())
    assert restored.to_dict() == scenario.to_dict()


def test_fact_history_keeps_original_and_corrections(scenario):
    history = build_fact_history(scenario, "deadline")
    assert [entry.value for entry in history] == ["May 15", "May 22"]
    assert history[0].source == "initial"
    assert history[1].accepted is True
    assert history[1].turn_order == 2
