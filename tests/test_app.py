"""Tests for the notes_os.app module (Phase 1 scaffold)."""

from __future__ import annotations

from notes_os.app import NotesOSApp, main


def test_main_runs_without_error() -> None:
    """main() must complete without raising and return None."""
    result = main()
    assert result is None


def test_notes_os_app_instantiates() -> None:
    """NotesOSApp can be constructed without arguments or errors."""
    app = NotesOSApp()
    assert isinstance(app, NotesOSApp)


def test_notes_os_app_run() -> None:
    """NotesOSApp.run() completes without raising."""
    app = NotesOSApp()
    result = app.run()
    assert result is None
