"""macOS-only TUI integration smoke test — drives the real app against Apple Notes.

This is the smoke test the mocked Pilot suite cannot replace.  ``MockNotesRepository``
returns instantly and Pilot's ``press()`` can send ``character=None``, so the mocked
tests are blind to a whole class of real-only failures: blocking ``osascript`` calls in
``on_mount`` / on every move, real key-encoding (``Enter`` arriving as ``\\r``), and the
real ``ensure_folder`` → ``move_note`` round-trip.  This test exercises the FULL stack —
``NotesOSApp`` → ``HomeScreen`` → ``SortScreen`` → real ``AppleScriptNotesRepository`` →
``osascript`` → Apple Notes — by driving the app via Pilot and archiving one seeded note.

Safety
------
- Marked ``@pytest.mark.integration`` and therefore DESELECTED from CI by the
  ``addopts = ["-m", "not integration"]`` setting.  Run locally with
  ``pixi run pytest -m integration``.
- Touches ONLY test-owned folders: a ``_TestInbox`` and a ``_TestArchive``.  The
  archive destination is redirected via ``ArchiveConfig.base_folder`` so pressing
  ``x`` never writes into the user's real PARA ``Archive`` folder.  Both folders are
  created in setup and deleted in teardown; the user's real notes are never read or
  written.
- The :class:`~notes_os.backup.BackupManager` is replaced with a spy so the test does
  NOT copy the real (potentially multi-GB) ``NoteStore.sqlite`` and needs only the
  Automation→Notes grant, not Full Disk Access.  The backup-then-move wiring is still
  exercised (``BackingUpNotesRepository`` calls ``spy.create`` before each real move).

Requires macOS, Apple Notes, ``osascript``, and the Automation→Notes TCC grant for the
process running the tests.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from notes_os.app import NotesOSApp
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup, BackupConfig
from notes_os.config import ArchiveConfig, SorterConfig
from notes_os.screens.home import HomeScreen
from notes_os.screens.sort import SortScreen
from notes_os.sorter.models import BridgeConfig
from notes_os.sorter.notes import AppleScriptNotesRepository


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
# Constants — all test-owned; never collide with real PARA folders
# ---------------------------------------------------------------------------

_TEST_INBOX = "_TestInbox"
_TEST_ARCHIVE = "_TestArchive"
_TEST_NOTE_TITLE = "_TestNote_NotesOS_TUI_Smoke"
_TEST_NOTE_BODY = "<div>TUI smoke note — safe to delete.</div>"


# ---------------------------------------------------------------------------
# osascript helpers (mirror tests/sorter/test_notes_integration.py — kept local
# so this smoke is a self-contained scaffold others can copy for new screens)
# ---------------------------------------------------------------------------


def _run_script(script: str) -> str:
    """Run an AppleScript and return stripped stdout.

    Args:
        script: The AppleScript program to execute.

    Returns:
        The stdout from osascript on success.

    Raises:
        subprocess.CalledProcessError: If osascript exits non-zero.
    """
    result = subprocess.run(  # noqa: S603
        ["osascript", "-e", script],  # noqa: S607  # osascript is a fixed macOS system binary
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
        return _run_script(script) == "yes"
    except subprocess.CalledProcessError:
        return False


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


def _delete_folder(folder_name: str) -> None:
    """Delete a top-level Notes folder if it exists (suppresses errors).

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


def _create_note_in_folder(folder_name: str, title: str, body: str) -> str:
    """Create a note in a specific folder and return its opaque Notes ID.

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


def _count_notes_under(folder_name: str) -> int:
    """Return notes directly in *folder_name* plus those in its immediate subfolders.

    Verification is by folder count rather than by note id on purpose: Apple
    Notes reassigns a note's ``id`` when it is moved between folders (the
    pre-move id then fails to resolve with error ``-1728``), so a seeded id
    cannot be re-read after the archive move. Counting one level of subfolders
    also covers the ``auto_year`` case where the note lands in
    ``_TestArchive/<year>`` rather than directly in ``_TestArchive``.

    Args:
        folder_name: The top-level folder whose subtree (itself + one level of
            subfolders) should be counted.

    Returns:
        The total number of notes in the folder and its immediate subfolders.
    """
    escaped = folder_name.replace('"', '""')
    script = f"""\
tell application "Notes"
    set theFolder to folder "{escaped}"
    set total to (count notes of theFolder)
    repeat with aSub in (folders of theFolder)
        set total to total + (count notes of aSub)
    end repeat
    return total
