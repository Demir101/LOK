"""Deterministic assertion engine.

The engine verifies explicitly defined text conditions only. A passed
``contains`` assertion establishes that a value is present in a response; it
does not establish that the assistant understood the conversation.

This module has no dependency on Streamlit or storage and is fully testable.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import replace

from lok.domain.enums import AssertionStatus, Dimension, Operator
from lok.domain.models import Assertion, AssertionResult, ConversationTurn, utc_now_iso
from lok.domain.normalization import (
    DEFAULT_POLICY,
    NormalizationPolicy,
    excerpt_around,
    find_match,
    normalize_text,
    strip_edge_punctuation,
    truncate,
)

_VALID_OPERATORS = frozenset(op.value for op in Operator)
_VALID_DIMENSIONS = frozenset(dim.value for dim in Dimension)


def _result(
    assertion: Assertion,
    status: AssertionStatus,
    evidence: str,
    *,
    excerpt: str = "",
    error: str = "",
    evaluated_at: str | None = None,
) -> AssertionResult:
    return AssertionResult(
        assertion_id=assertion.assertion_id,
        turn_id=assertion.turn_id,
        dimension=assertion.dimension,
        operator=assertion.operator,
        expected_value=assertion.expected_value,
        weight=assertion.weight,
        status=status.value,
        evidence=evidence,
        description=assertion.description,
        actual_excerpt=excerpt,
        error_message=error,
        evaluated_at=evaluated_at or utc_now_iso(),
    )


def definition_error(assertion: Assertion) -> str | None:
    """Return a message if the assertion definition itself is invalid."""
    if assertion.operator not in _VALID_OPERATORS:
        return (
            f"Unsupported operator '{assertion.operator}'. "
            f"Supported operators: {', '.join(sorted(_VALID_OPERATORS))}."
        )
    if assertion.dimension not in _VALID_DIMENSIONS:
        return f"Unsupported dimension '{assertion.dimension}'."
    if not isinstance(assertion.expected_value, str) or not assertion.expected_value.strip():
        return "Expected value is empty; an empty expected value cannot be checked meaningfully."
    try:
        weight = float(assertion.weight)
    except (TypeError, ValueError):
        return f"Weight '{assertion.weight}' is not a number."
    if not math.isfinite(weight) or weight <= 0:
        return f"Weight must be a positive finite number (got {assertion.weight})."
    return None


def evaluate_assertion(
    assertion: Assertion,
    turns: Mapping[str, ConversationTurn],
    responses: Mapping[str, str],
    policy: NormalizationPolicy = DEFAULT_POLICY,
    evaluated_at: str | None = None,
) -> AssertionResult:
    """Execute a single assertion and return a structured result with evidence.

    Order of checks:
      1. Assertion definition is valid (else ``error``).
      2. Target turn exists and expects a response (else ``error``).
      3. A non-blank response was provided (else ``not_evaluated``).
      4. Normalise text and run the operator (``passed`` / ``failed``).
    """
    problem = definition_error(assertion)
    if problem:
        return _result(
            assertion,
            AssertionStatus.ERROR,
            f"Assertion could not be executed: {problem}",
            error=problem,
            evaluated_at=evaluated_at,
        )

    turn = turns.get(assertion.turn_id)
    if turn is None:
        message = f"Target turn '{assertion.turn_id}' does not exist in this scenario version."
        return _result(
            assertion,
            AssertionStatus.ERROR,
            f"Assertion could not be executed: {message}",
            error=message,
            evaluated_at=evaluated_at,
        )
    if not turn.requires_response:
        message = f"Target turn '{assertion.turn_id}' is not configured to receive a response."
        return _result(
            assertion,
            AssertionStatus.ERROR,
            f"Assertion could not be executed: {message}",
            error=message,
            evaluated_at=evaluated_at,
        )

    raw_response = responses.get(assertion.turn_id)
    if raw_response is None or not raw_response.strip():
        reason = "No response was provided" if raw_response is None else "The response is empty"
        return _result(
            assertion,
            AssertionStatus.NOT_EVALUATED,
            f"{reason} for turn {turn.order} ('{turn.turn_id}'). "
            "The assertion was not evaluated and is excluded from scoring.",
            evaluated_at=evaluated_at,
        )

    effective = replace(policy, case_sensitive=assertion.case_sensitive)
    return _run_operator(assertion, turn, raw_response, effective, evaluated_at)


def _run_operator(
    assertion: Assertion,
    turn: ConversationTurn,
    response: str,
    policy: NormalizationPolicy,
    evaluated_at: str | None,
) -> AssertionResult:
    display_policy = replace(policy, case_sensitive=True)
    display_text = normalize_text(response, display_policy)
    haystack = normalize_text(response, policy)
    needle = normalize_text(assertion.expected_value, policy)
    case_note = "case-sensitive" if policy.case_sensitive else "case-insensitive"
    boundary_note = "boundary-aware" if assertion.boundary_match else "plain substring"
    turn_label = f"turn {turn.order} ('{turn.turn_id}')"
    expected = assertion.expected_value

    if assertion.operator in (Operator.CONTAINS, Operator.DOES_NOT_CONTAIN):
        index = find_match(haystack, needle, boundary_match=assertion.boundary_match)
        found = index >= 0
        excerpt = excerpt_around(display_text, index, len(needle)) if found else truncate(display_text)
        match_desc = f"({case_note}, {boundary_note} match)"
        if assertion.operator == Operator.CONTAINS:
            passed = found
            evidence = (
                f"Condition satisfied: the response to {turn_label} contains '{expected}' {match_desc}."
                if found
                else f"Condition not satisfied: '{expected}' was not found in the response to "
                f"{turn_label} {match_desc}."
            )
        else:
            passed = not found
            evidence = (
                f"Condition satisfied: '{expected}' does not appear in the response to "
                f"{turn_label} {match_desc}."
                if passed
                else f"Condition not satisfied: the response to {turn_label} contains "
                f"'{expected}' {match_desc}."
            )
    else:
        equal = strip_edge_punctuation(haystack) == strip_edge_punctuation(needle)
        excerpt = truncate(display_text)
        eq_desc = f"({case_note}; surrounding quotes and trailing sentence punctuation ignored)"
        if assertion.operator == Operator.EQUALS:
            passed = equal
            evidence = (
                f"Condition satisfied: the complete response to {turn_label} equals '{expected}' {eq_desc}."
                if equal
                else f"Condition not satisfied: the complete response to {turn_label} does not "
                f"equal '{expected}' {eq_desc}."
            )
        else:
            passed = not equal
            evidence = (
                f"Condition satisfied: the complete response to {turn_label} is not '{expected}' {eq_desc}."
                if passed
                else f"Condition not satisfied: the complete response to {turn_label} equals "
                f"'{expected}' {eq_desc}."
            )

    status = AssertionStatus.PASSED if passed else AssertionStatus.FAILED
    return _result(assertion, status, evidence, excerpt=excerpt, evaluated_at=evaluated_at)


def evaluate_assertions(
    assertions: Iterable[Assertion],
    turns: Iterable[ConversationTurn],
    responses: Mapping[str, str],
    policy: NormalizationPolicy = DEFAULT_POLICY,
) -> list[AssertionResult]:
    """Execute every assertion with one shared timestamp."""
    turn_map = {turn.turn_id: turn for turn in turns}
    timestamp = utc_now_iso()
    return [evaluate_assertion(assertion, turn_map, responses, policy, timestamp) for assertion in assertions]
