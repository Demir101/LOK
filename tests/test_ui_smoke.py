"""Headless UI smoke tests using Streamlit's AppTest (no browser, no network).

Each page is rendered against a temporary database. These tests catch exceptions
and broken wiring; they do not check layout or visual quality.
"""

import pytest
from streamlit.testing.v1 import AppTest

PAGES = [
    "dashboard",
    "run_evaluation",
    "history",
    "comparison",
    "scenario_library",
    "scenario_builder",
    "methodology",
    "settings",
]


def _render(module_name: str) -> None:
    import importlib

    importlib.import_module(f"lok.ui.pages.{module_name}").render()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "ui.db"
    monkeypatch.setenv("LOK_DB_PATH", str(path))
    return path


@pytest.mark.parametrize("module_name", PAGES)
def test_page_renders_without_exception(temp_db, module_name):
    at = AppTest.from_function(_render, args=(module_name,), default_timeout=60)
    at.run()
    assert not at.exception, [e.message for e in at.exception]


def test_pages_render_with_stored_evaluation(temp_db):
    from lok.services.container import create_services

    services = create_services(temp_db)
    session = services.evaluations.start("demo-project-release-deadline", "Assistant A", "v1")
    services.evaluations.save_responses(session.evaluation_id, {"t2": "The deadline is May 22."})
    services.evaluations.run_evaluation(session.evaluation_id)
    for module_name in ("dashboard", "history", "comparison"):
        at = AppTest.from_function(_render, args=(module_name,), default_timeout=60)
        at.run()
        assert not at.exception, (module_name, [e.message for e in at.exception])


def test_builder_template_validates_and_saves(temp_db):
    at = AppTest.from_function(_render, args=("scenario_builder",), default_timeout=60)
    at.run()
    next(b for b in at.button if b.label == "Use template").click().run()
    # The template intentionally leaves the basics blank.
    assert any("validation error" in e.value for e in at.error)

    next(t for t in at.text_input if t.label == "Scenario ID").input("ui-smoke-meeting").run()
    assert any("unsaved changes" in m.value for m in at.markdown)
    next(t for t in at.text_input if t.label == "Title").input("UI smoke test").run()
    next(t for t in at.text_area if t.label == "Description").input("Synthetic test.").run()
    next(t for t in at.text_input if t.label == "Category").input("Calendar scheduling").run()
    assert not at.error

    create = next(b for b in at.button if b.label == "Create scenario")
    assert not create.disabled
    create.click().run()
    assert not at.exception
    assert any("ui-smoke-meeting" in s.value and "version 1" in s.value for s in at.success)