end tell"""
    return int(_run_script(script))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_BACKUP = Backup(
    timestamp=datetime(2026, 6, 1, 10, 0, 0),  # fixed sentinel; spy never reads it
    path="/nonexistent/tui-smoke-sentinel",  # type: ignore[arg-type]  # spy never reads it
)


def _make_spy_manager() -> MagicMock:
    """Return a MagicMock BackupManager spy that records create() without I/O.

    Using a spy avoids copying the real ``NoteStore.sqlite`` (so Full Disk Access
    is not required) while still proving the backup-then-move wiring fires.

    Returns:
        MagicMock with ``spec=BackupManager``; ``create()`` returns ``_FAKE_BACKUP``.
    """
    spy = MagicMock(spec=BackupManager)
    spy.create.return_value = _FAKE_BACKUP
    spy.list.return_value = [_FAKE_BACKUP]
    return spy


def _make_smoke_config(tmp_path: Path) -> SorterConfig:
    """Build a SorterConfig pointing at the test inbox/archive with tmp I/O paths.

    The bridge reads from ``_TestInbox`` and the archive root is redirected to
    ``_TestArchive`` so the ``x`` keystroke can never touch the real PARA Archive.

    Args:
        tmp_path: pytest temporary directory (backup/log dirs live here, unused by
            the spy but required by the config models).

    Returns:
        A frozen :class:`~notes_os.config.SorterConfig`.
    """
    notes_db_dir = tmp_path / "notes-db"
    backup_dir = tmp_path / "backups"
    notes_db_dir.mkdir()
    backup_dir.mkdir()

    return SorterConfig(
        bridge=BridgeConfig(inbox_folder=_TEST_INBOX),
        backup=BackupConfig(notes_db_dir=notes_db_dir, backup_dir=backup_dir),
        archive=ArchiveConfig(base_folder=_TEST_ARCHIVE, auto_year=True),
        log_dir=tmp_path / "logs",
    )


@pytest.fixture()
def seeded_inbox() -> Iterator[str]:
    """Create ``_TestInbox`` with one seeded note; tear both test folders down after.

    Yields:
        The opaque Notes ID of the seeded note.
    """
    # Setup — clean slate, then a folder with a single note.
    _delete_folder(_TEST_INBOX)
    _delete_folder(_TEST_ARCHIVE)
    _ensure_folder_raw(_TEST_INBOX)
    note_id = _create_note_in_folder(_TEST_INBOX, _TEST_NOTE_TITLE, _TEST_NOTE_BODY)

    yield note_id

    # Teardown — remove only test-owned folders (and any nested year subfolders).
    _delete_folder(_TEST_INBOX)
    _delete_folder(_TEST_ARCHIVE)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


class TestTUISmokeAgainstRealNotes:
    """Drive the real TUI against Apple Notes and archive one seeded note."""

    async def test_archive_seeded_note_end_to_end(
        self,
        tmp_path: Path,
        seeded_inbox: str,
    ) -> None:
        """Home → Sort → press ``x`` archives the real note out of ``_TestInbox``.

        Exercises the real-only path that the mocked suite cannot: blocking
        ``osascript`` reads in ``on_mount``/``_load_inbox_refs``, real ``x`` key
        encoding, and the real ``ensure_folder`` → ``move_note`` round-trip
        (which blocks the event loop ~1s each on the real bridge).  A spy
        ``BackupManager`` keeps the test off the real ``NoteStore.sqlite`` while
        still firing the backup-then-move wiring.

        Args:
            tmp_path: pytest temporary directory for config I/O paths.
            seeded_inbox: Opaque Notes ID of the note seeded in ``_TestInbox``.
        """
        # The fixture's seeded id is intentionally not re-read after the move:
        # Apple Notes reassigns a note's id on move, so verification below is by
        # folder note-count, not by id.
        _seeded_id = seeded_inbox
        config = _make_smoke_config(tmp_path)

        spy_manager = _make_spy_manager()
        inner = AppleScriptNotesRepository(config.bridge)
        repo = BackingUpNotesRepository(inner, spy_manager, config.backup)

        app = NotesOSApp(config=config, repo=repo, backup_manager=spy_manager)

        async with app.run_test() as pilot:
            await pilot.pause()

            # HomeScreen mounts; wait for the real _load_status osascript worker.
            assert isinstance(app.screen, HomeScreen), (
                f"Expected HomeScreen at launch, got {type(app.screen).__name__}"
            )
            await app.workers.wait_for_complete()
            await pilot.pause()

            # Enter the sort flow; wait for the real _load_inbox_refs worker.
            await app.screen.run_action("sort")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert isinstance(app.screen, SortScreen), (
                f"Expected SortScreen after sort action, got {type(app.screen).__name__}"
            )

            # Press 'x' — archives via the REAL bridge (blocks inline on osascript).
            await pilot.press("x")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        # The real note must have left _TestInbox and landed under _TestArchive.
        # Verify by folder counts (not by id): Apple Notes reassigns a note's id
        # on move, so the seeded id no longer resolves after the archive.
        assert spy_manager.create.call_count >= 1, (
            "backup-then-move wiring: spy_manager.create() should fire before the move"
        )
        assert _folder_exists(_TEST_ARCHIVE), (
            f"{_TEST_ARCHIVE!r} should have been created by ensure_folder during archive"
        )
        # Inbox emptied — read through the production repo (exercises get_inbox_notes).
        remaining = inner.get_inbox_notes()
        assert remaining == [], (
            f"Seeded note should have left {_TEST_INBOX!r}; inbox still has {len(remaining)} note(s)"
        )
        # Note arrived somewhere under the archive root (root or its <year> subfolder).
        assert _count_notes_under(_TEST_ARCHIVE) >= 1, (
            f"Expected the archived note under {_TEST_ARCHIVE!r}, found none"
        )
