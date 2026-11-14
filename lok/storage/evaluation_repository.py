"""Persistence of evaluation sessions, responses, results, reviews and scores."""

from __future__ import annotations

import sqlite3
from typing import Any

from lok.domain.models import (
    AssertionResult,
    DimensionScore,
    EvaluationSession,
    HumanReview,
    ScoreSummary,
    utc_now_iso,
)
from lok.storage.database import Database, DatabaseError


class EvaluationNotFoundError(LookupError):
    """Raised when an evaluation session does not exist."""


_SUMMARY_SELECT = """
SELECT e.evaluation_id, e.ai_system, e.model_label, e.scenario_id, e.scenario_version,
       v.title AS scenario_title, v.category AS scenario_category, e.status,
       e.created_at, e.updated_at, e.evaluated_at, e.completed_at,
       e.overall_score, e.coverage, e.notes,
       (SELECT COUNT(*) FROM assertion_results r
         WHERE r.evaluation_id = e.evaluation_id AND r.status = 'passed') AS passed,
       (SELECT COUNT(*) FROM assertion_results r
         WHERE r.evaluation_id = e.evaluation_id AND r.status = 'failed') AS failed,
       (SELECT COUNT(*) FROM assertion_results r
         WHERE r.evaluation_id = e.evaluation_id AND r.status = 'not_evaluated') AS not_evaluated,
       (SELECT COUNT(*) FROM assertion_results r
         WHERE r.evaluation_id = e.evaluation_id AND r.status = 'error') AS errors
FROM evaluation_sessions e
JOIN scenario_versions v ON v.scenario_id = e.scenario_id AND v.version = e.scenario_version
"""


