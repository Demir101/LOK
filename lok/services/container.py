"""Wiring of database, repositories and services (composition root)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lok.config import SEED_PATH
from lok.services.evaluation_service import EvaluationService
from lok.services.scenario_service import ScenarioService
from lok.storage.database import Database
from lok.storage.evaluation_repository import EvaluationRepository
from lok.storage.scenario_repository import ScenarioRepository


@dataclass
class AppServices:
    database: Database
    scenario_repo: ScenarioRepository
    evaluation_repo: EvaluationRepository
    scenarios: ScenarioService
    evaluations: EvaluationService
    seeded_on_start: int


def create_services(db_path: Path, seed_path: Path = SEED_PATH, seed: bool = True) -> AppServices:
    """Initialise the database (creating/migrating it) and seed missing demo scenarios."""
    database = Database(db_path)
    database.initialize()
    scenario_repo = ScenarioRepository(database)
    evaluation_repo = EvaluationRepository(database)
    scenarios = ScenarioService(scenario_repo)
    inserted = scenarios.seed_demo_scenarios(seed_path) if seed else 0
    return AppServices(
        database=database,
        scenario_repo=scenario_repo,
        evaluation_repo=evaluation_repo,
        scenarios=scenarios,
        evaluations=EvaluationService(scenario_repo, evaluation_repo),
        seeded_on_start=inserted,
    )
