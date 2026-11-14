"""Versioned schema migrations.

The schema version is stored in ``PRAGMA user_version``. Each migration runs
once, in order, inside the initialisation transaction. To change the schema,
append a new ``(version, sql)`` entry — never edit an existing one.
"""

from __future__ import annotations

import sqlite3

_V1 = """
CREATE TABLE app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE scenarios (
    scenario_id     TEXT PRIMARY KEY,
    origin          TEXT NOT NULL CHECK (origin IN ('demo', 'custom')),
    current_version INTEGER NOT NULL CHECK (current_version >= 1),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE scenario_versions (
    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    version     INTEGER NOT NULL CHECK (version >= 1),
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    objective   TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL,
    difficulty  TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    change_note TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (scenario_id, version)
);

CREATE TABLE scenario_tags (
    scenario_id TEXT NOT NULL,
    version     INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    tag         TEXT NOT NULL,
    PRIMARY KEY (scenario_id, version, tag),
    FOREIGN KEY (scenario_id, version)
        REFERENCES scenario_versions(scenario_id, version) ON DELETE CASCADE
);

CREATE TABLE facts (
    scenario_id            TEXT NOT NULL,
    version                INTEGER NOT NULL,
    fact_id                TEXT NOT NULL,
    position               INTEGER NOT NULL,
    name                   TEXT NOT NULL,
    initial_value          TEXT NOT NULL,
    expected_current_value TEXT NOT NULL,
    status                 TEXT NOT NULL
        CHECK (status IN ('active', 'corrected', 'superseded', 'unverified')),
    description            TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (scenario_id, version, fact_id),
    FOREIGN KEY (scenario_id, version)
        REFERENCES scenario_versions(scenario_id, version) ON DELETE CASCADE
);

CREATE TABLE conversation_turns (
    scenario_id       TEXT NOT NULL,
    version           INTEGER NOT NULL,
    turn_id           TEXT NOT NULL,
    turn_order        INTEGER NOT NULL CHECK (turn_order >= 1),
    user_message      TEXT NOT NULL,
    event_type        TEXT NOT NULL CHECK (event_type IN (
        'initial_information', 'valid_correction', 'invalid_correction',
        'follow_up', 'verification_request')),
    correction_id     TEXT,
    requires_response INTEGER NOT NULL CHECK (requires_response IN (0, 1)),
    notes             TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (scenario_id, version, turn_id),
    UNIQUE (scenario_id, version, turn_order),
    FOREIGN KEY (scenario_id, version)
        REFERENCES scenario_versions(scenario_id, version) ON DELETE CASCADE,
    FOREIGN KEY (scenario_id, version, correction_id)
        REFERENCES correction_events(scenario_id, version, correction_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE correction_events (
    scenario_id       TEXT NOT NULL,
    version           INTEGER NOT NULL,
    correction_id     TEXT NOT NULL,
    position          INTEGER NOT NULL,
    target_fact_id    TEXT NOT NULL,
    original_value    TEXT NOT NULL,
    proposed_value    TEXT NOT NULL,
    correction_type   TEXT NOT NULL CHECK (correction_type IN ('valid', 'invalid', 'unverified')),
    is_authoritative  INTEGER NOT NULL CHECK (is_authoritative IN (0, 1)),
    turn_id           TEXT NOT NULL,
    expected_behavior TEXT NOT NULL,
    explanation       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (scenario_id, version, correction_id),
    FOREIGN KEY (scenario_id, version)
        REFERENCES scenario_versions(scenario_id, version) ON DELETE CASCADE,
    FOREIGN KEY (scenario_id, version, target_fact_id)
        REFERENCES facts(scenario_id, version, fact_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (scenario_id, version, turn_id)
        REFERENCES conversation_turns(scenario_id, version, turn_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE fact_dependencies (
    scenario_id    TEXT NOT NULL,
    version        INTEGER NOT NULL,
    source_fact_id TEXT NOT NULL,
    target_fact_id TEXT NOT NULL,
    position       INTEGER NOT NULL,
    explanation    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (scenario_id, version, source_fact_id, target_fact_id),
    CHECK (source_fact_id <> target_fact_id),
    FOREIGN KEY (scenario_id, version, source_fact_id)
        REFERENCES facts(scenario_id, version, fact_id) ON DELETE CASCADE,
    FOREIGN KEY (scenario_id, version, target_fact_id)
        REFERENCES facts(scenario_id, version, fact_id) ON DELETE CASCADE
);

CREATE TABLE assertions (
    scenario_id    TEXT NOT NULL,
    version        INTEGER NOT NULL,
    assertion_id   TEXT NOT NULL,
    position       INTEGER NOT NULL,
    turn_id        TEXT NOT NULL,
    dimension      TEXT NOT NULL CHECK (dimension IN (
        'correction_accuracy', 'false_correction_resistance', 'dependency_updates',
        'context_preservation', 'repeated_error_detection')),
    description    TEXT NOT NULL,
    operator       TEXT NOT NULL
        CHECK (operator IN ('contains', 'does_not_contain', 'equals', 'does_not_equal')),
    expected_value TEXT NOT NULL,
    weight         REAL NOT NULL CHECK (weight > 0),
    explanation    TEXT NOT NULL DEFAULT '',
    case_sensitive INTEGER NOT NULL DEFAULT 0 CHECK (case_sensitive IN (0, 1)),
    boundary_match INTEGER NOT NULL DEFAULT 1 CHECK (boundary_match IN (0, 1)),
    PRIMARY KEY (scenario_id, version, assertion_id),
    FOREIGN KEY (scenario_id, version, turn_id)
        REFERENCES conversation_turns(scenario_id, version, turn_id) ON DELETE CASCADE
);

CREATE TABLE expected_outcomes (
    scenario_id TEXT NOT NULL,
    version     INTEGER NOT NULL,
    outcome_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    description TEXT NOT NULL,
    dimension   TEXT,
    turn_id     TEXT,
    PRIMARY KEY (scenario_id, version, outcome_id),
    FOREIGN KEY (scenario_id, version)
        REFERENCES scenario_versions(scenario_id, version) ON DELETE CASCADE
);

CREATE TABLE evaluation_sessions (
    evaluation_id    TEXT PRIMARY KEY,
    ai_system        TEXT NOT NULL,
    model_label      TEXT NOT NULL,
    scenario_id      TEXT NOT NULL,
    scenario_version INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('draft', 'in_progress', 'completed')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    evaluated_at     TEXT,
    completed_at     TEXT,
    overall_score    REAL CHECK (overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)),
    coverage         REAL CHECK (coverage IS NULL OR (coverage >= 0 AND coverage <= 100)),
    notes            TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (scenario_id, scenario_version)
        REFERENCES scenario_versions(scenario_id, version) ON DELETE RESTRICT
);

CREATE TABLE assistant_responses (
    evaluation_id TEXT NOT NULL REFERENCES evaluation_sessions(evaluation_id) ON DELETE CASCADE,
    turn_id       TEXT NOT NULL,
    response_text TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (evaluation_id, turn_id)
);

CREATE TABLE assertion_results (
    evaluation_id  TEXT NOT NULL REFERENCES evaluation_sessions(evaluation_id) ON DELETE CASCADE,
    assertion_id   TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'not_evaluated', 'error')),
    evidence       TEXT NOT NULL,
    actual_excerpt TEXT NOT NULL DEFAULT '',
    error_message  TEXT NOT NULL DEFAULT '',
    evaluated_at   TEXT NOT NULL,
    PRIMARY KEY (evaluation_id, assertion_id)
);

CREATE TABLE human_reviews (
    evaluation_id  TEXT NOT NULL REFERENCES evaluation_sessions(evaluation_id) ON DELETE CASCADE,
    dimension      TEXT NOT NULL CHECK (dimension IN (
        'correction_accuracy', 'false_correction_resistance', 'dependency_updates',
        'context_preservation', 'repeated_error_detection')),
    rating         INTEGER NOT NULL CHECK (rating BETWEEN 0 AND 4),
    reviewer       TEXT NOT NULL DEFAULT '',
    reviewer_notes TEXT NOT NULL DEFAULT '',
    evidence_notes TEXT NOT NULL DEFAULT '',
    explanation    TEXT NOT NULL DEFAULT '',
    reviewed_at    TEXT NOT NULL,
    PRIMARY KEY (evaluation_id, dimension)
);

CREATE TABLE dimension_scores (
    evaluation_id   TEXT NOT NULL REFERENCES evaluation_sessions(evaluation_id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL,
    automated_score REAL,
    human_score     REAL,
    combined_score  REAL,
    evidence_type   TEXT NOT NULL CHECK (evidence_type IN ('automated', 'human', 'combined', 'none')),
    passed          INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    not_evaluated   INTEGER NOT NULL DEFAULT 0,
    errors          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (evaluation_id, dimension)
);

CREATE INDEX idx_versions_scenario ON scenario_versions(scenario_id);
CREATE INDEX idx_turns_order ON conversation_turns(scenario_id, version, turn_order);
CREATE INDEX idx_assertions_turn ON assertions(scenario_id, version, turn_id);
CREATE INDEX idx_sessions_scenario ON evaluation_sessions(scenario_id, scenario_version);
CREATE INDEX idx_sessions_updated ON evaluation_sessions(updated_at);
CREATE INDEX idx_sessions_status ON evaluation_sessions(status);
CREATE INDEX idx_sessions_ai_system ON evaluation_sessions(ai_system);
CREATE INDEX idx_results_status ON assertion_results(status);
"""

MIGRATIONS: list[tuple[int, str]] = [(1, _V1)]
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]


def current_schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def apply_migrations(connection: sqlite3.Connection) -> list[int]:
    """Apply pending migrations inside the caller's transaction."""
    current = current_schema_version(connection)
    if current > LATEST_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"Database schema version {current} is newer than this application supports "
            f"({LATEST_SCHEMA_VERSION})."
        )
    applied: list[int] = []
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        for statement in _split_statements(sql):
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        applied.append(version)
    return applied


def _split_statements(sql: str) -> list[str]:
    """Split a migration script on ';' (migration SQL contains no string literals with ';')."""
    return [part.strip() for part in sql.split(";") if part.strip()]
