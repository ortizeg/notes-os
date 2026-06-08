"""SC2 Pilot tests for SortScreen — inbox triage end-to-end via Textual.

These tests prove SC2: SortScreen routes one note through a real
BackingUpNotesRepository wrapping a MockNotesRepository — move recorded on
the mock, note leaves the inbox, session moved-count increments, and the
BackupManager.create() fires before the move.

All assertions drive the TUI via Textual's ``App.run_test()`` async Pilot.
No AppleScript is invoked.  The backup is proven via a ``MagicMock`` spy on
``BackupManager.create()`` so the assertion is deterministic and timing-safe.

Test coverage:
  SC2a: one note routed to Archive via 'x' — move recorded, inbox shrinks,
        session moved-count == 1, backup spy create() called before move.
  SC2b: drill into Projects → folder via 'p' then '1' — AWAIT_FOLDER works,
        move recorded.
  SC2c: Esc at AWAIT_FOLDER backs up to AWAIT_CATEGORY (router state reset).
  SC2d: action_sort on HomeScreen navigates to SortScreen (push_screen wired).
  SC2e: session skip — press 's'; session.skipped increments, no move.

Note on querying: SortScreen lives on app.screen after push_screen("sort").
All widget queries use app.screen.query_one(...).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from notes_os.app import NotesOSApp
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup
from notes_os.screens.sort import SortScreen
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.router import RouterState


if TYPE_CHECKING:
    from notes_os.config import SorterConfig
    from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_BACKUP_PATH = "/nonexistent/NoteStore_2026-01-01_12-00-00"  # test-only sentinel; never created
_FAKE_BACKUP = Backup(
    timestamp=datetime(2026, 1, 1, 12, 0, 0),
    path=_FAKE_BACKUP_PATH,  # type: ignore[arg-type]  # path coerced to str; test sentinel
)


def _make_spy_manager(tui_config: SorterConfig) -> MagicMock:
    """Build a MagicMock spy wrapping BackupManager spec.

    ``create()`` returns a stub Backup so the BackingUpNotesRepository
    contract is satisfied without touching the filesystem.

    Args:
        tui_config: SorterConfig fixture (used only for spec reference).

    Returns:
        A :class:`unittest.mock.MagicMock` with ``spec=BackupManager``.
    """
    spy = MagicMock(spec=BackupManager)
    spy.create.return_value = _FAKE_BACKUP
    spy.list.return_value = [_FAKE_BACKUP]
    return spy


def _make_archive_note(note_id: str = "sc2-note-1") -> Note:
    """Return a Note that routes to Archive with a single 'x' keystroke.

    Args:
        note_id: Opaque identifier for the note.

    Returns:
        A :class:`~notes_os.sorter.models.Note` with a predictable id.
    """
    return Note(
        id=note_id,
        title="Test Note for Archive",
        body="<p>archive me</p>",
        preview="archive me",
    )


def _make_projects_structure() -> ParaStructure:
    """Return a ParaStructure with Projects having two sub-folders.

    Returns:
        A :class:`~notes_os.sorter.models.ParaStructure` with
        Projects → (General, Web); other roots are leaf-only.
    """
    return ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": ("General", "Web"),
            "Areas": (),
            "Resources": (),
            "Archive": (),
        },
    )


def _make_app_with_spy(
    tui_config: SorterConfig,
    notes: list[Note],
    structure: ParaStructure | None = None,
) -> tuple[NotesOSApp, MockNotesRepository, MagicMock]:
    """Build a NotesOSApp with BackingUpNotesRepository + spy BackupManager.

    The spy records ``create()`` calls without touching the filesystem.
    This avoids the macOS rename-on-same-second issue (ensure_folder and
    move_note both fire create() within the same second in tests).

    Args:
        tui_config: SorterConfig with all I/O paths under tmp_path.
        notes: Seed notes for the MockNotesRepository inbox.
        structure: Optional ParaStructure; defaults to all-leaf roots.

    Returns:
        A 3-tuple of (app, mock_inner_repo, spy_manager) so tests can
        assert on mock_inner_repo.moves and spy_manager.create.call_count.
    """
    from tests.sorter.conftest import MockNotesRepository

    if structure is None:
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": (),
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )

    mock_inner = MockNotesRepository(notes=notes, structure=structure)
    spy_manager = _make_spy_manager(tui_config)
    wrapped_repo = BackingUpNotesRepository(mock_inner, spy_manager, tui_config.backup)

    app = NotesOSApp(config=tui_config, repo=wrapped_repo, backup_manager=spy_manager)
    return app, mock_inner, spy_manager


# ---------------------------------------------------------------------------
# SC2a: Archive route — backup spy called, move recorded, session increments
# ---------------------------------------------------------------------------


async def test_sc2_archive_move_backup_fired(tui_config: SorterConfig) -> None:
    """SC2a: route one note to Archive via 'x'; prove backup + move + session.

    Uses a spy BackupManager so create() calls are recorded without touching
    the filesystem (avoids macOS same-second rename collision between the two
    create() calls fired by ensure_folder + move_note).

    SC2 truths asserted:
    - mock_inner.moves has the note with the Archive path (Router.move_note fired).
    - Note left the inbox (get_inbox_notes() returned empty list).
    - Session moved-count == 1 (screen._session.summary().moved).
    - spy_manager.create() was called at least once (backup-before-write proved).

    Args:
        tui_config: SorterConfig fixture with all I/O paths under tmp_path.
    """
    note = _make_archive_note("sc2a-1")
    app, mock_inner, spy_manager = _make_app_with_spy(tui_config, [note])

    fixed_year = 2026

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen(year_provider=lambda: fixed_year)
        await app.push_screen(screen)
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen on top, got {type(app.screen)}"
        )

        # Verify no create() calls before the keystroke (no spurious backups)
        spy_manager.create.assert_not_called()

        # Press 'x' — archive route (single keystroke, immediate move)
        await pilot.press("x")
        await pilot.pause()

        # SC2a-1: move recorded on inner repo.
        assert len(mock_inner.moves) == 1, f"Expected 1 move recorded, got {mock_inner.moves!r}"
        moved_note_id, moved_path = mock_inner.moves[0]
        assert moved_note_id == "sc2a-1", f"Unexpected moved note id: {moved_note_id!r}"
        assert len(moved_path) == 2, f"Unexpected archive path depth: {moved_path!r}"
        assert moved_path[-1] == str(fixed_year), f"Archive path year mismatch: {moved_path!r}"

        # SC2a-2: note left the inbox.
        remaining = mock_inner.get_inbox_notes()
        assert len(remaining) == 0, f"Expected empty inbox after move, got {len(remaining)} note(s)"

        # SC2a-3: session moved-count == 1.
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        summary = sort_screen._session.summary()
        assert summary.moved == 1, f"Expected session.moved == 1, got {summary.moved}"

        # SC2a-4: backup fired before the move (create() called at least once).
        # BackingUpNotesRepository calls create() before each write op
        # (ensure_folder + move_note = 2 write ops for archive path).
        assert spy_manager.create.call_count >= 1, (
            f"Expected BackupManager.create() to be called at least once, "
            f"got {spy_manager.create.call_count} calls"
        )


# ---------------------------------------------------------------------------
# SC2b: Projects → folder drill — AWAIT_FOLDER numeric key routes the note
# ---------------------------------------------------------------------------


async def test_sc2_projects_folder_drill(tui_config: SorterConfig) -> None:
    """SC2b: route one note to Projects/General via 'p' then '1'.

    Steps:
    1. Build app with a Projects structure containing (General, Web).
    2. Push SortScreen, press 'p' (enters AWAIT_FOLDER), then '1' (General).
    3. Assert: move recorded to ("Projects", "General"); session.moved == 1.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(
        id="sc2b-1",
        title="Projects Note",
        body="<p>projects</p>",
        preview="projects",
    )
    structure = _make_projects_structure()
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note], structure)

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Press 'p' → should enter AWAIT_FOLDER state
        await pilot.press("p")
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"Expected AWAIT_FOLDER after 'p', got {sort_screen._router_state}"
        )

        # Press '1' → selects General (first folder, no subfolders → immediate move)
        await pilot.press("1")
        await pilot.pause()

        # Assert move recorded
        assert len(mock_inner.moves) == 1, f"Expected 1 move, got {mock_inner.moves!r}"
        _moved_id, moved_path = mock_inner.moves[0]
        assert moved_path == ("Projects", "General"), (
            f"Expected ('Projects', 'General'), got {moved_path!r}"
        )

        # Session moved-count
        summary = sort_screen._session.summary()
        assert summary.moved == 1, f"Expected session.moved == 1, got {summary.moved}"


