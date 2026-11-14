"""Domain models for scenarios, evaluation sessions and results.

The models are plain dataclasses without any dependency on storage or UI code.
Enumerated fields are stored as strings (see :mod:`lok.domain.enums`) so that
invalid values coming from imports can be represented and reported by the
validation layer instead of crashing during construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from lok.domain.enums import (
    AssertionStatus,
    CorrectionType,
    Dimension,
    EvidenceType,
    ScenarioOrigin,
    SessionStatus,
)


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Scenario definition
# --------------------------------------------------------------------------- #


@dataclass
class Fact:
    """A named piece of information tracked through the conversation."""

    fact_id: str
    name: str
    initial_value: str
    expected_current_value: str
    status: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "name": self.name,
            "initial_value": self.initial_value,
            "expected_current_value": self.expected_current_value,
            "status": self.status,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        return cls(
            fact_id=str(data["fact_id"]),
            name=str(data["name"]),
            initial_value=str(data.get("initial_value", "")),
            expected_current_value=str(data.get("expected_current_value", "")),
            status=str(data.get("status", "")),
            description=str(data.get("description", "") or ""),
        )


@dataclass
class CorrectionEvent:
    """A proposed change to a fact, introduced at a specific turn."""

    correction_id: str
    target_fact_id: str
    original_value: str
    proposed_value: str
    correction_type: str
    is_authoritative: bool
    turn_id: str
    expected_behavior: str
    explanation: str = ""

    @property
    def is_accepted(self) -> bool:
        """A correction should be adopted only when it is valid and authoritative."""
        return self.correction_type == CorrectionType.VALID and self.is_authoritative

    def to_dict(self) -> dict[str, Any]:
        return {
            "correction_id": self.correction_id,
            "target_fact_id": self.target_fact_id,
            "original_value": self.original_value,
            "proposed_value": self.proposed_value,
            "correction_type": self.correction_type,
            "is_authoritative": self.is_authoritative,
            "turn_id": self.turn_id,
            "expected_behavior": self.expected_behavior,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorrectionEvent:
        return cls(
            correction_id=str(data["correction_id"]),
            target_fact_id=str(data["target_fact_id"]),
            original_value=str(data.get("original_value", "")),
            proposed_value=str(data.get("proposed_value", "")),
            correction_type=str(data.get("correction_type", "")),
            is_authoritative=bool(data.get("is_authoritative", False)),
            turn_id=str(data.get("turn_id", "")),
            expected_behavior=str(data.get("expected_behavior", "")),
            explanation=str(data.get("explanation", "") or ""),
        )


@dataclass
class ConversationTurn:
    """One user turn of the scripted conversation."""

    turn_id: str
    order: int
    user_message: str
    event_type: str
    requires_response: bool = True
    correction_id: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "order": self.order,
            "user_message": self.user_message,
            "event_type": self.event_type,
            "requires_response": self.requires_response,
            "correction_id": self.correction_id,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationTurn:
        correction_id = data.get("correction_id")
        return cls(
            turn_id=str(data["turn_id"]),
            order=int(data["order"]),
            user_message=str(data.get("user_message", "")),
            event_type=str(data.get("event_type", "")),
            requires_response=bool(data.get("requires_response", True)),
            correction_id=str(correction_id) if correction_id not in (None, "") else None,
            notes=str(data.get("notes", "") or ""),
        )


@dataclass
class DependencyEdge:
    """Directed relationship: ``target`` depends on ``source``."""

    source_fact_id: str
    target_fact_id: str
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_fact_id": self.source_fact_id,
            "target_fact_id": self.target_fact_id,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyEdge:
        return cls(
            source_fact_id=str(data["source_fact_id"]),
            target_fact_id=str(data["target_fact_id"]),
            explanation=str(data.get("explanation", "") or ""),
        )


@dataclass
class Assertion:
    """A deterministic text check against one assistant response."""

    assertion_id: str
    turn_id: str
    dimension: str
    description: str
    operator: str
    expected_value: str
    weight: float = 1.0
    explanation: str = ""
    case_sensitive: bool = False
    boundary_match: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "turn_id": self.turn_id,
            "dimension": self.dimension,
            "description": self.description,
            "operator": self.operator,
            "expected_value": self.expected_value,
            "weight": self.weight,
            "explanation": self.explanation,
            "case_sensitive": self.case_sensitive,
            "boundary_match": self.boundary_match,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Assertion:
        return cls(
            assertion_id=str(data["assertion_id"]),
            turn_id=str(data.get("turn_id", "")),
            dimension=str(data.get("dimension", "")),
            description=str(data.get("description", "")),
            operator=str(data.get("operator", "")),
            expected_value=str(data.get("expected_value", "")),
            weight=float(data.get("weight", 1.0)),
            explanation=str(data.get("explanation", "") or ""),
            case_sensitive=bool(data.get("case_sensitive", False)),
            boundary_match=bool(data.get("boundary_match", True)),
        )


@dataclass
class ExpectedOutcome:
    """Human-readable statement of expected assistant behaviour."""

    outcome_id: str
    description: str
    dimension: str | None = None
    turn_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "description": self.description,
            "dimension": self.dimension,
            "turn_id": self.turn_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectedOutcome:
        dimension = data.get("dimension")
        turn_id = data.get("turn_id")
        return cls(
            outcome_id=str(data["outcome_id"]),
            description=str(data.get("description", "")),
            dimension=str(dimension) if dimension not in (None, "") else None,
            turn_id=str(turn_id) if turn_id not in (None, "") else None,
        )


@dataclass
class Scenario:
    """A complete, versioned evaluation scenario."""

    scenario_id: str
    title: str
    description: str
    category: str
    difficulty: str
    objective: str = ""
    tags: list[str] = field(default_factory=list)
    version: int = 1
    origin: str = ScenarioOrigin.CUSTOM
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    change_note: str = ""
    facts: list[Fact] = field(default_factory=list)
    corrections: list[CorrectionEvent] = field(default_factory=list)
    turns: list[ConversationTurn] = field(default_factory=list)
    dependencies: list[DependencyEdge] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    expected_outcomes: list[ExpectedOutcome] = field(default_factory=list)

    # -- convenience accessors ------------------------------------------------

    @property
    def ordered_turns(self) -> list[ConversationTurn]:
        return sorted(self.turns, key=lambda turn: turn.order)

    @property
    def response_turns(self) -> list[ConversationTurn]:
        """Turns for which an assistant response must be supplied."""
        return [turn for turn in self.ordered_turns if turn.requires_response]

    @property
    def dimensions(self) -> list[str]:
        """Dimensions covered by at least one assertion, in canonical order."""
        used = {assertion.dimension for assertion in self.assertions}
        return [dimension.value for dimension in Dimension if dimension.value in used]

    @property
    def is_demo(self) -> bool:
        return self.origin == ScenarioOrigin.DEMO

    def fact(self, fact_id: str) -> Fact | None:
        return next((fact for fact in self.facts if fact.fact_id == fact_id), None)

    def turn(self, turn_id: str) -> ConversationTurn | None:
        return next((turn for turn in self.turns if turn.turn_id == turn_id), None)

    def correction(self, correction_id: str) -> CorrectionEvent | None:
        return next((c for c in self.corrections if c.correction_id == correction_id), None)

    # -- serialisation ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "description": self.description,
            "objective": self.objective,
            "category": self.category,
            "difficulty": self.difficulty,
            "tags": list(self.tags),
            "version": self.version,
            "origin": self.origin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "change_note": self.change_note,
            "facts": [fact.to_dict() for fact in self.facts],
            "corrections": [correction.to_dict() for correction in self.corrections],
            "turns": [turn.to_dict() for turn in self.ordered_turns],
            "dependencies": [edge.to_dict() for edge in self.dependencies],
            "assertions": [assertion.to_dict() for assertion in self.assertions],
            "expected_outcomes": [outcome.to_dict() for outcome in self.expected_outcomes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        """Build a scenario from a dictionary that passed structural validation."""
        now = utc_now_iso()
        return cls(
            scenario_id=str(data["scenario_id"]),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            objective=str(data.get("objective", "") or ""),
            category=str(data.get("category", "")),
            difficulty=str(data.get("difficulty", "")),
            tags=[str(tag) for tag in data.get("tags", []) or []],
            version=int(data.get("version", 1)),
            origin=str(data.get("origin", ScenarioOrigin.CUSTOM)),
            created_at=str(data.get("created_at") or now),
            updated_at=str(data.get("updated_at") or now),
            change_note=str(data.get("change_note", "") or ""),
            facts=[Fact.from_dict(item) for item in data.get("facts", [])],
            corrections=[CorrectionEvent.from_dict(item) for item in data.get("corrections", [])],
            turns=[ConversationTurn.from_dict(item) for item in data.get("turns", [])],
            dependencies=[DependencyEdge.from_dict(item) for item in data.get("dependencies", [])],
            assertions=[Assertion.from_dict(item) for item in data.get("assertions", [])],
            expected_outcomes=[ExpectedOutcome.from_dict(item) for item in data.get("expected_outcomes", [])],
        )


@dataclass(frozen=True)
class FactHistoryEntry:
    """One historical value of a fact."""

    fact_id: str
    value: str
    source: str  # "initial" or "correction"
    turn_order: int | None
    correction_id: str | None
    correction_type: str | None
    accepted: bool


def build_fact_history(scenario: Scenario, fact_id: str) -> list[FactHistoryEntry]:
    """Return the complete value history of a fact, oldest first.

    Historical values are never erased: invalid and unverified proposals are
    kept in the history with ``accepted=False``.
    """
    fact = scenario.fact(fact_id)
    if fact is None:
        return []
    history = [
        FactHistoryEntry(
            fact_id=fact_id,
            value=fact.initial_value,
            source="initial",
            turn_order=None,
            correction_id=None,
            correction_type=None,
            accepted=True,
        )
    ]
    turn_orders = {turn.turn_id: turn.order for turn in scenario.turns}
    related = [c for c in scenario.corrections if c.target_fact_id == fact_id]
    related.sort(key=lambda c: turn_orders.get(c.turn_id, 10**9))
    for correction in related:
        history.append(
            FactHistoryEntry(
                fact_id=fact_id,
                value=correction.proposed_value,
                source="correction",
                turn_order=turn_orders.get(correction.turn_id),
                correction_id=correction.correction_id,
                correction_type=correction.correction_type,
                accepted=correction.is_accepted,
            )
        )
    return history


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


@dataclass
class AssertionResult:
    """Structured result of executing one assertion, with evidence."""

    assertion_id: str
    turn_id: str
    dimension: str
    operator: str
    expected_value: str
    weight: float
    status: str
    evidence: str
    description: str = ""
    actual_excerpt: str = ""
    error_message: str = ""
    evaluated_at: str = field(default_factory=utc_now_iso)

    @property
    def is_scored(self) -> bool:
        return self.status in (AssertionStatus.PASSED, AssertionStatus.FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "turn_id": self.turn_id,
            "dimension": self.dimension,
            "description": self.description,
            "operator": self.operator,
            "expected_value": self.expected_value,
            "weight": self.weight,
            "status": self.status,
            "evidence": self.evidence,
            "actual_excerpt": self.actual_excerpt,
            "error_message": self.error_message,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class HumanReview:
    """Subjective 0–4 rating of one dimension by a human reviewer."""

    dimension: str
    rating: int
    reviewer: str = ""
    reviewer_notes: str = ""
    evidence_notes: str = ""
    explanation: str = ""
    reviewed_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "rating": self.rating,
            "reviewer": self.reviewer,
            "reviewer_notes": self.reviewer_notes,
            "evidence_notes": self.evidence_notes,
            "explanation": self.explanation,
            "reviewed_at": self.reviewed_at,
        }


@dataclass
class DimensionScore:
    """Scores and counts for one dimension. ``None`` means unavailable."""

    dimension: str
    automated_score: float | None
    human_score: float | None
    combined_score: float | None
    evidence_type: str
    passed: int = 0
    failed: int = 0
    not_evaluated: int = 0
    errors: int = 0
    passed_weight: float = 0.0
    evaluated_weight: float = 0.0
    human_rating: int | None = None

    @property
    def is_assessed(self) -> bool:
        return self.evidence_type != EvidenceType.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "automated_score": self.automated_score,
            "human_score": self.human_score,
            "human_rating": self.human_rating,
            "combined_score": self.combined_score,
            "evidence_type": self.evidence_type,
            "passed": self.passed,
            "failed": self.failed,
            "not_evaluated": self.not_evaluated,
            "errors": self.errors,
            "passed_weight": self.passed_weight,
            "evaluated_weight": self.evaluated_weight,
        }


@dataclass
class ScoreSummary:
    """Aggregated scores for an evaluation session."""

    dimension_scores: dict[str, DimensionScore]
    overall_score: float | None
    coverage: float
    coverage_label: str
    assessed_dimensions: int
    passed: int
    failed: int
    not_evaluated: int
    errors: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "coverage": self.coverage,
            "coverage_label": self.coverage_label,
            "assessed_dimensions": self.assessed_dimensions,
            "assertion_counts": {
                "passed": self.passed,
                "failed": self.failed,
                "not_evaluated": self.not_evaluated,
                "error": self.errors,
            },
            "dimensions": {key: value.to_dict() for key, value in self.dimension_scores.items()},
        }


@dataclass
class EvaluationSession:
    """One evaluation of one AI system against one pinned scenario version."""

    evaluation_id: str
    ai_system: str
    model_label: str
    scenario_id: str
    scenario_version: int
    status: str = SessionStatus.DRAFT
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    evaluated_at: str | None = None
    completed_at: str | None = None
    notes: str = ""
    responses: dict[str, str] = field(default_factory=dict)
    assertion_results: list[AssertionResult] = field(default_factory=list)
    human_reviews: dict[str, HumanReview] = field(default_factory=dict)
    overall_score: float | None = None
    coverage: float | None = None

    @property
    def has_run(self) -> bool:
        """Whether automated assertions have been executed for the current responses."""
        return self.evaluated_at is not None

    def provided_response(self, turn_id: str) -> str | None:
        """Return the response text, or ``None`` if missing or blank."""
        text = self.responses.get(turn_id)
        if text is None or not text.strip():
            return None
        return text
