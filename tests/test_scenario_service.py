import json

import pytest

from lok.config import SEED_PATH
from lok.domain.models import DependencyEdge
from lok.domain.validation import ScenarioValidationError, parse_scenario_dict, validate_scenario
from lok.services.import_export_service import (
    ScenarioImportError,
    apply_import,
    export_scenarios,
    preview_import,
)
from lok.services.scenario_service import (
    DuplicateScenarioError,
    ReadOnlyScenarioError,
    ScenarioFilter,
    ScenarioService,
    filter_scenarios,
)
from lok.storage.scenario_repository import ScenarioRepository
from tests.conftest import make_scenario

MAX = 2 * 1024 * 1024


@pytest.fixture
def service(db):
    return ScenarioService(ScenarioRepository(db))


def test_create_scenario(service, scenario):
    created, warnings = service.create(scenario)
    assert created.version == 1
    assert created.origin == "custom"
    assert warnings == []
    assert service.get(scenario.scenario_id).title == scenario.title


def test_create_rejects_duplicate_id(service, scenario):
    service.create(scenario)
    with pytest.raises(DuplicateScenarioError):
        service.create(make_scenario())


def test_create_rejects_invalid_scenario_and_keeps_input(service, scenario):
    scenario.dependencies.append(DependencyEdge("reminder", "deadline"))
    with pytest.raises(ScenarioValidationError):
        service.create(scenario)
    assert not service.exists(scenario.scenario_id)
    assert len(scenario.dependencies) == 2  # caller's object untouched


def test_edit_creates_new_version(service, scenario):
    service.create(scenario)
    scenario.description = "Changed description"
    updated, _ = service.update(scenario, "clarified")
    assert updated.version == 2
    assert updated.change_note == "clarified"
    assert service.get(scenario.scenario_id, 1).description != "Changed description"


def test_demo_scenarios_are_read_only(service):
    service.seed_demo_scenarios(SEED_PATH)
    demo = service.get("demo-project-release-deadline")
    with pytest.raises(ReadOnlyScenarioError):
        service.update(demo)
    with pytest.raises(ReadOnlyScenarioError):
        service.delete(demo.scenario_id)


def test_duplicate_creates_editable_copy(service):
    service.seed_demo_scenarios(SEED_PATH)
    copy_ = service.duplicate("demo-project-release-deadline")
    assert copy_.origin == "custom"
    assert copy_.version == 1
    assert copy_.scenario_id != "demo-project-release-deadline"
    service.update(copy_, "edit allowed")


def test_seed_has_at_least_15_valid_scenarios_and_is_idempotent(service):
    assert service.seed_demo_scenarios(SEED_PATH) >= 15
    first_count = len(service.list_scenarios())
    assert service.seed_demo_scenarios(SEED_PATH) == 0
    assert len(service.list_scenarios()) == first_count
    for scenario in service.list_scenarios():
        assert scenario.is_demo
        assert "Synthetic" in scenario.description
        assert not [i for i in validate_scenario(scenario) if i.severity == "error"]


def test_seed_covers_all_dimensions_and_required_patterns():
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))["scenarios"]
    scenarios = [parse_scenario_dict(item) for item in raw]
    covered = {d for s in scenarios for d in s.dimensions}
    assert len(covered) == 5
    assert any(len(s.corrections) >= 2 for s in scenarios)
    assert any(s.dependencies and any(f.status == "active" for f in s.facts) for s in scenarios)
    assert any(len(s.turns) >= 8 for s in scenarios)
    assert len({s.category for s in scenarios}) >= 15


def test_filtering(service):
    service.seed_demo_scenarios(SEED_PATH)
    scenarios = service.list_scenarios()
    assert (
        filter_scenarios(scenarios, ScenarioFilter(query="VLAN"))[0].scenario_id == "demo-network-vlan-subnet"
    )
    hard = filter_scenarios(scenarios, ScenarioFilter(difficulties=["hard"]))
    assert hard and all(s.difficulty == "hard" for s in hard)
    fcr = filter_scenarios(scenarios, ScenarioFilter(dimensions=["false_correction_resistance"]))
    assert all("false_correction_resistance" in s.dimensions for s in fcr)
    tagged = filter_scenarios(scenarios, ScenarioFilter(tags=["ip-address"]))
    assert {s.scenario_id for s in tagged} == {"demo-server-ip-unverified", "demo-network-vlan-subnet"}


def test_valid_import_and_export_round_trip(db, service, scenario):
    repo = ScenarioRepository(db)
    payload = export_scenarios([scenario])
    preview = preview_import(payload, repo, MAX)
    assert not preview.has_errors
    report = apply_import(preview, repo, replace_existing=False)
    assert report.created == [scenario.scenario_id]
    assert service.get(scenario.scenario_id).assertions[0].expected_value == "May 22"


def test_import_conflict_requires_confirmation_and_creates_version(db, service, scenario):
    repo = ScenarioRepository(db)
    service.create(scenario)
    preview = preview_import(export_scenarios([scenario]), repo, MAX)
    assert preview.conflicts
    with pytest.raises(ScenarioImportError):
        apply_import(preview, repo, replace_existing=False)
    assert service.get(scenario.scenario_id).version == 1
    report = apply_import(preview, repo, replace_existing=True)
    assert report.new_versions == [scenario.scenario_id]
    assert service.get(scenario.scenario_id).version == 2


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ("{not json", "Malformed JSON"),
        ("", "empty"),
        ('{"format": "other", "schema_version": 1, "scenarios": []}', "Unsupported file format"),
        ('{"format": "lok.scenarios", "schema_version": 99, "scenarios": [{}]}', "schema_version"),
        ("[1, 2, 3]", "JSON object"),
    ],
)
def test_invalid_import_files(db, payload, fragment):
    preview = preview_import(payload, ScenarioRepository(db), MAX)
    assert preview.has_errors
    assert any(fragment in error for error in preview.file_errors)


def test_import_rejects_invalid_scenarios_atomically(db, scenario):
    repo = ScenarioRepository(db)
    bad = make_scenario("bad-one")
    bad.assertions[0].operator = "fuzzy"
    preview = preview_import(export_scenarios([make_scenario("good-one"), bad]), repo, MAX)
    assert preview.has_errors
    with pytest.raises(ScenarioImportError):
        apply_import(preview, repo, replace_existing=True)
    assert not repo.exists("good-one")


def test_import_size_limit(db, scenario):
    preview = preview_import(export_scenarios([scenario]), ScenarioRepository(db), max_bytes=100)
    assert any("maximum accepted size" in e for e in preview.file_errors)


def test_import_cannot_replace_demo(db, service):
    service.seed_demo_scenarios(SEED_PATH)
    repo = ScenarioRepository(db)
    demo = service.get("demo-ops-incident-severity")
    preview = preview_import(export_scenarios([demo]), repo, MAX)
    assert preview.has_errors
    assert "read-only demo" in str(preview.candidates[0].errors[-1])


def test_import_duplicate_ids_in_file(db, scenario):
    preview = preview_import(export_scenarios([scenario, make_scenario()]), ScenarioRepository(db), MAX)
    assert preview.has_errors
