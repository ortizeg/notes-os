"""macOS-only integration tests for the Apple Notes bridge using a dedicated _TestInbox folder.

All tests in this module are marked @pytest.mark.integration and are excluded from CI
via pytest's ``-m 'not integration'`` addopts setting.  Run them locally on macOS with
Apple Notes available to validate the real AppleScript round-trip.

The tests use a dedicated ``_TestInbox`` folder in Apple Notes plus a disposable
``_TestTarget`` folder.  They NEVER touch the user's real inbox or PARA notes.
Setup and teardown create and remove only test-owned folders and notes.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys

import pytest

from notes_os.sorter.models import BridgeConfig
from notes_os.sorter.notes import AppleScriptNotesRepository


# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

_OSASCRIPT_AVAILABLE = shutil.which("osascript") is not None
_ON_MACOS = sys.platform == "darwin"

if not _ON_MACOS or not _OSASCRIPT_AVAILABLE:
    pytest.skip(
        "Integration tests require macOS with osascript available",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEST_INBOX = "_TestInbox"
_TEST_TARGET = "_TestTarget"
_TEST_NOTE_TITLE = "_TestNote_NotesOS_Integration"
_TEST_NOTE_BODY = "<div>Integration test note — safe to delete.</div>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(script: str) -> str:
    """Run an AppleScript and return stdout.

    Args:
        script: The AppleScript program to execute.

    Returns:
        The stdout from osascript on success.

    Raises:
        subprocess.CalledProcessError: If osascript exits non-zero.
    """
    result = subprocess.run(  # noqa: S603
        ["osascript", "-e", script],  # noqa: S607  # osascript is a fixed macOS system binary at /usr/bin/osascript
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _folder_exists(folder_name: str) -> bool:
    """Return True if a top-level Notes folder named *folder_name* exists.

    Args:
        folder_name: The folder name to check.

    Returns:
        True if the folder exists in the Notes app.
    """
    escaped = folder_name.replace('"', '""')
    script = f"""\
tell application "Notes"
    if exists folder "{escaped}" then
        return "yes"
    else
        return "no"
    end if
end tell"""
    try:
        result = _run_script(script)
        return result.strip() == "yes"
    except subprocess.CalledProcessError:
        return False


def _delete_folder(folder_name: str) -> None:
    """Delete a top-level Notes folder if it exists.

    Args:
        folder_name: The folder name to delete.
    """
    escaped = folder_name.replace('"', '""')
    script = f"""\
tell application "Notes"
    if exists folder "{escaped}" then
        delete folder "{escaped}"
    end if
end tell"""
    with contextlib.suppress(subprocess.CalledProcessError):
        _run_script(script)


def _ensure_folder_raw(folder_name: str) -> None:
    """Create a top-level Notes folder if it does not exist.

    Args:
        folder_name: The folder name to create.
    """
    escaped = folder_name.replace('"', '""')
    script = f"""\
tell application "Notes"
    if not (exists folder "{escaped}") then
        make new folder with properties {{name:"{escaped}"}}
    end if
end tell"""
    _run_script(script)


def _create_note_in_folder(folder_name: str, title: str, body: str) -> str:
    """Create a note in a specific folder and return its ID.

    Args:
        folder_name: The folder to create the note in.
        title: The note's display name.
        body: The note's HTML body.

    Returns:
        The opaque Apple Notes note ID.
    """
    escaped_folder = folder_name.replace('"', '""')
    escaped_body = body.replace('"', '""')
    escaped_title = title.replace('"', '""')
    script = f"""\
tell application "Notes"
    set targetFolder to folder "{escaped_folder}"
    set newNote to make new note with properties {{name:"{escaped_title}", body:"{escaped_body}"}} at targetFolder
    return id of newNote
end tell"""
    return _run_script(script)


def _get_note_folder(note_id: str) -> str:
    """Return the name of the folder containing the note with *note_id*.

    Args:
        note_id: The opaque Apple Notes note identifier.

    Returns:
        The folder name containing the note.
    """
    escaped_id = note_id.replace('"', '""')
    script = f"""\
