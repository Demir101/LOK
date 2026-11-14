from lok.domain.assertions import evaluate_assertion, evaluate_assertions
from lok.domain.enums import AssertionStatus
from lok.domain.models import Assertion, ConversationTurn

TURNS = {
    "t1": ConversationTurn("t1", 1, "Info", "initial_information"),
    "t2": ConversationTurn("t2", 2, "Question", "follow_up"),
    "t0": ConversationTurn("t0", 3, "No reply needed", "follow_up", requires_response=False),
}


def run(operator: str, expected: str, response: str | None, **kwargs):
    assertion = Assertion(
        "a1",
        kwargs.pop("turn_id", "t2"),
        kwargs.pop("dimension", "correction_accuracy"),
        "desc",
        operator,
        expected,
        kwargs.pop("weight", 1.0),
        **kwargs,
    )
    responses = {} if response is None else {"t2": response}
    return evaluate_assertion(assertion, TURNS, responses)


def test_contains_pass_and_fail():
    assert run("contains", "May 22", "The deadline is may 22.").status == AssertionStatus.PASSED
    assert run("contains", "May 22", "The deadline is May 15.").status == AssertionStatus.FAILED


def test_does_not_contain():
    assert run("does_not_contain", "May 15", "It is May 22.").status == AssertionStatus.PASSED
    assert run("does_not_contain", "May 15", "Still May 15").status == AssertionStatus.FAILED


def test_equals_ignores_case_whitespace_and_trailing_period():
    assert run("equals", "192.168.1.10", "  192.168.1.10. ").status == AssertionStatus.PASSED
    assert run("equals", "192.168.1.10", "The IP is 192.168.1.10").status == AssertionStatus.FAILED


def test_equals_does_not_treat_different_ips_as_equal():
    assert run("equals", "192.168.1.10", "192.168.1.100").status == AssertionStatus.FAILED


def test_does_not_equal():
    assert run("does_not_equal", "192.168.1.99", "192.168.1.10").status == AssertionStatus.PASSED
    assert run("does_not_equal", "192.168.1.99", "192.168.1.99").status == AssertionStatus.FAILED


def test_case_sensitive_assertion():
    result = run("contains", "SEV1", "severity is sev1", case_sensitive=True)
    assert result.status == AssertionStatus.FAILED


def test_missing_response_is_not_evaluated():
    result = run("contains", "May 22", None)
    assert result.status == AssertionStatus.NOT_EVALUATED
    assert "No response was provided" in result.evidence


def test_empty_response_is_not_evaluated_even_for_negative_operator():
    # An empty response must never pass a does_not_contain assertion.
    result = run("does_not_contain", "May 15", "   \n ")
    assert result.status == AssertionStatus.NOT_EVALUATED
    assert "empty" in result.evidence


def test_invalid_operator_is_error_not_pass():
    result = run("roughly_matches", "May 22", "May 22")
    assert result.status == AssertionStatus.ERROR
    assert "Unsupported operator" in result.error_message


def test_invalid_expected_value_is_error():
    result = run("does_not_contain", "   ", "anything")
    assert result.status == AssertionStatus.ERROR
    assert "Expected value is empty" in result.error_message


def test_invalid_weight_and_dimension_are_errors():
    assert run("contains", "x", "x", weight=0).status == AssertionStatus.ERROR
    assert run("contains", "x", "x", weight=-1.5).status == AssertionStatus.ERROR
    assert run("contains", "x", "x", dimension="memory").status == AssertionStatus.ERROR


def test_unknown_turn_is_error():
    result = run("contains", "x", "x", turn_id="t99")
    assert result.status == AssertionStatus.ERROR
    assert "does not exist" in result.error_message


def test_turn_without_response_requirement_is_error():
    result = run("contains", "x", "x", turn_id="t0")
    assert result.status == AssertionStatus.ERROR


def test_evidence_contains_expected_value_turn_and_excerpt():
    result = run("contains", "May 22", "After the change the deadline is May 22, confirmed.")
    assert result.status == AssertionStatus.PASSED
    assert "Condition satisfied" in result.evidence
    assert "'May 22'" in result.evidence
    assert "turn 2" in result.evidence
    assert "May 22" in result.actual_excerpt
    assert result.operator == "contains"
    assert result.dimension == "correction_accuracy"


def test_failed_evidence_explains_unsatisfied_condition():
    result = run("contains", "May 22", "The deadline is May 15.")
    assert "Condition not satisfied" in result.evidence
    assert "May 15" in result.actual_excerpt


def test_evaluate_assertions_handles_multiple_turns():
    assertions = [
        Assertion("a1", "t1", "context_preservation", "d", "contains", "Berlin"),
        Assertion("a2", "t2", "correction_accuracy", "d", "contains", "May 22"),
    ]
    results = evaluate_assertions(assertions, TURNS.values(), {"t1": "Meeting in Berlin"})
    assert [r.status for r in results] == [AssertionStatus.PASSED, AssertionStatus.NOT_EVALUATED]
    assert results[0].evaluated_at == results[1].evaluated_at
