"""SC1 Pilot tests for HomeScreen — inbox count, last backup, honest backend.

These tests prove SC1: HomeScreen live status indicators read real values from
injected dependencies (MockNotesRepository + tmp_path config) with no AppleScript.
All assertions drive the TUI via Textual's ``App.run_test()`` async Pilot.

Note on querying: Textual widgets live on the active *screen* in the stack, not
directly on the App.  All ``query_one`` calls use ``app.screen.query_one(...)``
to correctly target the pushed HomeScreen.

Note on worker timing: ``HomeScreen.on_mount`` now kicks off a
``@work(thread=True)`` worker (``_load_status``) to fetch inbox count and last-
backup timestamp off the event-loop thread.  Each test that asserts on those
status widgets must wait for all workers to complete (``await
app.workers.wait_for_complete()``) and then flush the resulting
``call_from_thread`` UI updates (``await pilot.pause()``) before querying.

Test coverage:
  - SC1a: inbox count matches seeded note count (2 notes → "2")
  - SC1b: backend label contains "sort-only" — NOT "ollama"/"apple"/LLM
  - SC1c: last-backup shows "never" when no backups exist
  - SC1d: last-backup shows a timestamp string after a real backup is created
  - SC1e: splash version Static renders a version string
  - SC1f: menu contains "Sort Inbox" and "Quit" items
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import OptionList, Static

from notes_os.app import NotesOSApp
from notes_os.backup import BackupManager
from notes_os.screens.home import HomeScreen


if TYPE_CHECKING:
    from notes_os.config import SorterConfig
    from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# SC1a / SC1b / SC1c: inbox count + backend + no-backups case
# ---------------------------------------------------------------------------


async def test_home_screen_status_no_backups(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """HomeScreen shows correct inbox count, honest backend, and 'never' last backup.

    SC1a: inbox count reads from injected MockNotesRepository (2 notes seeded).
    SC1b: backend label shows "sort-only" — not a fabricated LLM backend.
    SC1c: last-backup shows "never" when backup_dir under tmp_path is empty.

    Args:
        tui_config: SorterConfig fixture with all paths under tmp_path.
        tui_repo: MockNotesRepository seeded with 2 notes.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)

        # Wait for the _load_status thread worker to complete, then flush the
        # call_from_thread UI updates back to the main thread.
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Textual pushes HomeScreen on top of the base screen; widgets live on
        # the active screen, so we query from app.screen (HomeScreen), not app.
        screen = app.screen

        # SC1a: inbox count
        inbox_widget = screen.query_one("#status-inbox", Static)
        inbox_text = str(inbox_widget.render())
        assert "2" in inbox_text, f"Expected '2' in inbox text, got: {inbox_text!r}"

        # SC1b: honest M1 backend — must NOT contain fabricated LLM labels
        backend_widget = screen.query_one("#status-backend", Static)
        backend_text = str(backend_widget.render())
        assert "sort-only" in backend_text, (
            f"Expected 'sort-only' in backend text, got: {backend_text!r}"
        )
        assert "ollama" not in backend_text.lower(), "Backend must not claim ollama"

        # SC1c: no backups → "never"
        backup_widget = screen.query_one("#status-backup", Static)
        backup_text = str(backup_widget.render())
        assert "never" in backup_text.lower(), (
            f"Expected 'never' in backup text (empty backup_dir), got: {backup_text!r}"
        )


# ---------------------------------------------------------------------------
# SC1d: last-backup timestamp after real backup is created
# ---------------------------------------------------------------------------


async def test_home_screen_status_with_backup(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """HomeScreen shows a real timestamp after a backup is created.

    SC1d: after creating a backup (real file copy under tmp_path), the
    HomeScreen status renders the backup timestamp string.

    Args:
        tui_config: SorterConfig fixture (backup_dir under tmp_path).
        tui_repo: MockNotesRepository seeded with 2 notes.
    """
    # Create a real backup so BackupManager.list() returns one entry.
    # The NoteStore.sqlite file must exist in notes_db_dir.
    notes_db_dir = tui_config.backup.notes_db_dir
    db_file = notes_db_dir / "NoteStore.sqlite"
    db_file.write_bytes(b"SQLite format 3\x00")  # minimal stub content

    manager = BackupManager(tui_config.backup)
    backup = manager.create()
    assert backup is not None

    # Run the app with the same config/repo so on_mount finds the backup.
    app = NotesOSApp(config=tui_config, repo=tui_repo, backup_manager=manager)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Wait for the _load_status thread worker, then flush UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        backup_widget = app.screen.query_one("#status-backup", Static)
        backup_text = str(backup_widget.render())

        # Should NOT be "never" now
        assert "never" not in backup_text.lower(), (
            f"Expected timestamp, not 'never', got: {backup_text!r}"
        )
        # Timestamp contains YYYY-MM-DD format (has dashes between date parts)
        assert "-" in backup_text, f"Expected date string in backup text, got: {backup_text!r}"


# ---------------------------------------------------------------------------
# SC1e: splash version Static
# ---------------------------------------------------------------------------


async def test_home_screen_splash_version(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """HomeScreen splash renders a version string.

    SC1e: the version Static (``#version-label``) contains a version-like
    string (either resolved via importlib.metadata or the fallback
    "0.0.0+unknown").  This widget is set synchronously in ``compose`` so no
    worker wait is needed.

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        version_widget = app.screen.query_one("#version-label", Static)
        version_text = str(version_widget.render())

        # Version string must start with "v" (e.g. "v1.2.3" or "v0.0.0+unknown")
        assert version_text.startswith("v"), (
            f"Expected version label to start with 'v', got: {version_text!r}"
        )


# ---------------------------------------------------------------------------
# SC1f: menu items
# ---------------------------------------------------------------------------


async def test_home_screen_menu_items(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """HomeScreen menu contains 'Sort Inbox' and 'Quit' options.

    SC1f: the OptionList (id ``#menu``) has exactly two options with the
    expected IDs and visible text.  This widget is set synchronously in
    ``compose`` so no worker wait is needed.

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        menu = app.screen.query_one("#menu", OptionList)
        option_count = menu.option_count
        assert option_count == 2, f"Expected 2 menu items, got {option_count}"

        # Verify option IDs
        sort_option = menu.get_option("sort")
        quit_option = menu.get_option("quit")

        assert sort_option is not None, "Expected a menu option with id='sort'"
        assert quit_option is not None, "Expected a menu option with id='quit'"

        # Verify prompt text contains expected strings
        assert "Sort" in str(sort_option.prompt), (
            f"Sort option prompt unexpected: {sort_option.prompt!r}"
        )
        assert "Quit" in str(quit_option.prompt), (
            f"Quit option prompt unexpected: {quit_option.prompt!r}"
        )
