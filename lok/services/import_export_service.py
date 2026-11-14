"""Versioned JSON import and export of scenarios.

File format (``schema_version`` 1)::

    {
      "format": "lok.scenarios",
      "schema_version": 1,
      "exported_at": "2026-01-01T00:00:00+00:00",
      "scenarios": [ { ...scenario object... } ]
    }

Imports are parsed with :func:`json.loads` only (no ``eval``/pickle), limited
in size, fully validated, and applied in a single all-or-nothing transaction.
Existing scenarios are never overwritten silently: replacing requires explicit
confirmation and always creates a *new version*, preserving older versions.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from lok import __version__
from lok.domain.enums import ScenarioOrigin
from lok.domain.models import Scenario, utc_now_iso
from lok.domain.validation import (
    ScenarioValidationError,
    ValidationIssue,
    errors_only,
    parse_scenario_dict,
    validate_scenario,
)
from lok.storage.scenario_repository import ScenarioRepository

SCENARIO_FORMAT = "lok.scenarios"
SCENARIO_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class ScenarioImportError(ValueError):
    """Raised when an import file cannot be accepted as a whole."""


@dataclass
class ImportCandidate:
    """One scenario found in an import file, with its validation outcome."""

    index: int
    scenario_id: str
    title: str
    scenario: Scenario | None
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    existing_origin: str | None = None

    @property
    def is_conflict(self) -> bool:
        return self.existing_origin is not None

    @property
    def is_valid(self) -> bool:
        return self.scenario is not None and not self.errors


@dataclass
class ImportPreview:
    """Result of parsing and validating an import file (nothing written yet)."""

    candidates: list[ImportCandidate]
    file_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.file_errors) or any(not c.is_valid for c in self.candidates)

    @property
    def conflicts(self) -> list[ImportCandidate]:
        return [c for c in self.candidates if c.is_conflict]


@dataclass
class ImportReport:
    created: list[str]
    new_versions: list[str]


def export_scenarios(scenarios: list[Scenario]) -> str:
    """Serialise scenarios into the versioned LOK scenario format."""
    document = {
        "format": SCENARIO_FORMAT,
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "lok_version": __version__,
        "exported_at": utc_now_iso(),
        "scenarios": [scenario.to_dict() for scenario in scenarios],
    }
    return json.dumps(document, ensure_ascii=False, indent=2)


def _decode(raw: bytes | str, max_bytes: int) -> Any:
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if size == 0:
        raise ScenarioImportError("The file is empty.")
    if size > max_bytes:
        raise ScenarioImportError(
            f"The file is {size:,} bytes; the maximum accepted size is {max_bytes:,} bytes."
        )
    try:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError as exc:
        raise ScenarioImportError(f"The file is not valid UTF-8 text: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioImportError(
            f"Malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc


def preview_import(raw: bytes | str, repository: ScenarioRepository, max_bytes: int) -> ImportPreview:
    """Parse and validate an import file without writing anything."""
    try:
        document = _decode(raw, max_bytes)
    except ScenarioImportError as exc:
        return ImportPreview(candidates=[], file_errors=[str(exc)])

    if not isinstance(document, dict):
        return ImportPreview([], ["The top level of the file must be a JSON object."])
    file_errors: list[str] = []
    if document.get("format") != SCENARIO_FORMAT:
        file_errors.append(f'Unsupported file format; expected "format": "{SCENARIO_FORMAT}".')
    schema_version = document.get("schema_version")
    if isinstance(schema_version, bool) or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        file_errors.append(
            f"Unsupported schema_version {schema_version!r}; supported: "
            f"{', '.join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))}."
        )
    raw_scenarios = document.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        file_errors.append('"scenarios" must be a non-empty list.')
    if file_errors:
        return ImportPreview([], file_errors)

    candidates = [_candidate(index, raw_item, repository) for index, raw_item in enumerate(raw_scenarios)]
    counts = Counter(c.scenario_id for c in candidates)
    for candidate in candidates:
        if candidate.scenario_id and counts[candidate.scenario_id] > 1:
            candidate.errors.append(
                ValidationIssue(
                    "scenario_id", f"ID '{candidate.scenario_id}' appears more than once in the file."
                )
            )
    return ImportPreview(candidates)


def _candidate(index: int, raw: Any, repository: ScenarioRepository) -> ImportCandidate:
    scenario_id = str(raw.get("scenario_id", "")) if isinstance(raw, dict) else ""
    title = str(raw.get("title", "")) if isinstance(raw, dict) else ""
    try:
        scenario = parse_scenario_dict(raw)
    except ScenarioValidationError as exc:
        return ImportCandidate(index, scenario_id, title, None, errors=exc.issues)
    except (TypeError, ValueError) as exc:
        return ImportCandidate(
            index,
            scenario_id,
            title,
            None,
            errors=[ValidationIssue("scenario", f"Could not read scenario: {exc}")],
        )
    scenario.origin = ScenarioOrigin.CUSTOM
    issues = validate_scenario(scenario)
    errors = errors_only(issues)
    warnings = [issue for issue in issues if issue not in errors]
    existing = repository.origin_of(scenario.scenario_id) if scenario.scenario_id else None
    if existing == ScenarioOrigin.DEMO:
        errors.append(
            ValidationIssue(
                "scenario_id",
                f"'{scenario.scenario_id}' is a read-only demo scenario and cannot be replaced. "
                "Change the scenario_id in the file to import it as a custom scenario.",
            )
        )
    return ImportCandidate(index, scenario.scenario_id, scenario.title, scenario, errors, warnings, existing)


def apply_import(
    preview: ImportPreview, repository: ScenarioRepository, replace_existing: bool
) -> ImportReport:
    """Write a validated preview to the database (all-or-nothing).

    Raises :class:`ScenarioImportError` if the preview has errors, or if it contains
    conflicts and ``replace_existing`` is not explicitly confirmed.
    """
    if preview.has_errors:
        raise ScenarioImportError("The import contains errors; nothing was imported.")
    if preview.conflicts and not replace_existing:
        ids = ", ".join(c.scenario_id for c in preview.conflicts)
        raise ScenarioImportError(
            f"Scenario(s) {ids} already exist. Confirm replacement to store the imported "
            "definitions as new versions."
        )
    new: list[Scenario] = []
    versions: list[Scenario] = []
    now = utc_now_iso()
    for candidate in preview.candidates:
        assert candidate.scenario is not None  # guaranteed by has_errors check  # noqa: S101
        scenario = copy.deepcopy(candidate.scenario)
        source_version = scenario.version
        scenario.origin = ScenarioOrigin.CUSTOM
        if candidate.is_conflict:
            scenario.change_note = f"Replaced by import (file version {source_version})."
            versions.append(scenario)
        else:
            scenario.version = 1
            scenario.created_at = scenario.updated_at = now
            scenario.change_note = f"Imported (file version {source_version})."
            new.append(scenario)
    repository.insert_many(new=new, versions=versions)
    return ImportReport(created=[s.scenario_id for s in new], new_versions=[s.scenario_id for s in versions])
