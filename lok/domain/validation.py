"""Scenario validation.

Two layers:

* :func:`parse_scenario_dict` checks the *structure* of untrusted input (JSON
  imports, builder drafts) and converts it into a :class:`Scenario`.
* :func:`validate_scenario` checks *semantic* rules: unique IDs, valid
  references, enum values, weights, acyclic dependencies and correction
  consistency.

Both report every problem found as :class:`ValidationIssue` objects with a
location, so users can fix all issues at once.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from lok.domain.dependency_graph import DependencyGraph, GraphValidationError
from lok.domain.enums import (
    CORRECTION_EVENT_TYPES,
    CorrectionType,
    Difficulty,
    Dimension,
    EventType,
    FactStatus,
    Operator,
    ScenarioOrigin,
)
from lok.domain.models import Scenario

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
ID_RULE = "1–64 characters: letters, digits, '_', '-' or '.', starting with a letter or digit"
MAX_TEXT_LENGTH = 20_000

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation problem."""

    location: str
    message: str
    severity: str = ERROR

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


class ScenarioValidationError(ValueError):
    """Raised when a scenario fails validation. Carries every issue found."""

    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = [issue for issue in issues if issue.severity == ERROR]
        summary = "; ".join(str(issue) for issue in self.issues[:5])
        more = f" (+{len(self.issues) - 5} more)" if len(self.issues) > 5 else ""
        super().__init__(f"Scenario is invalid: {summary}{more}")


# --------------------------------------------------------------------------- #
# Structural parsing
# --------------------------------------------------------------------------- #

_REQUIRED_TOP_LEVEL: dict[str, type | tuple[type, ...]] = {
    "scenario_id": str,
    "title": str,
    "description": str,
    "category": str,
    "difficulty": str,
    "facts": list,
    "turns": list,
    "assertions": list,
}
_OPTIONAL_TOP_LEVEL: dict[str, type | tuple[type, ...]] = {
    "objective": str,
    "tags": list,
    "version": int,
    "origin": str,
    "created_at": str,
    "updated_at": str,
    "change_note": str,
    "corrections": list,
    "dependencies": list,
    "expected_outcomes": list,
}
_ITEM_SCHEMAS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    # section: (required fields, optional fields)
    "facts": (
        {"fact_id": str, "name": str, "initial_value": str, "expected_current_value": str, "status": str},
        {"description": str},
    ),
    "turns": (
        {"turn_id": str, "order": int, "user_message": str, "event_type": str},
        {"requires_response": bool, "correction_id": (str, type(None)), "notes": str},
    ),
    "corrections": (
        {
            "correction_id": str,
            "target_fact_id": str,
            "original_value": str,
            "proposed_value": str,
            "correction_type": str,
            "is_authoritative": bool,
            "turn_id": str,
            "expected_behavior": str,
        },
        {"explanation": str},
    ),
    "dependencies": (
        {"source_fact_id": str, "target_fact_id": str},
        {"explanation": str},
    ),
    "assertions": (
        {
            "assertion_id": str,
            "turn_id": str,
            "dimension": str,
            "description": str,
            "operator": str,
            "expected_value": str,
            "weight": (int, float),
        },
        {"explanation": str, "case_sensitive": bool, "boundary_match": bool},
    ),
    "expected_outcomes": (
        {"outcome_id": str, "description": str},
        {"dimension": (str, type(None)), "turn_id": (str, type(None))},
    ),
}


def _type_name(expected: type | tuple[type, ...]) -> str:
    if isinstance(expected, tuple):
        return " or ".join("null" if t is type(None) else t.__name__ for t in expected)
    return expected.__name__


def _check_type(value: Any, expected: type | tuple[type, ...]) -> bool:
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    # bool is a subclass of int; do not accept True/False as numbers.
    if isinstance(value, bool) and bool not in expected_types:
        return False
    return isinstance(value, expected_types)


