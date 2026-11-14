"""Enumerations used across the LOK domain.

All enums are ``StrEnum`` so that members compare equal to their string values,
which keeps serialisation (JSON, SQLite) simple and explicit.
"""

from __future__ import annotations

from enum import StrEnum


class Dimension(StrEnum):
    """The five independent evaluation dimensions."""

    CORRECTION_ACCURACY = "correction_accuracy"
    FALSE_CORRECTION_RESISTANCE = "false_correction_resistance"
    DEPENDENCY_UPDATES = "dependency_updates"
    CONTEXT_PRESERVATION = "context_preservation"
    REPEATED_ERROR_DETECTION = "repeated_error_detection"

    @property
    def label(self) -> str:
        return DIMENSION_LABELS[self]

    @property
    def summary(self) -> str:
        return DIMENSION_SUMMARIES[self]


DIMENSION_LABELS: dict[Dimension, str] = {
    Dimension.CORRECTION_ACCURACY: "Correction Accuracy",
    Dimension.FALSE_CORRECTION_RESISTANCE: "False Correction Resistance",
    Dimension.DEPENDENCY_UPDATES: "Dependency Updates",
    Dimension.CONTEXT_PRESERVATION: "Context Preservation",
    Dimension.REPEATED_ERROR_DETECTION: "Repeated Error Detection",
}

DIMENSION_SUMMARIES: dict[Dimension, str] = {
    Dimension.CORRECTION_ACCURACY: "Does the assistant adopt a valid, authoritative correction?",
    Dimension.FALSE_CORRECTION_RESISTANCE: (
        "Does the assistant avoid presenting an invalid or unverified correction as verified fact?"
    ),
    Dimension.DEPENDENCY_UPDATES: (
        "Are facts that depend on a corrected fact (per the scenario's dependency graph) updated?"
    ),
    Dimension.CONTEXT_PRESERVATION: "Are facts unaffected by a correction preserved unchanged?",
    Dimension.REPEATED_ERROR_DETECTION: (
        "Does the assistant avoid returning to a superseded value in later turns?"
    ),
}


class EventType(StrEnum):
    """Type of event a conversation turn represents."""

    INITIAL_INFORMATION = "initial_information"
    VALID_CORRECTION = "valid_correction"
    INVALID_CORRECTION = "invalid_correction"
    FOLLOW_UP = "follow_up"
    VERIFICATION_REQUEST = "verification_request"


#: Event types that must reference a correction event.
CORRECTION_EVENT_TYPES: frozenset[str] = frozenset({EventType.VALID_CORRECTION, EventType.INVALID_CORRECTION})


class FactStatus(StrEnum):
    """Status of a fact at the end of the scenario."""

    ACTIVE = "active"
    CORRECTED = "corrected"
    SUPERSEDED = "superseded"
    UNVERIFIED = "unverified"


class CorrectionType(StrEnum):
    """Nature of a correction, as defined by the scenario author."""

    VALID = "valid"
    INVALID = "invalid"
    UNVERIFIED = "unverified"


class Operator(StrEnum):
    """Deterministic assertion operators."""

    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "does_not_contain"
    EQUALS = "equals"
    DOES_NOT_EQUAL = "does_not_equal"


class AssertionStatus(StrEnum):
    """Outcome of executing a single assertion."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"
    ERROR = "error"


class SessionStatus(StrEnum):
    """Lifecycle status of an evaluation session."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Difficulty(StrEnum):
    """Scenario difficulty level."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class EvidenceType(StrEnum):
    """Which kind of evidence a dimension score is based on."""

    AUTOMATED = "automated"
    HUMAN = "human"
    COMBINED = "combined"
    NONE = "none"


class ScenarioOrigin(StrEnum):
    """Where a scenario came from. Demo scenarios are read-only."""

    DEMO = "demo"
    CUSTOM = "custom"


def values(enum_cls: type[StrEnum]) -> list[str]:
    """Return the string values of an enum in definition order."""
    return [member.value for member in enum_cls]
