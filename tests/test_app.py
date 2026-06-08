"""Tests for the notes_os.app module (Phase 6 TUI shell)."""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

from notes_os.app import NotesOSApp, main
from notes_os.screens.home import HomeScreen


if TYPE_CHECKING:
    import pytest

    from notes_os.config import SorterConfig
    from tests.sorter.conftest import MockNotesRepository


def test_notes_os_app_instantiates(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """NotesOSApp can be constructed with injected config+repo and no errors.

    Verifies the DI seam: the injected repo and backup_manager are stored
    as public attributes so screens can read them via ``self.app.repo`` etc.

    Args:
        tui_config: SorterConfig fixture with all paths under tmp_path.
        tui_repo: MockNotesRepository fixture seeded with sample notes.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)
    assert isinstance(app, NotesOSApp)
    assert app.repo is tui_repo
    assert app.backup_manager is not None
    assert app.app_config is tui_config


async def test_notes_os_app_pilot_pushes_home_screen(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """NotesOSApp pushes HomeScreen on mount when driven via Pilot.

    Verifies TUI-01: the root screen is HomeScreen after mount completes.

    Args:
        tui_config: SorterConfig fixture with all paths under tmp_path.
        tui_repo: MockNotesRepository fixture seeded with sample notes.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


def test_main_runs_without_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() completes without raising and returns None.

    ``NotesOSApp.run`` is monkeypatched to a no-op so the blocking Textual
    event loop is never entered under pytest (T-06-03 mitigation).

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    monkeypatch.setattr(NotesOSApp, "run", lambda self: None)
    result = main()
    assert result is None


def test_main_handles_missing_package_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() falls back gracefully when the package version cannot be resolved.

    Exercises the ``PackageNotFoundError → "0.0.0+unknown"`` branch in
    ``main()`` and confirms the function still returns None.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """

    def _raise(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    monkeypatch.setattr(NotesOSApp, "run", lambda self: None)
    assert main() is None
