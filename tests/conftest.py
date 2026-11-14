"""Shared fixtures. Every test that touches storage uses a temporary database."""

from __future__ import annotations

from pathlib import Path

import pytest

from lok.domain.models import (
    Assertion,
    ConversationTurn,
    CorrectionEvent,
    DependencyEdge,
    ExpectedOutcome,
    Fact,
    Scenario,
)
from lok.storage.database import Database


def make_scenario(scenario_id: str = "test-deadline", **overrides) -> Scenario:
    """A small but complete scenario: deadline correction with a dependent reminder."""
    scenario = Scenario(
        scenario_id=scenario_id,
        title="Deadline correction",
        description="The project deadline moves; the reminder depends on it.",
        objective="Check that the corrected deadline is adopted.",
        category="Project management",
        difficulty="easy",
        tags=["deadline", "test"],
        facts=[
            Fact("deadline", "Deadline", "May 15", "May 22", "corrected", "Project deadline"),
            Fact("reminder", "Reminder", "May 13", "May 20", "corrected", "Two days before deadline"),
            Fact("owner", "Owner", "Priya", "Priya", "active", "Project owner"),
        ],
        corrections=[
            CorrectionEvent(
                correction_id="c1",
                target_fact_id="deadline",
                original_value="May 15",
                proposed_value="May 22",
                correction_type="valid",
                is_authoritative=True,
                turn_id="t2",
                expected_behavior="Adopt May 22 as the deadline.",
            )
        ],
        turns=[
            ConversationTurn("t1", 1, "Deadline is May 15, owner Priya.", "initial_information"),
            ConversationTurn("t2", 2, "Correction: deadline is May 22.", "valid_correction", True, "c1"),
            ConversationTurn("t3", 3, "What is the deadline and the reminder date?", "follow_up"),
        ],
        dependencies=[DependencyEdge("deadline", "reminder", "Reminder is two days before deadline")],
        assertions=[
            Assertion("a1", "t3", "correction_accuracy", "Uses May 22", "contains", "May 22", 2.0),
            Assertion("a2", "t3", "repeated_error_detection", "No May 15", "does_not_contain", "May 15"),
            Assertion("a3", "t3", "dependency_updates", "Reminder May 20", "contains", "May 20"),
            Assertion("a4", "t2", "context_preservation", "Owner kept", "contains", "Priya"),
        ],
        expected_outcomes=[ExpectedOutcome("o1", "Deadline is May 22.", "correction_accuracy", "t3")],
    )
    for key, value in overrides.items():
        setattr(scenario, key, value)
    return scenario


@pytest.fixture
def scenario() -> Scenario:
    return make_scenario()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_lok.db")
    database.initialize()
    return database