def structural_issues(data: Any) -> list[ValidationIssue]:
    """Return structural problems in raw scenario data (types and required keys)."""
    if not isinstance(data, dict):
        return [ValidationIssue("scenario", "Scenario must be a JSON object.")]
    issues: list[ValidationIssue] = []
    for key, expected in _REQUIRED_TOP_LEVEL.items():
        if key not in data:
            issues.append(ValidationIssue(key, "Required field is missing."))
        elif not _check_type(data[key], expected):
            issues.append(ValidationIssue(key, f"Must be of type {_type_name(expected)}."))
    for key, expected in _OPTIONAL_TOP_LEVEL.items():
        if key in data and data[key] is not None and not _check_type(data[key], expected):
            issues.append(ValidationIssue(key, f"Must be of type {_type_name(expected)}."))
    if isinstance(data.get("tags"), list):
        for index, tag in enumerate(data["tags"]):
            if not isinstance(tag, str):
                issues.append(ValidationIssue(f"tags[{index}]", "Tags must be strings."))

    for section, (required, optional) in _ITEM_SCHEMAS.items():
        items = data.get(section)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            location = f"{section}[{index}]"
            if not isinstance(item, dict):
                issues.append(ValidationIssue(location, "Each entry must be an object."))
                continue
            for key, expected in required.items():
                if key not in item:
                    issues.append(ValidationIssue(f"{location}.{key}", "Required field is missing."))
                elif not _check_type(item[key], expected):
                    issues.append(
                        ValidationIssue(f"{location}.{key}", f"Must be of type {_type_name(expected)}.")
                    )
            for key, expected in optional.items():
                if key in item and not _check_type(item[key], expected):
                    issues.append(
                        ValidationIssue(f"{location}.{key}", f"Must be of type {_type_name(expected)}.")
                    )
    return issues


def parse_scenario_dict(data: Any) -> Scenario:
    """Structurally validate raw data and build a :class:`Scenario`.

    Raises :class:`ScenarioValidationError` listing every structural problem.
    Semantic validation is performed separately by :func:`validate_scenario`.
    """
    issues = structural_issues(data)
    if issues:
        raise ScenarioValidationError(issues)
    return Scenario.from_dict(data)


# --------------------------------------------------------------------------- #
# Semantic validation
# --------------------------------------------------------------------------- #


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _check_id(value: str, location: str, issues: list[ValidationIssue]) -> None:
    if not value or not value.strip():
        issues.append(ValidationIssue(location, "ID is required."))
    elif not ID_PATTERN.match(value):
        issues.append(ValidationIssue(location, f"Invalid ID '{value}'. Use {ID_RULE}."))