tell application "Notes"
    set theNote to note id "{escaped_id}"
    return name of container of theNote
end tell"""
    return _run_script(script)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bridge_repo() -> AppleScriptNotesRepository:
    """Return an AppleScriptNotesRepository configured with _TestInbox.

    Returns:
        A real AppleScriptNotesRepository pointing at _TestInbox.
    """
    cfg = BridgeConfig(inbox_folder=_TEST_INBOX)
    return AppleScriptNotesRepository(cfg)


@pytest.fixture()
def test_inbox_with_note(bridge_repo: AppleScriptNotesRepository) -> tuple[str, str]:
    """Set up _TestInbox with a known test note; tear it down after the test.

    Creates _TestInbox, creates a test note in it, yields (note_id, note_title),
    then deletes _TestInbox entirely on teardown.  Also ensures _TestTarget is
    cleaned up if created during the test.

    Args:
        bridge_repo: The real repository fixture.

    Yields:
        A (note_id, note_title) tuple for the seeded test note.
    """
    # Setup
    _ensure_folder_raw(_TEST_INBOX)
    note_id = _create_note_in_folder(_TEST_INBOX, _TEST_NOTE_TITLE, _TEST_NOTE_BODY)

    yield note_id, _TEST_NOTE_TITLE

    # Teardown — delete test-owned folders only
    _delete_folder(_TEST_INBOX)
    _delete_folder(_TEST_TARGET)


@pytest.fixture()
def default_repo() -> AppleScriptNotesRepository:
    """Return an AppleScriptNotesRepository with the default BridgeConfig (PARA roots).

    Returns:
        A real AppleScriptNotesRepository with default config.
    """
    return AppleScriptNotesRepository(BridgeConfig())


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestRealRead:
    """Integration: get_inbox_notes reads a real note from _TestInbox."""

    def test_get_inbox_notes_returns_seeded_note(
        self,
        bridge_repo: AppleScriptNotesRepository,
        test_inbox_with_note: tuple[str, str],
    ) -> None:
        """get_inbox_notes returns the seeded note with correct title and stripped preview."""
        note_id, note_title = test_inbox_with_note

        notes = bridge_repo.get_inbox_notes()

        ids = {n.id for n in notes}
        assert note_id in ids, f"Expected note id {note_id!r} in inbox, got {ids}"

        target_note = next(n for n in notes if n.id == note_id)
        assert target_note.title == note_title
        # Preview must be plain text (no HTML tags)
        assert "<" not in target_note.preview
        assert ">" not in target_note.preview
        # Expected stripped text from _TEST_NOTE_BODY
        assert "Integration test note" in target_note.preview


class TestRealStructure:
    """Integration: get_para_structure returns the PARA roots."""

    def test_get_para_structure_returns_para_roots(
        self,
        default_repo: AppleScriptNotesRepository,
    ) -> None:
        """get_para_structure returns a structure with the four configured PARA roots."""
        structure = default_repo.get_para_structure()

        cfg = BridgeConfig()
        for root in cfg.para_folders:
            assert root in structure.roots, f"Expected PARA root {root!r} in structure.roots"


class TestRealMove:
    """Integration: move_note moves a note and the round-trip succeeds (SC2)."""

    def test_move_note_leaves_inbox_and_arrives_at_target(
        self,
        bridge_repo: AppleScriptNotesRepository,
        test_inbox_with_note: tuple[str, str],
    ) -> None:
        """move_note moves the test note from _TestInbox to _TestTarget; round-trip moves it back."""
        note_id, _note_title = test_inbox_with_note

        # Create _TestTarget folder
        _ensure_folder_raw(_TEST_TARGET)

        # Move from _TestInbox to _TestTarget
        bridge_repo.move_note(note_id, (_TEST_TARGET,))

        folder_after_move = _get_note_folder(note_id)
        assert folder_after_move == _TEST_TARGET, (
            f"Note should be in {_TEST_TARGET!r}, got {folder_after_move!r}"
        )

        # Round-trip: move back to _TestInbox using default repo (inbox_folder is config-only)
        default_repo = AppleScriptNotesRepository(BridgeConfig())
        default_repo.move_note(note_id, (_TEST_INBOX,))

        folder_after_round_trip = _get_note_folder(note_id)
        assert folder_after_round_trip == _TEST_INBOX, (
            f"Note should be back in {_TEST_INBOX!r}, got {folder_after_round_trip!r}"
        )


class TestRealEnsureFolder:
    """Integration: ensure_folder creates folders idempotently (SC3)."""

    def test_ensure_folder_creates_and_is_idempotent(
        self,
        default_repo: AppleScriptNotesRepository,
    ) -> None:
        """ensure_folder creates _TestTarget, then a second call is a no-op (idempotent, SC3)."""
        # Precondition: folder does not exist
        _delete_folder(_TEST_TARGET)
        assert not _folder_exists(_TEST_TARGET), f"{_TEST_TARGET!r} should not exist before test"

        try:
            # First call: create
            default_repo.ensure_folder((_TEST_TARGET,))
            assert _folder_exists(_TEST_TARGET), (
                f"{_TEST_TARGET!r} should exist after ensure_folder"
            )

            # Second call: idempotent no-op (must not raise, must not duplicate)
            default_repo.ensure_folder((_TEST_TARGET,))
            assert _folder_exists(_TEST_TARGET), (
                f"{_TEST_TARGET!r} should still exist after second call"
            )
        finally:
            _delete_folder(_TEST_TARGET)


# ---------------------------------------------------------------------------
# TUI smoke test — production wiring against real Notes (deselected in CI)
# ---------------------------------------------------------------------------


class TestTUIProductionWiring:
    """Integration smoke: verify NotesOSApp production DI wiring without UI interaction.

    This test verifies that the production wiring path — ``NotesOSApp()`` with
    no injected dependencies — correctly builds a
    :class:`~notes_os.backup.BackingUpNotesRepository` wrapping an
    :class:`~notes_os.sorter.notes.AppleScriptNotesRepository`.  It exercises
    the deferred-import DI seam from Phase 06-01 without launching a full
    interactive Textual session (which requires a real terminal).

    macOS-only; requires Apple Notes and osascript.  Deselected from CI by the
    module-level ``pytestmark = pytest.mark.integration`` so the default run
    (``pytest -m 'not integration'``) never executes this test and never touches
    user data.
    """

    def test_production_app_builds_correct_repo_types(self) -> None:
        """NotesOSApp() DI seam builds BackingUpNotesRepository over AppleScriptNotesRepository.

        Constructs a production ``NotesOSApp()`` with no injected dependencies
        and asserts that the repo and backup_manager attributes have the correct
        production types.  No Textual event loop is started; no notes are read
        or written; no UI is shown.

        This is the minimal macOS-only smoke to prove the production wiring is
        intact after Phase-6 TUI integration (SC5 production-path check).
        """
        from notes_os.app import NotesOSApp
        from notes_os.backup import BackingUpNotesRepository, BackupManager
        from notes_os.sorter.notes import AppleScriptNotesRepository

        app = NotesOSApp()

        assert isinstance(app.backup_manager, BackupManager), (
            f"Expected BackupManager, got {type(app.backup_manager).__name__}"
        )

        assert isinstance(app.repo, BackingUpNotesRepository), (
            f"Expected BackingUpNotesRepository, got {type(app.repo).__name__}"
        )

        # Verify the inner (unwrapped) repo is the AppleScript implementation
        inner = app.repo._inner  # type: ignore[attr-defined]  # BackingUpNotesRepository._inner
        assert isinstance(inner, AppleScriptNotesRepository), (
            f"Expected AppleScriptNotesRepository as inner repo, got {type(inner).__name__}"
        )
