import sqlite3

import pytest

from lok.domain.models import EvaluationSession
from lok.storage.database import Database
from lok.storage.evaluation_repository import EvaluationNotFoundError, EvaluationRepository
from lok.storage.migrations import LATEST_SCHEMA_VERSION
from lok.storage.scenario_repository import (
    ScenarioInUseError,
    ScenarioNotFoundError,
    ScenarioRepository,
)
from tests.conftest import make_scenario


def test_initialization_creates_schema(db):
    assert db.schema_version() == LATEST_SCHEMA_VERSION
    with db.connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in (
        "scenarios",
        "scenario_versions",
        "facts",
        "correction_events",
        "conversation_turns",
        "fact_dependencies",
        "assertions",
        "evaluation_sessions",
        "assistant_responses",
        "assertion_results",
        "human_reviews",
    ):
        assert table in tables


def test_initialization_is_idempotent(db):
    assert db.initialize() == LATEST_SCHEMA_VERSION
    assert db.initialize() == LATEST_SCHEMA_VERSION


def test_foreign_keys_enforced(db):
    with db.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute(
            "INSERT INTO evaluation_sessions (evaluation_id, ai_system, model_label, scenario_id,"
            " scenario_version, status, created_at, updated_at) VALUES"
            " ('e1', 'x', 'y', 'missing', 1, 'draft', 'now', 'now')"
        )


def test_create_and_read_scenario(db, scenario):
    repo = ScenarioRepository(db)
    repo.insert_new(scenario)
    loaded = repo.get(scenario.scenario_id)
    assert loaded.to_dict() == scenario.to_dict()


def test_update_creates_new_version_and_preserves_old(db, scenario):
    repo = ScenarioRepository(db)
    repo.insert_new(scenario)
    edited = make_scenario()
    edited.title = "Edited title"
    edited.assertions[0].expected_value = "May 23"
    repo.insert_version(edited)
    assert edited.version == 2
    assert repo.get(scenario.scenario_id).title == "Edited title"
    old = repo.get(scenario.scenario_id, 1)
    assert old.title == "Deadline correction"
    assert old.assertions[0].expected_value == "May 22"
    assert [v["version"] for v in repo.list_versions(scenario.scenario_id)] == [2, 1]


def test_delete_scenario(db, scenario):
    repo = ScenarioRepository(db)
    repo.insert_new(scenario)
    repo.delete(scenario.scenario_id)
    assert not repo.exists(scenario.scenario_id)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
    with pytest.raises(ScenarioNotFoundError):
        repo.get(scenario.scenario_id)


def test_delete_refused_when_evaluations_exist(db, scenario):
    repo, evals = ScenarioRepository(db), EvaluationRepository(db)
    repo.insert_new(scenario)
    evals.insert(EvaluationSession("e1", "Sys", "v1", scenario.scenario_id, 1))
    with pytest.raises(ScenarioInUseError):
        repo.delete(scenario.scenario_id)
    assert repo.exists(scenario.scenario_id)


def test_transaction_rolls_back_on_error(db, scenario):
    repo = ScenarioRepository(db)
    broken = make_scenario("broken")
    broken.assertions[0].turn_id = "does-not-exist"  # violates FK
    with pytest.raises(Exception):  # noqa: B017 - any failure must roll back
        repo.insert_many(new=[make_scenario("ok-one"), broken], versions=[])
    assert not repo.exists("ok-one")
    assert not repo.exists("broken")


def test_evaluation_crud_and_persistence(tmp_path, scenario):
    path = tmp_path / "persist.db"
    db = Database(path)
    db.initialize()
    ScenarioRepository(db).insert_new(scenario)
    evals = EvaluationRepository(db)
    session = EvaluationSession("e1", "Sys", "v1", scenario.scenario_id, 1, responses={"t3": "May 22"})
    evals.insert(session)
    session.notes = "updated"
    evals.save(session, None)

    reopened = EvaluationRepository(Database(path))  # new connection, same file
    loaded = reopened.get("e1")
    assert loaded.notes == "updated"
    assert loaded.responses == {"t3": "May 22"}
    assert [row["evaluation_id"] for row in reopened.list_summaries()] == ["e1"]

    reopened.delete("e1")
    with pytest.raises(EvaluationNotFoundError):
        reopened.get("e1")


def test_evaluation_children_cascade_on_delete(db, scenario):
    ScenarioRepository(db).insert_new(scenario)
    evals = EvaluationRepository(db)
    evals.insert(EvaluationSession("e1", "Sys", "v1", scenario.scenario_id, 1, responses={"t3": "x"}))
    evals.delete("e1")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assistant_responses").fetchone()[0] == 0


def test_check_constraints_reject_invalid_values(db, scenario):
    ScenarioRepository(db).insert_new(scenario)
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute(
            "UPDATE assertions SET weight = 0 WHERE scenario_id = ? AND assertion_id = 'a1'",
            (scenario.scenario_id,),
        )


def test_meta_round_trip(db):
    repo = ScenarioRepository(db)
    assert repo.get_meta("x") is None
    repo.set_meta("x", "1")
    repo.set_meta("x", "2")
    assert repo.get_meta("x") == "2"