class EvaluationRepository:
    """CRUD operations for evaluation sessions."""

    def __init__(self, database: Database):
        self.db = database

    # -- writes -----------------------------------------------------------------

    def insert(self, session: EvaluationSession) -> EvaluationSession:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO evaluation_sessions (evaluation_id, ai_system, model_label,"
                    " scenario_id, scenario_version, status, created_at, updated_at, evaluated_at,"
                    " completed_at, overall_score, coverage, notes)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session.evaluation_id,
                        session.ai_system,
                        session.model_label,
                        session.scenario_id,
                        session.scenario_version,
                        session.status,
                        session.created_at,
                        session.updated_at,
                        session.evaluated_at,
                        session.completed_at,
                        session.overall_score,
                        session.coverage,
                        session.notes,
                    ),
                )
                self._write_children(conn, session, None)
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"Could not create evaluation: {exc}") from exc
        return session

    def save(self, session: EvaluationSession, summary: ScoreSummary | None) -> EvaluationSession:
        """Persist the complete session state atomically."""
        session.updated_at = utc_now_iso()
        try:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    "UPDATE evaluation_sessions SET ai_system = ?, model_label = ?, status = ?,"
                    " updated_at = ?, evaluated_at = ?, completed_at = ?, overall_score = ?,"
                    " coverage = ?, notes = ? WHERE evaluation_id = ?",
                    (
                        session.ai_system,
                        session.model_label,
                        session.status,
                        session.updated_at,
                        session.evaluated_at,
                        session.completed_at,
                        session.overall_score,
                        session.coverage,
                        session.notes,
                        session.evaluation_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise EvaluationNotFoundError(session.evaluation_id)
                for table in (
                    "assistant_responses",
                    "assertion_results",
                    "human_reviews",
                    "dimension_scores",
                ):
                    conn.execute(
                        f"DELETE FROM {table} WHERE evaluation_id = ?",
                        (session.evaluation_id,),
                    )
                self._write_children(conn, session, summary)
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"Could not save evaluation '{session.evaluation_id}': {exc}") from exc
        return session

    @staticmethod
    def _write_children(
        conn: sqlite3.Connection, session: EvaluationSession, summary: ScoreSummary | None
    ) -> None:
        eid = session.evaluation_id
        now = utc_now_iso()
        conn.executemany(
            "INSERT INTO assistant_responses (evaluation_id, turn_id, response_text, updated_at)"
            " VALUES (?, ?, ?, ?)",
            [(eid, turn_id, text, now) for turn_id, text in session.responses.items()],
        )
        conn.executemany(
            "INSERT INTO assertion_results (evaluation_id, assertion_id, status, evidence,"
            " actual_excerpt, error_message, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (eid, r.assertion_id, r.status, r.evidence, r.actual_excerpt, r.error_message, r.evaluated_at)
                for r in session.assertion_results
            ],
        )
        conn.executemany(
            "INSERT INTO human_reviews (evaluation_id, dimension, rating, reviewer, reviewer_notes,"
            " evidence_notes, explanation, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    eid,
                    h.dimension,
                    h.rating,
                    h.reviewer,
                    h.reviewer_notes,
                    h.evidence_notes,
                    h.explanation,
                    h.reviewed_at,
                )
                for h in session.human_reviews.values()
            ],
        )
        if summary is not None:
            conn.executemany(
                "INSERT INTO dimension_scores (evaluation_id, dimension, automated_score, human_score,"
                " combined_score, evidence_type, passed, failed, not_evaluated, errors)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        eid,
                        d.dimension,
                        d.automated_score,
                        d.human_score,
                        d.combined_score,
                        d.evidence_type,
                        d.passed,
                        d.failed,
                        d.not_evaluated,
                        d.errors,
                    )
                    for d in summary.dimension_scores.values()
                ],
            )

    def delete(self, evaluation_id: str) -> None:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM evaluation_sessions WHERE evaluation_id = ?", (evaluation_id,))
            if cursor.rowcount == 0:
                raise EvaluationNotFoundError(evaluation_id)

    def delete_all(self) -> int:
        with self.db.transaction() as conn:
            return conn.execute("DELETE FROM evaluation_sessions").rowcount

    # -- reads ------------------------------------------------------------------

    def get(self, evaluation_id: str) -> EvaluationSession:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM evaluation_sessions WHERE evaluation_id = ?", (evaluation_id,)
            ).fetchone()
            if row is None:
                raise EvaluationNotFoundError(f"Evaluation '{evaluation_id}' does not exist.")
            responses = {
                r["turn_id"]: r["response_text"]
                for r in conn.execute(
                    "SELECT turn_id, response_text FROM assistant_responses WHERE evaluation_id = ?",
                    (evaluation_id,),
                )
            }
            results = [
                AssertionResult(
                    assertion_id=r["assertion_id"],
                    turn_id=r["turn_id"] or "",
                    dimension=r["dimension"] or "",
                    operator=r["operator"] or "",
                    expected_value=r["expected_value"] or "",
                    weight=float(r["weight"] or 0.0),
                    status=r["status"],
                    evidence=r["evidence"],
                    description=r["description"] or "",
                    actual_excerpt=r["actual_excerpt"],
                    error_message=r["error_message"],
                    evaluated_at=r["evaluated_at"],
                )
                for r in conn.execute(
                    "SELECT r.*, a.turn_id, a.dimension, a.operator, a.expected_value, a.weight,"
                    " a.description, a.position FROM assertion_results r"
                    " LEFT JOIN assertions a ON a.scenario_id = ? AND a.version = ?"
                    "  AND a.assertion_id = r.assertion_id"
                    " WHERE r.evaluation_id = ? ORDER BY a.position",
                    (row["scenario_id"], row["scenario_version"], evaluation_id),
                )
            ]
            reviews = {
                r["dimension"]: HumanReview(
                    dimension=r["dimension"],
                    rating=int(r["rating"]),
                    reviewer=r["reviewer"],
                    reviewer_notes=r["reviewer_notes"],
                    evidence_notes=r["evidence_notes"],
                    explanation=r["explanation"],
                    reviewed_at=r["reviewed_at"],
                )
                for r in conn.execute("SELECT * FROM human_reviews WHERE evaluation_id = ?", (evaluation_id,))
            }
        return EvaluationSession(
            evaluation_id=row["evaluation_id"],
            ai_system=row["ai_system"],
            model_label=row["model_label"],
            scenario_id=row["scenario_id"],
            scenario_version=int(row["scenario_version"]),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            evaluated_at=row["evaluated_at"],
            completed_at=row["completed_at"],
            notes=row["notes"],
            responses=responses,
            assertion_results=results,
            human_reviews=reviews,
            overall_score=row["overall_score"],
            coverage=row["coverage"],
        )

    def exists(self, evaluation_id: str) -> bool:
        with self.db.connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM evaluation_sessions WHERE evaluation_id = ?", (evaluation_id,)
                ).fetchone()
                is not None
            )

    def list_summaries(self) -> list[dict[str, Any]]:
        """All sessions with scenario title and assertion counts, newest first."""
        with self.db.connect() as conn:
            rows = conn.execute(_SUMMARY_SELECT + " ORDER BY e.updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def summary(self, evaluation_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(_SUMMARY_SELECT + " WHERE e.evaluation_id = ?", (evaluation_id,)).fetchone()
        if row is None:
            raise EvaluationNotFoundError(evaluation_id)
        return dict(row)

    def dimension_scores(self, evaluation_id: str | None = None) -> list[dict[str, Any]]:
        """Stored dimension scores, optionally for a single session."""
        sql = (
            "SELECT d.*, e.ai_system, e.model_label, e.scenario_id, e.status, e.updated_at"
            " FROM dimension_scores d JOIN evaluation_sessions e"
            " ON e.evaluation_id = d.evaluation_id"
        )
        params: tuple[Any, ...] = ()
        if evaluation_id is not None:
            sql += " WHERE d.evaluation_id = ?"
            params = (evaluation_id,)
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def assertion_status_counts(self) -> dict[str, int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM assertion_results GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def failures_by_scenario(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT e.scenario_id, v.title, COUNT(*) AS failed"
                " FROM assertion_results r"
                " JOIN evaluation_sessions e ON e.evaluation_id = r.evaluation_id"
                " JOIN scenario_versions v ON v.scenario_id = e.scenario_id"
                "  AND v.version = e.scenario_version"
                " WHERE r.status = 'failed' GROUP BY e.scenario_id, v.title ORDER BY failed DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def results_by_dimension(self) -> list[dict[str, Any]]:
        """Assertion result counts grouped by dimension and status."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT a.dimension, r.status, COUNT(*) AS n FROM assertion_results r"
                " JOIN evaluation_sessions e ON e.evaluation_id = r.evaluation_id"
                " JOIN assertions a ON a.scenario_id = e.scenario_id"
                "  AND a.version = e.scenario_version AND a.assertion_id = r.assertion_id"
                " GROUP BY a.dimension, r.status"
            ).fetchall()
        return [dict(row) for row in rows]

    def stored_dimension_score_objects(self, evaluation_id: str) -> dict[str, DimensionScore]:
        return {
            row["dimension"]: DimensionScore(
                dimension=row["dimension"],
                automated_score=row["automated_score"],
                human_score=row["human_score"],
                combined_score=row["combined_score"],
                evidence_type=row["evidence_type"],
                passed=row["passed"],
                failed=row["failed"],
                not_evaluated=row["not_evaluated"],
                errors=row["errors"],
            )
            for row in self.dimension_scores(evaluation_id)
        }
