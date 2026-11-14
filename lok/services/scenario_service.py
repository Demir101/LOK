"""Scenario use cases: listing, filtering, creation, versioned editing, duplication, seeding."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from lok.domain.enums import ScenarioOrigin
from lok.domain.models import Scenario, utc_now_iso
from lok.domain.validation import (
    ScenarioValidationError,
    ValidationIssue,
    ensure_valid,
    parse_scenario_dict,
)
from lok.storage.scenario_repository import ScenarioNotFoundError, ScenarioRepository

SEED_META_KEY = "demo_seed_version"


class ReadOnlyScenarioError(PermissionError):
    """Raised when trying to edit or delete a read-only demo scenario."""


class DuplicateScenarioError(ValueError):
    """Raised when creating a scenario whose ID already exists."""


@dataclass
class ScenarioFilter:
    """Criteria for the Scenario Library. Empty criteria match everything."""

    query: str = ""
    categories: list[str] = field(default_factory=list)
    difficulties: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)

    def matches(self, scenario: Scenario) -> bool:
        query = self.query.strip().casefold()
        if (
            query
            and query not in scenario.title.casefold()
            and query not in (scenario.description.casefold())
        ):
            return False
        if self.categories and scenario.category not in self.categories:
            return False
        if self.difficulties and scenario.difficulty not in self.difficulties:
            return False
        if self.dimensions and not set(self.dimensions) & set(scenario.dimensions):
            return False
        if self.tags and not set(self.tags) & set(scenario.tags):
            return False
        return not (self.origins and scenario.origin not in self.origins)


def filter_scenarios(scenarios: Iterable[Scenario], criteria: ScenarioFilter) -> list[Scenario]:
    return [scenario for scenario in scenarios if criteria.matches(scenario)]


class ScenarioService:
    """Application service for scenarios."""

    def __init__(self, repository: ScenarioRepository):
        self.repo = repository

    # -- queries ------------------------------------------------------------------

    def list_scenarios(self) -> list[Scenario]:
        return self.repo.list_latest()

    def get(self, scenario_id: str, version: int | None = None) -> Scenario:
        return self.repo.get(scenario_id, version)

    def versions(self, scenario_id: str) -> list[dict]:
        return self.repo.list_versions(scenario_id)

    def exists(self, scenario_id: str) -> bool:
        return self.repo.exists(scenario_id)

    def evaluation_count(self, scenario_id: str) -> int:
        return self.repo.evaluation_count(scenario_id)

    def suggest_id(self, base: str) -> str:
        """Return an unused, valid scenario ID derived from ``base``."""
        slug = re.sub(r"[^a-z0-9]+", "-", base.casefold()).strip("-")[:50] or "scenario"
        candidate, counter = slug, 2
        while self.repo.exists(candidate):
            candidate = f"{slug}-{counter}"
            counter += 1
        return candidate

    # -- commands -----------------------------------------------------------------

    def create(self, scenario: Scenario) -> tuple[Scenario, list[ValidationIssue]]:
        """Validate and store a new custom scenario as version 1."""
        candidate = copy.deepcopy(scenario)
        candidate.origin = ScenarioOrigin.CUSTOM
        candidate.version = 1
        candidate.created_at = candidate.updated_at = utc_now_iso()
        warnings = ensure_valid(candidate)
        if self.repo.exists(candidate.scenario_id):
            raise DuplicateScenarioError(f"A scenario with ID '{candidate.scenario_id}' already exists.")
        self.repo.insert_new(candidate)
        return candidate, warnings

    def update(self, scenario: Scenario, change_note: str = "") -> tuple[Scenario, list[ValidationIssue]]:
        """Store an edited scenario as a new immutable version.

        Previous versions — and every evaluation pinned to them — stay untouched.
        """
        origin = self.repo.origin_of(scenario.scenario_id)
        if origin is None:
            raise ScenarioNotFoundError(f"Scenario '{scenario.scenario_id}' does not exist.")
        if origin == ScenarioOrigin.DEMO:
            raise ReadOnlyScenarioError(
                "Demo scenarios are read-only. Duplicate the scenario to create an editable copy."
            )
        candidate = copy.deepcopy(scenario)
        candidate.origin = ScenarioOrigin.CUSTOM
        candidate.change_note = change_note.strip()
        warnings = ensure_valid(candidate)
        self.repo.insert_version(candidate)
        return candidate, warnings

    def duplicate(
        self, scenario_id: str, new_id: str | None = None, new_title: str | None = None
    ) -> Scenario:
        """Create an editable custom copy (version 1) of the latest version of a scenario."""
        source = self.repo.get(scenario_id)
        copy_ = copy.deepcopy(source)
        copy_.scenario_id = new_id or self.suggest_id(f"{scenario_id}-copy")
        copy_.title = new_title or f"{source.title} (copy)"
        copy_.change_note = f"Duplicated from {source.scenario_id} v{source.version}."
        created, _ = self.create(copy_)
        return created

    def delete(self, scenario_id: str) -> None:
        origin = self.repo.origin_of(scenario_id)
        if origin is None:
            raise ScenarioNotFoundError(f"Scenario '{scenario_id}' does not exist.")
        if origin == ScenarioOrigin.DEMO:
            raise ReadOnlyScenarioError("Demo scenarios cannot be deleted.")
        self.repo.delete(scenario_id)

    # -- demo seed ----------------------------------------------------------------

    def seed_demo_scenarios(self, seed_path: Path) -> int:
        """Insert demo scenarios that are not yet present. Idempotent.

        Returns the number of scenarios inserted. Existing scenarios (demo or
        custom) are never modified or duplicated.
        """
        document = json.loads(seed_path.read_text(encoding="utf-8"))
        seed_version = str(document.get("seed_version", "1"))
        missing: list[Scenario] = []
        for raw in document["scenarios"]:
            scenario = parse_scenario_dict(raw)
            if self.repo.exists(scenario.scenario_id):
                continue
            scenario.origin = ScenarioOrigin.DEMO
            scenario.version = 1
            scenario.created_at = scenario.updated_at = utc_now_iso()
            scenario.change_note = "Synthetic demo scenario shipped with LOK."
            try:
                ensure_valid(scenario)
            except ScenarioValidationError as exc:
                raise ScenarioValidationError(
                    [ValidationIssue(f"seed:{scenario.scenario_id}", str(exc))]
                ) from exc
            missing.append(scenario)
        if missing:
            self.repo.insert_many(new=missing, versions=[])
        self.repo.set_meta(SEED_META_KEY, seed_version)
        return len(missing)

    @staticmethod
    def categories(scenarios: Iterable[Scenario]) -> list[str]:
        return sorted({s.category for s in scenarios}, key=str.casefold)

    @staticmethod
    def tags(scenarios: Iterable[Scenario]) -> list[str]:
        return sorted({t for s in scenarios for t in s.tags}, key=str.casefold)