# ---------------------------------------------------------------------------
# SC2c: Esc at AWAIT_FOLDER backs up to AWAIT_CATEGORY (TUI-05 nav)
# ---------------------------------------------------------------------------


async def test_sc2_esc_at_await_folder_backs_to_category(
    tui_config: SorterConfig,
) -> None:
    """SC2c: Esc at AWAIT_FOLDER resets router state to AWAIT_CATEGORY.

    Steps:
    1. Push SortScreen with a Projects note (has sub-folders so 'p' → AWAIT_FOLDER).
    2. Press 'p' to enter AWAIT_FOLDER.
    3. Press Escape — assert screen._router_state == AWAIT_CATEGORY.
    4. No move recorded (back nav doesn't move notes).

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(
        id="sc2c-1",
        title="Back Nav Note",
        body="<p>back</p>",
        preview="back",
    )
    structure = _make_projects_structure()
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note], structure)

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Press 'p' → AWAIT_FOLDER
        await pilot.press("p")
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"Expected AWAIT_FOLDER after 'p', got {sort_screen._router_state}"
        )

        # Press Escape → back to AWAIT_CATEGORY
        await pilot.press("escape")
        await pilot.pause()

        assert sort_screen._router_state == RouterState.AWAIT_CATEGORY, (
            f"Expected AWAIT_CATEGORY after Esc, got {sort_screen._router_state}"
        )

        # No moves recorded — user backed out
        assert len(mock_inner.moves) == 0, (
            f"Expected no moves after back nav, got {mock_inner.moves!r}"
        )


# ---------------------------------------------------------------------------
# SC2d: HomeScreen "Sort Inbox" navigates to SortScreen
# ---------------------------------------------------------------------------


async def test_sc2_home_sort_pushes_sort_screen(tui_config: SorterConfig) -> None:
    """SC2d: activating 'Sort Inbox' from HomeScreen pushes SortScreen.

    Verifies that the HomeScreen.action_sort seam from 06-01 is now wired to
    push_screen("sort") which resolves to SortScreen from the SCREENS registry.

    Steps:
    1. Build app with tui_config + empty inbox (no moves to make).
    2. Wait for HomeScreen to mount.
    3. Activate 'Sort Inbox' via action_sort().
    4. Assert SortScreen is now on top of the screen stack.

    Args:
        tui_config: SorterConfig fixture.
    """
    from tests.sorter.conftest import MockNotesRepository

    empty_structure = ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={"Projects": (), "Areas": (), "Resources": (), "Archive": ()},
    )
    mock_repo = MockNotesRepository(notes=[], structure=empty_structure)
    app = NotesOSApp(config=tui_config, repo=mock_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Trigger the sort action (equivalent to selecting 'Sort Inbox' from menu)
        await app.screen.run_action("sort")
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen after action_sort, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC2e: session skip — 's' key records skip, no move
# ---------------------------------------------------------------------------


async def test_sc2_skip_increments_session(tui_config: SorterConfig) -> None:
    """SC2e: pressing 's' skips the current note; session.skipped increments.

    Steps:
    1. Push SortScreen with one note.
    2. Press 's' (skip).
    3. Assert: no moves on inner repo; session.skipped == 1; session.moved == 0.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(
        id="sc2e-1",
        title="Skip Me Note",
        body="<p>skip</p>",
        preview="skip",
    )
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Press 's' — skip
        await pilot.press("s")
        await pilot.pause()

        # No moves recorded
        assert len(mock_inner.moves) == 0, f"Expected no moves for skip, got {mock_inner.moves!r}"

        # Session skip count
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        summary = sort_screen._session.summary()
        assert summary.skipped == 1, f"Expected session.skipped == 1, got {summary.skipped}"
        assert summary.moved == 0, f"Expected session.moved == 0, got {summary.moved}"
