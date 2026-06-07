"""Tests for the notes_os.app module (Phase 1 scaffold)."""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

from notes_os.app import NotesOSApp, main


if TYPE_CHECKING:
    import pytest


def test_main_runs_without_error() -> None:
    """main() must complete without raising and return None."""
    result = main()
    assert result is None


def test_main_handles_missing_package_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() falls back gracefully when the package version cannot be resolved."""

    def _raise(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    assert main() is None


def test_notes_os_app_instantiates() -> None:
    """NotesOSApp can be constructed without arguments or errors."""
    app = NotesOSApp()
    assert isinstance(app, NotesOSApp)


def test_notes_os_app_run() -> None:
    """NotesOSApp.run() completes without raising."""
    app = NotesOSApp()
    result = app.run()
    assert result is None
