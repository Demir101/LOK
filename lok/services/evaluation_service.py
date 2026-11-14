"""Evaluation session lifecycle: start, save responses, run assertions, review, complete.

All scoring goes through :mod:`lok.domain.scoring`; the UI never computes scores.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lok.domain.assertions import evaluate_assertions
from lok.domain.enums import Dimension, SessionStatus
from lok.domain.models import (
    ConversationTurn,
    EvaluationSession,
    HumanReview,
    Scenario,
    ScoreSummary,
    utc_now_iso,
)
from lok.domain.normalization import DEFAULT_POLICY, NormalizationPolicy
from lok.domain.scoring import ScoringError, compute_scores, human_rating_to_score
from lok.storage.evaluation_repository import EvaluationRepository
from lok.storage.scenario_repository import ScenarioRepository

MAX_LABEL_LENGTH = 120
MAX_RESPONSE_LENGTH = 100_000


class EvaluationInputError(ValueError):
    """Raised when user-supplied evaluation input is invalid."""


class EvaluationIncompleteError(RuntimeError):
    """Raised when completing a session that is missing required work."""

    def __init__(self, message: str, missing_turns: list[ConversationTurn] | None = None):
        super().__init__(message)
        self.missing_turns = missing_turns or []


@dataclass
class ReproducibilityReport:
    """Outcome of re-executing stored responses against the pinned scenario version."""

    reproducible: bool
    checked: int
    differences: list[str] = field(default_factory=list)


def new_evaluation_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"EV-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _clean_label(value: str, field_name: str) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        raise EvaluationInputError(f"{field_name} is required.")
    if len(cleaned) > MAX_LABEL_LENGTH:
        raise EvaluationInputError(f"{field_name} must be at most {MAX_LABEL_LENGTH} characters.")
    return cleaned


class EvaluationService:
    """Application service for evaluation sessions."""

    def __init__(
        self,
        scenarios: ScenarioRepository,
        evaluations: EvaluationRepository,
        policy: NormalizationPolicy = DEFAULT_POLICY,
    ):
        self.scenarios = scenarios
        self.evaluations = evaluations
        self.policy = policy

    # -- queries ------------------------------------------------------------------

    def get(self, evaluation_id: str) -> EvaluationSession:
        return self.evaluations.get(evaluation_id)

    def scenario_for(self, session: EvaluationSession) -> Scenario:
        """The exact scenario version the session is pinned to."""
        return self.scenarios.get(session.scenario_id, session.scenario_version)

    def list_summaries(self) -> list[dict]:
        return self.evaluations.list_summaries()

    @staticmethod
    def summarize(session: EvaluationSession) -> ScoreSummary:
        return compute_scores(session.assertion_results, session.human_reviews)

    @staticmethod
    def missing_responses(session: EvaluationSession, scenario: Scenario) -> list[ConversationTurn]:
        return [t for t in scenario.response_turns if session.provided_response(t.turn_id) is None]

    # -- commands -----------------------------------------------------------------

    def start(self, scenario_id: str, ai_system: str, model_label: str, notes: str = "") -> EvaluationSession:
        """Create a draft session pinned to the scenario's current version."""
        scenario = self.scenarios.get(scenario_id)
        session = EvaluationSession(
            evaluation_id=new_evaluation_id(),
            ai_system=_clean_label(ai_system, "AI system name"),
            model_label=_clean_label(model_label, "Model/version label"),
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.version,
            status=SessionStatus.DRAFT,
            notes=notes.strip(),
        )
        return self.evaluations.insert(session)

    def update_details(
        self, evaluation_id: str, ai_system: str, model_label: str, notes: str
    ) -> EvaluationSession:
        session = self.evaluations.get(evaluation_id)
        session.ai_system = _clean_label(ai_system, "AI system name")
        session.model_label = _clean_label(model_label, "Model/version label")
        session.notes = notes.strip()
        return self._persist(session)

    def save_responses(self, evaluation_id: str, responses: dict[str, str]) -> EvaluationSession:
        """Save assistant responses (a draft). Blank responses are stored as missing.

        If any response changes, previously executed assertion results no longer
        describe the stored responses; they are cleared and the evaluation must
        be run again. A completed session that changes returns to in progress.
        """
        session = self.evaluations.get(evaluation_id)
        scenario = self.scenario_for(session)
        allowed = {t.turn_id for t in scenario.response_turns}
        unknown = sorted(set(responses) - allowed)
        if unknown:
            raise EvaluationInputError(f"Responses for unknown or non-response turns: {', '.join(unknown)}.")
        cleaned: dict[str, str] = {}
        for turn_id, text in responses.items():
            if text is None or not str(text).strip():
                continue
            if len(text) > MAX_RESPONSE_LENGTH:
                raise EvaluationInputError(
                    f"Response for turn '{turn_id}' exceeds {MAX_RESPONSE_LENGTH:,} characters."
                )
            cleaned[turn_id] = str(text)
        if cleaned != session.responses:
            session.responses = cleaned
            session.assertion_results = []
            session.evaluated_at = None
            session.completed_at = None
            session.status = SessionStatus.IN_PROGRESS if cleaned else SessionStatus.DRAFT
        return self._persist(session)

    def run_evaluation(self, evaluation_id: str) -> tuple[EvaluationSession, ScoreSummary]:
        """Execute every assertion of the pinned scenario version against stored responses."""
        session = self.evaluations.get(evaluation_id)
        scenario = self.scenario_for(session)
        session.assertion_results = evaluate_assertions(
            scenario.assertions, scenario.turns, session.responses, self.policy
        )
        session.evaluated_at = utc_now_iso()
        if session.status == SessionStatus.DRAFT:
            session.status = SessionStatus.IN_PROGRESS
        session = self._persist(session)
        return session, self.summarize(session)

    def save_human_review(self, evaluation_id: str, review: HumanReview) -> EvaluationSession:
        if review.dimension not in {d.value for d in Dimension}:
            raise EvaluationInputError(f"Unsupported dimension '{review.dimension}'.")
        try:
            human_rating_to_score(review.rating)
        except ScoringError as exc:
            raise EvaluationInputError(str(exc)) from exc
        session = self.evaluations.get(evaluation_id)
        review.reviewed_at = utc_now_iso()
        session.human_reviews[review.dimension] = review
        if session.status == SessionStatus.DRAFT:
            session.status = SessionStatus.IN_PROGRESS
        return self._persist(session)

    def remove_human_review(self, evaluation_id: str, dimension: str) -> EvaluationSession:
        session = self.evaluations.get(evaluation_id)
        session.human_reviews.pop(dimension, None)
        return self._persist(session)

    def complete(self, evaluation_id: str) -> EvaluationSession:
        """Mark a session completed. Requires all responses and an up-to-date run."""
        session = self.evaluations.get(evaluation_id)
        scenario = self.scenario_for(session)
        missing = self.missing_responses(session, scenario)
        if missing:
            orders = ", ".join(str(t.order) for t in missing)
            raise EvaluationIncompleteError(
                f"Responses are missing for turn(s) {orders}. The evaluation stays incomplete.", missing
            )
        if not session.has_run:
            raise EvaluationIncompleteError("Run the evaluation before completing it.")
        session.status = SessionStatus.COMPLETED
        session.completed_at = utc_now_iso()
        return self._persist(session)

    def reopen(self, evaluation_id: str) -> EvaluationSession:
        session = self.evaluations.get(evaluation_id)
        session.status = SessionStatus.IN_PROGRESS if session.responses else SessionStatus.DRAFT
        session.completed_at = None
        return self._persist(session)

    def delete(self, evaluation_id: str) -> None:
        self.evaluations.delete(evaluation_id)

    def delete_all(self) -> int:
        return self.evaluations.delete_all()

    def verify_reproducibility(self, evaluation_id: str) -> ReproducibilityReport:
        """Re-run stored responses against the pinned version and compare outcomes."""
        session = self.evaluations.get(evaluation_id)
        if not session.has_run:
            return ReproducibilityReport(False, 0, ["The evaluation has not been run yet."])
        scenario = self.scenario_for(session)
        fresh = evaluate_assertions(scenario.assertions, scenario.turns, session.responses, self.policy)
        stored = {r.assertion_id: r for r in session.assertion_results}
        differences: list[str] = []
        for result in fresh:
            previous = stored.get(result.assertion_id)
            if previous is None:
                differences.append(f"{result.assertion_id}: no stored result.")
            elif previous.status != result.status:
                differences.append(f"{result.assertion_id}: stored {previous.status}, now {result.status}.")
        extra = set(stored) - {r.assertion_id for r in fresh}
        differences.extend(f"{aid}: stored result has no assertion definition." for aid in sorted(extra))
        stored_summary = self.summarize(session)
        if (
            session.overall_score is not None
            and stored_summary.overall_score is not None
            and (abs(session.overall_score - stored_summary.overall_score) > 1e-9)
        ):
            differences.append("Stored overall score differs from the recomputed score.")
        return ReproducibilityReport(not differences, len(fresh), differences)

    # -- internals ----------------------------------------------------------------

    def _persist(self, session: EvaluationSession) -> EvaluationSession:
        summary = self.summarize(session)
        session.overall_score = summary.overall_score
        session.coverage = summary.coverage
        return self.evaluations.save(session, summary)
