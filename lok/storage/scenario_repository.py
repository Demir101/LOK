"""Persistence of versioned scenarios.

Scenario versions are immutable once written: an edit always creates a new
version row set. Evaluation sessions reference ``(scenario_id, version)`` so
their scenario definition and assertion rules can never change underneath them.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lok.domain.models import (
    Assertion,
    ConversationTurn,
    CorrectionEvent,
    DependencyEdge,
    ExpectedOutcome,
    Fact,
    Scenario,
    utc_now_iso,
)
from lok.storage.database import Database, DatabaseError


class ScenarioNotFoundError(LookupError):
    """Raised when a scenario or scenario version does not exist."""


class ScenarioInUseError(RuntimeError):
    """Raised when deleting a scenario that evaluation sessions still reference."""


class ScenarioRepository:
    """CRUD operations for scenarios and their immutable versions."""

    def __init__(self, database: Database):
        self.db = database

    # -- writes -----------------------------------------------------------------

    def insert_new(self, scenario: Scenario) -> Scenario:
        """Insert a brand-new scenario with its first version."""
        self.insert_many(new=[scenario], versions=[])
        return scenario

    def insert_version(self, scenario: Scenario) -> Scenario:
        """Store ``scenario`` as the next version of an existing scenario.

        The version number is assigned here (current + 1); the caller's value
        is overwritten so versions stay strictly sequential.
        """
        self.insert_many(new=[], versions=[scenario])
        return scenario

    def insert_many(self, new: list[Scenario], versions: list[Scenario]) -> None:
        """Insert new scenarios and new versions in a single all-or-nothing transaction."""
        current_id = ""
        try:
            with self.db.transaction() as conn:
                for scenario in new:
                    current_id = scenario.scenario_id
                    self._insert_new(conn, scenario)
                for scenario in versions:
                    current_id = scenario.scenario_id
                    self._insert_next_version(conn, scenario)
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f"Could not save scenario '{current_id}': {exc}") from exc

    def _insert_new(self, conn: sqlite3.Connection, scenario: Scenario) -> None:
        if self._exists(conn, scenario.scenario_id):
            raise DatabaseError(f"Scenario '{scenario.scenario_id}' already exists.")
        conn.execute(
            "INSERT INTO scenarios (scenario_id, origin, current_version, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                scenario.scenario_id,
                scenario.origin,
                scenario.version,
                scenario.created_at,
                scenario.updated_at,
            ),
        )
        self._insert_version_rows(conn, scenario)

    def _insert_next_version(self, conn: sqlite3.Connection, scenario: Scenario) -> None:
        row = conn.execute(
            "SELECT current_version, created_at FROM scenarios WHERE scenario_id = ?",
            (scenario.scenario_id,),
        ).fetchone()
        if row is None:
            raise ScenarioNotFoundError(f"Scenario '{scenario.scenario_id}' does not exist.")
        scenario.version = int(row["current_version"]) + 1
        scenario.created_at = row["created_at"]
        scenario.updated_at = utc_now_iso()
        self._insert_version_rows(conn, scenario)
        conn.execute(
            "UPDATE scenarios SET current_version = ?, updated_at = ? WHERE scenario_id = ?",
            (scenario.version, scenario.updated_at, scenario.scenario_id),
        )

    def origin_of(self, scenario_id: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT origin FROM scenarios WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()
        return None if row is None else str(row["origin"])

    def delete(self, scenario_id: str) -> None:
        """Delete a scenario and all versions. Refuses if evaluations reference it."""
        with self.db.transaction() as conn:
            if not self._exists(conn, scenario_id):
                raise ScenarioNotFoundError(scenario_id)
            used = conn.execute(
                "SELECT COUNT(*) FROM evaluation_sessions WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()[0]
            if used:
                raise ScenarioInUseError(
                    f"Scenario '{scenario_id}' is referenced by {used} evaluation session(s). "
                    "Delete those evaluations first to preserve historical integrity."
                )
            conn.execute("DELETE FROM scenarios WHERE scenario_id = ?", (scenario_id,))

    @staticmethod
    def _insert_version_rows(conn: sqlite3.Connection, s: Scenario) -> None:
        key = (s.scenario_id, s.version)
        conn.execute(
            "INSERT INTO scenario_versions (scenario_id, version, title, description, objective,"
            " category, difficulty, change_note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *key,
                s.title,
                s.description,
                s.objective,
                s.category,
                s.difficulty,
                s.change_note,
                s.updated_at,
            ),
        )
        conn.executemany(
            "INSERT INTO scenario_tags (scenario_id, version, position, tag) VALUES (?, ?, ?, ?)",
            [(*key, pos, tag) for pos, tag in enumerate(dict.fromkeys(s.tags))],
        )
        conn.executemany(
            "INSERT INTO facts (scenario_id, version, fact_id, position, name, initial_value,"
            " expected_current_value, status, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    *key,
                    f.fact_id,
                    pos,
                    f.name,
                    f.initial_value,
                    f.expected_current_value,
                    f.status,
                    f.description,
                )
                for pos, f in enumerate(s.facts)
            ],
        )
        conn.executemany(
            "INSERT INTO conversation_turns (scenario_id, version, turn_id, turn_order, user_message,"
            " event_type, correction_id, requires_response, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    *key,
                    t.turn_id,
                    t.order,
                    t.user_message,
                    t.event_type,
                    t.correction_id,
                    int(t.requires_response),
                    t.notes,
                )
                for t in s.turns
            ],
        )
        conn.executemany(
            "INSERT INTO correction_events (scenario_id, version, correction_id, position,"
            " target_fact_id, original_value, proposed_value, correction_type, is_authoritative,"
            " turn_id, expected_behavior, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    *key,
                    c.correction_id,
                    pos,
                    c.target_fact_id,
                    c.original_value,
                    c.proposed_value,
                    c.correction_type,
                    int(c.is_authoritative),
                    c.turn_id,
                    c.expected_behavior,
                    c.explanation,
                )
                for pos, c in enumerate(s.corrections)
            ],
        )
        conn.executemany(
            "INSERT INTO fact_dependencies (scenario_id, version, source_fact_id, target_fact_id,"
            " position, explanation) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (*key, d.source_fact_id, d.target_fact_id, pos, d.explanation)
                for pos, d in enumerate(s.dependencies)
            ],
        )
        conn.executemany(
            "INSERT INTO assertions (scenario_id, version, assertion_id, position, turn_id, dimension,"
            " description, operator, expected_value, weight, explanation, case_sensitive,"
            " boundary_match) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    *key,
                    a.assertion_id,
                    pos,
                    a.turn_id,
                    a.dimension,
                    a.description,
                    a.operator,
                    a.expected_value,
                    float(a.weight),
                    a.explanation,
                    int(a.case_sensitive),
                    int(a.boundary_match),
                )
                for pos, a in enumerate(s.assertions)
            ],
        )
        conn.executemany(
            "INSERT INTO expected_outcomes (scenario_id, version, outcome_id, position, description,"
            " dimension, turn_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (*key, o.outcome_id, pos, o.description, o.dimension, o.turn_id)
                for pos, o in enumerate(s.expected_outcomes)
            ],
        )

    # -- reads ------------------------------------------------------------------

    @staticmethod
    def _exists(conn: sqlite3.Connection, scenario_id: str) -> bool:
        return (
            conn.execute("SELECT 1 FROM scenarios WHERE scenario_id = ?", (scenario_id,)).fetchone()
            is not None
        )

    def exists(self, scenario_id: str) -> bool:
        with self.db.connect() as conn:
            return self._exists(conn, scenario_id)

    def get(self, scenario_id: str, version: int | None = None) -> Scenario:
        """Load a scenario version (latest when ``version`` is ``None``)."""
        with self.db.connect() as conn:
            return self._load(conn, scenario_id, version)

    def list_latest(self) -> list[Scenario]:
        """Load the latest version of every scenario, ordered by title."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT s.scenario_id FROM scenarios s JOIN scenario_versions v"
                " ON v.scenario_id = s.scenario_id AND v.version = s.current_version"
                " ORDER BY v.title COLLATE NOCASE"
            ).fetchall()
            return [self._load(conn, row["scenario_id"], None) for row in rows]

    def list_versions(self, scenario_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT v.version, v.title, v.change_note, v.created_at,"
                " (SELECT COUNT(*) FROM evaluation_sessions e WHERE e.scenario_id = v.scenario_id"
                "  AND e.scenario_version = v.version) AS evaluations"
                " FROM scenario_versions v WHERE v.scenario_id = ? ORDER BY v.version DESC",
                (scenario_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0])

    def evaluation_count(self, scenario_id: str) -> int:
        with self.db.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM evaluation_sessions WHERE scenario_id = ?", (scenario_id,)
                ).fetchone()[0]
            )

    def _load(self, conn: sqlite3.Connection, scenario_id: str, version: int | None) -> Scenario:
        head = conn.execute(
            "SELECT origin, current_version, created_at FROM scenarios WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchone()
        if head is None:
            raise ScenarioNotFoundError(f"Scenario '{scenario_id}' does not exist.")
        version = int(head["current_version"]) if version is None else int(version)
        key = (scenario_id, version)
        meta = conn.execute(
            "SELECT * FROM scenario_versions WHERE scenario_id = ? AND version = ?", key
        ).fetchone()
        if meta is None:
            raise ScenarioNotFoundError(f"Scenario '{scenario_id}' has no version {version}.")

        def rows(sql: str) -> list[sqlite3.Row]:
            return conn.execute(sql, key).fetchall()

        where = "WHERE scenario_id = ? AND version = ?"
        return Scenario(
            scenario_id=scenario_id,
            title=meta["title"],
            description=meta["description"],
            objective=meta["objective"],
            category=meta["category"],
            difficulty=meta["difficulty"],
            tags=[r["tag"] for r in rows(f"SELECT tag FROM scenario_tags {where} ORDER BY position")],
            version=version,
            origin=head["origin"],
            created_at=head["created_at"],
            updated_at=meta["created_at"],
            change_note=meta["change_note"],
            facts=[
                Fact(
                    r["fact_id"],
                    r["name"],
                    r["initial_value"],
                    r["expected_current_value"],
                    r["status"],
                    r["description"],
                )
                for r in rows(f"SELECT * FROM facts {where} ORDER BY position")
            ],
            corrections=[
                CorrectionEvent(
                    r["correction_id"],
                    r["target_fact_id"],
                    r["original_value"],
                    r["proposed_value"],
                    r["correction_type"],
                    bool(r["is_authoritative"]),
                    r["turn_id"],
                    r["expected_behavior"],
                    r["explanation"],
                )
                for r in rows(f"SELECT * FROM correction_events {where} ORDER BY position")
            ],
            turns=[
                ConversationTurn(
                    r["turn_id"],
                    r["turn_order"],
                    r["user_message"],
                    r["event_type"],
                    bool(r["requires_response"]),
                    r["correction_id"],
                    r["notes"],
                )
                for r in rows(f"SELECT * FROM conversation_turns {where} ORDER BY turn_order")
            ],
            dependencies=[
                DependencyEdge(r["source_fact_id"], r["target_fact_id"], r["explanation"])
                for r in rows(f"SELECT * FROM fact_dependencies {where} ORDER BY position")
            ],
            assertions=[
                Assertion(
                    r["assertion_id"],
                    r["turn_id"],
                    r["dimension"],
                    r["description"],
                    r["operator"],
                    r["expected_value"],
                    r["weight"],
                    r["explanation"],
                    bool(r["case_sensitive"]),
                    bool(r["boundary_match"]),
                )
                for r in rows(f"SELECT * FROM assertions {where} ORDER BY position")
            ],
            expected_outcomes=[
                ExpectedOutcome(r["outcome_id"], r["description"], r["dimension"], r["turn_id"])
                for r in rows(f"SELECT * FROM expected_outcomes {where} ORDER BY position")
            ],
        )

    # -- application metadata ---------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