def _check_required_text(value: str, location: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(ValidationIssue(location, "This field is required."))
    elif len(value) > MAX_TEXT_LENGTH:
        issues.append(ValidationIssue(location, f"Text exceeds {MAX_TEXT_LENGTH} characters."))


def _enum_check(
    value: str | None, allowed: Iterable[str], location: str, issues: list[ValidationIssue]
) -> None:
    allowed_list = list(allowed)
    if value not in allowed_list:
        issues.append(
            ValidationIssue(location, f"Unsupported value '{value}'. Allowed: {', '.join(allowed_list)}.")
        )


def validate_scenario(scenario: Scenario) -> list[ValidationIssue]:
    """Return all semantic validation issues (errors and warnings)."""
    issues: list[ValidationIssue] = []
    _validate_metadata(scenario, issues)
    _validate_facts(scenario, issues)
    _validate_turns(scenario, issues)
    _validate_corrections(scenario, issues)
    _validate_dependencies(scenario, issues)
    _validate_assertions(scenario, issues)
    _validate_outcomes(scenario, issues)
    return issues


def errors_only(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity == ERROR]


def ensure_valid(scenario: Scenario) -> list[ValidationIssue]:
    """Raise :class:`ScenarioValidationError` on errors; return warnings otherwise."""
    issues = validate_scenario(scenario)
    if errors_only(issues):
        raise ScenarioValidationError(issues)
    return [issue for issue in issues if issue.severity == WARNING]


def _validate_metadata(s: Scenario, issues: list[ValidationIssue]) -> None:
    _check_id(s.scenario_id, "scenario_id", issues)
    _check_required_text(s.title, "title", issues)
    _check_required_text(s.description, "description", issues)
    _check_required_text(s.category, "category", issues)
    _enum_check(s.difficulty, [d.value for d in Difficulty], "difficulty", issues)
    _enum_check(s.origin, [o.value for o in ScenarioOrigin], "origin", issues)
    if not isinstance(s.version, int) or s.version < 1:
        issues.append(ValidationIssue("version", "Version must be a positive integer."))
    for index, tag in enumerate(s.tags):
        if not tag.strip():
            issues.append(ValidationIssue(f"tags[{index}]", "Tags must not be empty."))
    for tag in _duplicates(t.strip().lower() for t in s.tags):
        issues.append(ValidationIssue("tags", f"Duplicate tag '{tag}'.", WARNING))


def _validate_facts(s: Scenario, issues: list[ValidationIssue]) -> None:
    if not s.facts:
        issues.append(ValidationIssue("facts", "At least one fact is required."))
    for duplicate in _duplicates(f.fact_id for f in s.facts):
        issues.append(ValidationIssue("facts", f"Duplicate fact ID '{duplicate}'."))
    for index, fact in enumerate(s.facts):
        location = f"facts[{index}]"
        _check_id(fact.fact_id, f"{location}.fact_id", issues)
        _check_required_text(fact.name, f"{location}.name", issues)
        _check_required_text(fact.initial_value, f"{location}.initial_value", issues)
        _check_required_text(fact.expected_current_value, f"{location}.expected_current_value", issues)
        _enum_check(fact.status, [st.value for st in FactStatus], f"{location}.status", issues)


def _validate_turns(s: Scenario, issues: list[ValidationIssue]) -> None:
    if not s.turns:
        issues.append(ValidationIssue("turns", "At least one conversation turn is required."))
        return
    for duplicate in _duplicates(t.turn_id for t in s.turns):
        issues.append(ValidationIssue("turns", f"Duplicate turn ID '{duplicate}'."))
    for duplicate in _duplicates(str(t.order) for t in s.turns):
        issues.append(ValidationIssue("turns", f"Duplicate turn order {duplicate}."))
    if not any(t.requires_response for t in s.turns):
        issues.append(ValidationIssue("turns", "At least one turn must require an AI response."))
    correction_ids = {c.correction_id for c in s.corrections}
    for index, turn in enumerate(s.turns):
        location = f"turns[{index}]"
        _check_id(turn.turn_id, f"{location}.turn_id", issues)
        if not isinstance(turn.order, int) or turn.order < 1:
            issues.append(ValidationIssue(f"{location}.order", "Order must be a positive integer."))
        _check_required_text(turn.user_message, f"{location}.user_message", issues)
        _enum_check(turn.event_type, [e.value for e in EventType], f"{location}.event_type", issues)
        if turn.event_type in CORRECTION_EVENT_TYPES and not turn.correction_id:
            issues.append(
                ValidationIssue(
                    f"{location}.correction_id",
                    f"A '{turn.event_type}' turn must reference a correction event.",
                )
            )
        if turn.correction_id and turn.correction_id not in correction_ids:
            issues.append(
                ValidationIssue(
                    f"{location}.correction_id",
                    f"Unknown correction reference '{turn.correction_id}'.",
                )
            )


def _validate_corrections(s: Scenario, issues: list[ValidationIssue]) -> None:
    for duplicate in _duplicates(c.correction_id for c in s.corrections):
        issues.append(ValidationIssue("corrections", f"Duplicate correction ID '{duplicate}'."))
    fact_ids = {f.fact_id for f in s.facts}
    turns = {t.turn_id: t for t in s.turns}
    for index, correction in enumerate(s.corrections):
        location = f"corrections[{index}]"
        _check_id(correction.correction_id, f"{location}.correction_id", issues)
        _enum_check(
            correction.correction_type,
            [c.value for c in CorrectionType],
            f"{location}.correction_type",
            issues,
        )
        if correction.target_fact_id not in fact_ids:
            issues.append(
                ValidationIssue(f"{location}.target_fact_id", f"Unknown fact '{correction.target_fact_id}'.")
            )
        _check_required_text(correction.original_value, f"{location}.original_value", issues)
        _check_required_text(correction.proposed_value, f"{location}.proposed_value", issues)
        _check_required_text(correction.expected_behavior, f"{location}.expected_behavior", issues)
        if correction.original_value.strip() and (
            correction.original_value.strip() == correction.proposed_value.strip()
        ):
            issues.append(
                ValidationIssue(
                    f"{location}.proposed_value", "Proposed value must differ from the original value."
                )
            )
        if correction.correction_type == CorrectionType.VALID and not correction.is_authoritative:
            issues.append(
                ValidationIssue(
                    f"{location}.is_authoritative", "A valid correction must be marked authoritative."
                )
            )
        if (
            correction.correction_type in (CorrectionType.INVALID, CorrectionType.UNVERIFIED)
            and correction.is_authoritative
        ):
            issues.append(
                ValidationIssue(
                    f"{location}.is_authoritative",
                    f"An '{correction.correction_type}' correction cannot be authoritative.",
                )
            )
        turn = turns.get(correction.turn_id)
        if turn is None:
            issues.append(ValidationIssue(f"{location}.turn_id", f"Unknown turn '{correction.turn_id}'."))
            continue
        if turn.correction_id != correction.correction_id:
            issues.append(
                ValidationIssue(
                    f"{location}.turn_id",
                    f"Turn '{turn.turn_id}' does not reference correction '{correction.correction_id}'.",
                )
            )
        expected_event = (
            EventType.VALID_CORRECTION
            if correction.correction_type == CorrectionType.VALID
            else EventType.INVALID_CORRECTION
        )
        if correction.correction_type in {c.value for c in CorrectionType} and (
            turn.event_type != expected_event
        ):
            issues.append(
                ValidationIssue(
                    f"{location}.turn_id",
                    f"A '{correction.correction_type}' correction must be introduced by a "
                    f"'{expected_event.value}' turn (turn '{turn.turn_id}' is '{turn.event_type}').",
                )
            )


def _validate_dependencies(s: Scenario, issues: list[ValidationIssue]) -> None:
    fact_ids = [f.fact_id for f in s.facts]
    known = set(fact_ids)
    seen: set[tuple[str, str]] = set()
    edges: list[tuple[str, str]] = []
    for index, edge in enumerate(s.dependencies):
        location = f"dependencies[{index}]"
        ok = True
        for endpoint, role in ((edge.source_fact_id, "source"), (edge.target_fact_id, "target")):
            if endpoint not in known:
                issues.append(ValidationIssue(location, f"Unknown {role} fact '{endpoint}'."))
                ok = False
        if edge.source_fact_id == edge.target_fact_id:
            issues.append(ValidationIssue(location, "A fact cannot depend on itself."))
            ok = False
        pair = (edge.source_fact_id, edge.target_fact_id)
        if pair in seen:
            issues.append(ValidationIssue(location, f"Duplicate dependency {pair[0]} -> {pair[1]}."))
            ok = False
        seen.add(pair)
        if ok:
            edges.append(pair)
    unique_nodes = list(dict.fromkeys(fact_ids))
    try:
        DependencyGraph.build(unique_nodes, edges)
    except GraphValidationError as exc:
        issues.append(ValidationIssue("dependencies", str(exc)))


def _validate_assertions(s: Scenario, issues: list[ValidationIssue]) -> None:
    if not s.assertions:
        issues.append(ValidationIssue("assertions", "At least one assertion is required."))
        return
    for duplicate in _duplicates(a.assertion_id for a in s.assertions):
        issues.append(ValidationIssue("assertions", f"Duplicate assertion ID '{duplicate}'."))
    turns = {t.turn_id: t for t in s.turns}
    for index, assertion in enumerate(s.assertions):
        location = f"assertions[{index}]"
        _check_id(assertion.assertion_id, f"{location}.assertion_id", issues)
        _check_required_text(assertion.description, f"{location}.description", issues)
        _enum_check(assertion.operator, [o.value for o in Operator], f"{location}.operator", issues)
        _enum_check(assertion.dimension, [d.value for d in Dimension], f"{location}.dimension", issues)
        if not assertion.expected_value or not assertion.expected_value.strip():
            issues.append(ValidationIssue(f"{location}.expected_value", "Expected value is required."))
        weight = assertion.weight
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight):
            issues.append(ValidationIssue(f"{location}.weight", "Weight must be a finite number."))
        elif weight <= 0:
            issues.append(ValidationIssue(f"{location}.weight", "Weight must be greater than zero."))
        turn = turns.get(assertion.turn_id)
        if turn is None:
            issues.append(ValidationIssue(f"{location}.turn_id", f"Unknown turn '{assertion.turn_id}'."))
        elif not turn.requires_response:
            issues.append(
                ValidationIssue(
                    f"{location}.turn_id",
                    f"Turn '{assertion.turn_id}' does not require an AI response, so it cannot be checked.",
                )
            )
    positive = {Operator.CONTAINS, Operator.EQUALS}
    if s.assertions and not any(a.operator in positive for a in s.assertions):
        issues.append(
            ValidationIssue(
                "assertions",
                "All assertions are negative (does_not_contain / does_not_equal). A trivial "
                "response could pass them; add at least one positive assertion.",
                WARNING,
            )
        )


def _validate_outcomes(s: Scenario, issues: list[ValidationIssue]) -> None:
    for duplicate in _duplicates(o.outcome_id for o in s.expected_outcomes):
        issues.append(ValidationIssue("expected_outcomes", f"Duplicate outcome ID '{duplicate}'."))
    turn_ids = {t.turn_id for t in s.turns}
    for index, outcome in enumerate(s.expected_outcomes):
        location = f"expected_outcomes[{index}]"
        _check_id(outcome.outcome_id, f"{location}.outcome_id", issues)
        _check_required_text(outcome.description, f"{location}.description", issues)
        if outcome.dimension is not None:
            _enum_check(outcome.dimension, [d.value for d in Dimension], f"{location}.dimension", issues)
        if outcome.turn_id is not None and outcome.turn_id not in turn_ids:
            issues.append(ValidationIssue(f"{location}.turn_id", f"Unknown turn '{outcome.turn_id}'."))
