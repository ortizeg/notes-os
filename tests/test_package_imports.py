"""Smoke tests for the notes_os package surface (Phase 1 scaffold).

These tests prove SCAF-02: the full package namespace — including the M2-M4
stub subpackages — imports cleanly without installing extras, so downstream
modules can import any namespace unconditionally from day one.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "notes_os",
        "notes_os.app",
        "notes_os.config",
        "notes_os.exceptions",
        "notes_os.sorter",
        "notes_os.distiller",
        "notes_os.graph",
        "notes_os.suggestions",
    ],
)
def test_module_imports(module_name: str) -> None:
    """Every NotesOS module and stub subpackage imports without error."""
    module = importlib.import_module(module_name)
    assert module is not None


def test_notes_os_error_is_exception() -> None:
    """NotesOSError is the project-wide root exception."""
    from notes_os.exceptions import NotesOSError

    assert issubclass(NotesOSError, Exception)
    with pytest.raises(NotesOSError):
        raise NotesOSError("boom")
