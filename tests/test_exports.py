import csv
import io
import json

import pytest

from lok.domain.models import HumanReview
from lok.services import reporting_service as reporting
from lok.services.evaluation_service import EvaluationService
from lok.services.scenario_service import ScenarioService
from lok.storage.evaluation_repository import EvaluationRepository
from lok.storage.scenario_repository import ScenarioRepository
from tests.conftest import make_scenario

UNICODE = "Der Termin ist am May 22 — Grüße, Łukasz 日本語 ✓"


@pytest.fixture
def env(db, scenario):
    repo = ScenarioRepository(db)
    ScenarioService(repo).create(scenario)
    svc = EvaluationService(repo, EvaluationRepository(db))
    session = svc.start(scenario.scenario_id, "Assistant Ü", "v1 «beta»")
    svc.save_responses(session.evaluation_id, {"t2": "Priya | owner", "t3": UNICODE})
    svc.run_evaluation(session.evaluation_id)
    svc.save_human_review(session.evaluation_id, HumanReview("context_preservation", 3, "Rev", "fine"))
    session = svc.get(session.evaluation_id)
    return svc, session, svc.scenario_for(session)


def read_csv(data: bytes) -> list[dict]:
    assert data.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def test_json_export_is_complete_and_versioned(env):
    _, session, scenario = env
    doc = json.loads(reporting.to_json(session, scenario))
    assert doc["format"] == "lok.evaluation_report"
    assert doc["schema_version"] == 1
    assert doc["ai_system"] == {"name": "Assistant Ü", "model_label": "v1 «beta»"}
    assert doc["scenario"]["version"] == 1
    assert {a["assertion_id"] for a in doc["assertions"]} == {"a1", "a2", "a3", "a4"}
    assert doc["scores"]["coverage"] == pytest.approx(80.0)
    assert doc["human_reviews"][0]["rating"] == 3
    assert doc["exported_at"]
    assert any(r["response"] == UNICODE for r in doc["responses"])


def test_json_export_marks_missing_responses_explicitly(env):
    _, session, scenario = env
    doc = reporting.build_report(session, scenario)
    t1 = next(r for r in doc["responses"] if r["turn_id"] == "t1")
    assert t1["response"] is None


def test_csv_exports(env):
    _, session, scenario = env
    rows = read_csv(reporting.assertions_csv(session, scenario))
    assert len(rows) == 4
    assert rows[0]["evaluation_id"] == session.evaluation_id
    assert rows[0]["ai_system"] == "Assistant Ü"
    dims = read_csv(reporting.dimensions_csv(session, scenario))
    assert len(dims) == 5
    fcr = next(r for r in dims if r["dimension"] == "false_correction_resistance")
    assert fcr["dimension_score"] == ""  # missing values stay empty, never 0
    assert fcr["evidence_type"] == "none"


def test_history_csv(env):
    svc, _, _ = env
    rows = read_csv(reporting.history_csv(svc.list_summaries()))
    assert len(rows) == 1
    assert rows[0]["scenario_title"] == "Deadline correction"


def test_markdown_report_sections_and_escaping(env):
    _, session, scenario = env
    md = reporting.to_markdown(session, scenario)
    for heading in (
        "# LOK — LOOK FOR IT",
        "## 1. Evaluation overview",
        "## 4. Dimension scores",
        "### Passed assertions",
        "### Failed assertions",
        "### Assertions not evaluated",
        "## 6. Human review",
        "## 8. Scoring methodology",
        "## 9. Limitations",
    ):
        assert heading in md
    assert "Not Assessed" in md
    assert UNICODE in md
    assert "No response provided." in md
    assert "subjective" in md


def test_empty_evaluation_exports(db, scenario):
    repo = ScenarioRepository(db)
    ScenarioService(repo).create(scenario)
    svc = EvaluationService(repo, EvaluationRepository(db))
    session = svc.start(scenario.scenario_id, "Sys", "v1")
    doc = reporting.build_report(session, svc.scenario_for(session))
    assert all(a["status"] == "not_run" for a in doc["assertions"])
    assert doc["scores"]["overall_score"] is None
    md = reporting.to_markdown(session, svc.scenario_for(session))
    assert "the evaluation has not been run" in md
    assert len(read_csv(reporting.assertions_csv(session, svc.scenario_for(session)))) == 4


def test_invalid_evaluation_data_rejected(env):
    _, session, _ = env
    with pytest.raises(reporting.ReportError):
        reporting.build_report(session, make_scenario("something-else"))
    wrong_version = make_scenario()
    wrong_version.version = 7
    with pytest.raises(reporting.ReportError):
        reporting.to_markdown(session, wrong_version)
