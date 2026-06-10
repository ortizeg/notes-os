"""SC2 Pilot tests for SortScreen — inbox triage end-to-end via Textual.

These tests prove SC2: SortScreen routes one note through a real
BackingUpNotesRepository wrapping a MockNotesRepository — move recorded on
the mock, note leaves the inbox, session moved-count increments, and the
BackupManager.create() fires before the move.

All assertions drive the TUI via Textual's ``App.run_test()`` async Pilot.
No AppleScript is invoked.  The backup is proven via a ``MagicMock`` spy on
``BackupManager.create()`` so the assertion is deterministic and timing-safe.

Note on worker timing: ``SortScreen.on_mount`` now starts a
``@work(thread=True)`` worker (``_load_inbox``) to fetch the inbox snapshot
off the event-loop thread.  Tests that push a SortScreen must wait for all
workers to complete (``await app.workers.wait_for_complete()``) and then flush
the resulting ``call_from_thread`` UI updates (``await pilot.pause()``) before
sending keystrokes or asserting on screen state.

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

import threading
from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from textual.events import Key
from textual.widgets import Static

from notes_os.app import NotesOSApp
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup
from notes_os.exceptions import BackupError
from notes_os.screens.sort import _BULK_PAGE_SIZE, _BULK_THRESHOLD, SortScreen
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.router import RouterState


if TYPE_CHECKING:
    from notes_os.config import SorterConfig
    from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_BACKUP_PATH = (
    "/nonexistent/NoteStore_2026-01-01_12-00-00"  # test-only sentinel; never created
)
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

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
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
    """SC2b: route one note to Projects/General via 'p', '1', 'enter'.

    Steps:
    1. Build app with a Projects structure containing (General, Web).
    2. Push SortScreen, press 'p' (enters AWAIT_FOLDER, highlight=0=General).
    3. Press '1' to jump-highlight to General (already highlighted, no-op change).
    4. Press 'enter' to confirm the selection.
    3. Assert: move recorded to ("Projects", "General"); session.moved == 1.

    Digit keys now only jump-highlight; Enter is required to confirm (arrow-
    highlight + Enter model so folders 10+ are reachable).

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

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Press 'p' → should enter AWAIT_FOLDER state (highlight defaults to 0 = General)
        await pilot.press("p")
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"Expected AWAIT_FOLDER after 'p', got {sort_screen._router_state}"
        )

        # Press '1' → jump-highlights to General (index 0); does NOT move yet
        await pilot.press("1")
        await pilot.pause()

        # No move yet — digit only highlights
        assert len(mock_inner.moves) == 0, f"Digit alone must not move; got {mock_inner.moves!r}"
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"State must stay AWAIT_FOLDER after digit alone, got {sort_screen._router_state}"
        )

        # Press 'enter' → confirms highlighted option (General, index 0 → 1-based index 1)
        await pilot.press("enter")
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


async def test_category_prompt_renders_bracket_shortcuts_literally(
    tui_config: SorterConfig,
) -> None:
    """Regression: the '[P]rojects [A]reas …' prompt must keep its literal brackets.

    The #prompt Static is created with ``markup=False``; without it Textual would
    parse '[P]', '[A]', '[R]', '[S]' as console-markup tags and strip them, eating
    the first letter of each option ('rojects reas esources …').

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(id="bp-1", title="A Note", body="<p>body</p>", preview="body")
    structure = _make_projects_structure()
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, [note], structure)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        prompt_text = str(app.screen.query_one("#prompt", Static).render())
        assert "[P]rojects" in prompt_text, prompt_text
        assert "[A]reas" in prompt_text, prompt_text
        assert "[S]kip" in prompt_text, prompt_text


async def test_archive_move_backup_failure_does_not_crash(
    tui_config: SorterConfig,
) -> None:
    """Regression: a backup failure on the [X] archive path must not crash the TUI.

    The archive move happens INSIDE router.handle_category → ensure_folder →
    backup.create(). When the backup raises (e.g. Full Disk Access not granted →
    PermissionError → BackupError), the screen must record the error and keep the
    (un-moved) note in view at AWAIT_CATEGORY — never propagate and crash the app
    (BRDG-06 resilience + BKUP-06 abort-on-failed-backup).

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(id="err-1", title="Note", body="<p>b</p>", preview="b")
    structure = _make_projects_structure()
    app, mock_inner, spy = _make_app_with_spy(tui_config, [note], structure)
    spy.create.side_effect = BackupError(
        "backup failed: [Errno 1] Operation not permitted: NoteStore.sqlite"
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("x")  # archive → ensure_folder → backup.create() raises
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert isinstance(sort_screen, SortScreen), "TUI crashed off SortScreen"
        assert mock_inner.moves == [], f"note must NOT move on backup failure: {mock_inner.moves!r}"
        summary = sort_screen._session.summary()
        assert summary.errors == 1, f"expected 1 recorded error, got {summary!r}"
        assert summary.moved == 0
        assert sort_screen._router_state == RouterState.AWAIT_CATEGORY
        prompt_text = str(sort_screen.query_one("#prompt", Static).render())
        assert "Could not move" in prompt_text, prompt_text


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

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
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
    4. Wait for SortScreen._load_inbox worker to complete.
    5. Assert SortScreen is now on top of the screen stack.

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

        # Wait for _load_inbox thread worker on the newly pushed SortScreen.
        await app.workers.wait_for_complete()
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
    2. Wait for inbox to load (thread worker).
    3. Press 's' (skip).
    4. Assert: no moves on inner repo; session.skipped == 1; session.moved == 0.

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

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
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


# ---------------------------------------------------------------------------
# Regression: folder 11 reachable via arrows; digit alone does not move
# ---------------------------------------------------------------------------


def _make_12_areas_structure() -> ParaStructure:
    """Return a ParaStructure with Areas having 12 distinct leaf sub-folders.

    Areas has no "General" so order = given order (Folder01..Folder12).
    All sub-folders are leaf-level (no sub-subfolders), so selecting any one
    results in an immediate MOVE.

    Returns:
        A :class:`~notes_os.sorter.models.ParaStructure` with 12 Areas folders.
    """
    areas_folders = tuple(f"Folder{i:02d}" for i in range(1, 13))  # Folder01..Folder12
    return ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": (),
            "Areas": areas_folders,
            "Resources": (),
            "Archive": (),
        },
    )


async def test_folder_11_reachable_via_arrows(tui_config: SorterConfig) -> None:
    """Regression: folders 10+ are reachable via arrow navigation + Enter.

    With the old single-digit-instant model, pressing "1" at AWAIT_FOLDER would
    immediately move the note to folder 1 — and folders 10, 11, 12 were
    completely unreachable via keyboard.

    With the arrow-highlight + Enter model:
    - Press "a" → AWAIT_FOLDER, highlight=0 (Folder01).
    - Press "down" 10 times → highlight=10 (Folder11, 0-based index 10).
    - Press "enter" → moves note to ("Areas", "Folder11").

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(
        id="reg-11-1",
        title="Folder 11 Note",
        body="<p>areas</p>",
        preview="areas",
    )
    structure = _make_12_areas_structure()
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note], structure)

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Press "a" → enter AWAIT_FOLDER (highlight defaults to 0 = Folder01)
        await pilot.press("a")
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"Expected AWAIT_FOLDER after 'a', got {sort_screen._router_state}"
        )
        assert sort_screen._highlight == 0, (
            f"Expected highlight=0 on entry, got {sort_screen._highlight}"
        )

        # Navigate down 10 times to reach index 10 (Folder11, 0-based)
        for _ in range(10):
            await pilot.press("down")
            await pilot.pause()

        assert sort_screen._highlight == 10, (
            f"Expected highlight=10 after 10 downs, got {sort_screen._highlight}"
        )
        # No move yet — arrow keys only move the highlight
        assert len(mock_inner.moves) == 0, (
            f"Arrow keys must not move note; got {mock_inner.moves!r}"
        )

        # Press enter → confirms Folder11 (0-based index 10 → 1-based index 11)
        await pilot.press("enter")
        await pilot.pause()

        assert len(mock_inner.moves) == 1, f"Expected 1 move, got {mock_inner.moves!r}"
        _moved_id, moved_path = mock_inner.moves[0]
        assert moved_path == ("Areas", "Folder11"), (
            f"Expected ('Areas', 'Folder11'), got {moved_path!r}"
        )
        summary = sort_screen._session.summary()
        assert summary.moved == 1, f"Expected session.moved == 1, got {summary.moved}"


async def test_enter_with_carriage_return_character_selects(
    tui_config: SorterConfig,
) -> None:
    """Regression: Enter from a REAL terminal arrives as character='\\r', not 'enter'.

    ``on_key`` collapses ``event.character or event.key``; the Enter key sends a
    truthy carriage-return character that would shadow ``event.key='enter'`` and
    silently no-op the selection (Pilot's ``press('enter')`` sends character=None,
    so it masked the bug). on_key now normalizes named keys off event.key. This
    test dispatches a Key with character='\\r' to reproduce the real terminal.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(id="cr-1", title="Note", body="<p>b</p>", preview="b")
    structure = _make_12_areas_structure()
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note], structure)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("a")  # → AWAIT_FOLDER, highlight 0
        await pilot.pause()
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        for _ in range(10):
            await pilot.press("down")
            await pilot.pause()
        assert sort_screen._highlight == 10

        # Real-terminal Enter: key="enter" but character="\r" (carriage return).
        sort_screen.on_key(Key(key="enter", character="\r"))
        await pilot.pause()

        assert len(mock_inner.moves) == 1, (
            f"carriage-return Enter must select; got {mock_inner.moves!r}"
        )
        assert mock_inner.moves[0][1] == ("Areas", "Folder11")


async def test_digit_alone_does_not_move(tui_config: SorterConfig) -> None:
    """Regression: pressing a digit at AWAIT_FOLDER only jump-highlights; no move.

    Before the fix, pressing "1" would immediately move the note to folder 1.
    Now it should only update the highlight and leave the state at AWAIT_FOLDER,
    requiring an explicit Enter to confirm the selection.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(
        id="reg-digit-1",
        title="Digit No-Move Note",
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

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Press "p" → AWAIT_FOLDER
        await pilot.press("p")
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER

        # Press "1" → jump-highlight only, no move
        await pilot.press("1")
        await pilot.pause()

        assert len(mock_inner.moves) == 0, (
            f"Digit alone must not move note; got {mock_inner.moves!r}"
        )
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"State must remain AWAIT_FOLDER after digit, got {sort_screen._router_state}"
        )
        assert sort_screen._highlight == 0, (
            f"Highlight should be 0 (index of option '1'), got {sort_screen._highlight}"
        )

        # Press enter → now moves to folder 1 (General)
        await pilot.press("enter")
        await pilot.pause()

        assert len(mock_inner.moves) == 1, f"Expected 1 move after enter, got {mock_inner.moves!r}"
        _moved_id, moved_path = mock_inner.moves[0]
        assert moved_path == ("Projects", "General"), (
            f"Expected ('Projects', 'General'), got {moved_path!r}"
        )


# ---------------------------------------------------------------------------
# Phase 12: per-session backup cadence in the TUI (BKUP-07)
# ---------------------------------------------------------------------------


async def test_tui_one_backup_per_visit_and_rearm(tui_config: SorterConfig) -> None:
    """One SortScreen visit with N moves fires ONE backup; a new visit re-arms it.

    The archive path performs two write ops per move (ensure_folder + move_note),
    so two archived notes are FOUR write ops across the visit — yet the per-
    session latch means exactly ONE ``BackupManager.create()`` call for the whole
    visit (BKUP-07).  ``_apply_inbox_refs`` re-arms the latch on each fresh visit
    (the app-scoped repo is reused), so a SECOND visit's first move produces a
    SECOND backup.

    This proves the TUI re-arm seam end-to-end; the unit-level
    ``test_begin_session_rearms_backup`` covers the latch contract in isolation.

    Args:
        tui_config: SorterConfig fixture with all I/O paths under tmp_path.
    """
    notes = [
        _make_archive_note("visit1-a"),
        _make_archive_note("visit1-b"),
        _make_archive_note("visit2-a"),  # left for the second visit
    ]
    app, mock_inner, spy = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()

        # ---- Visit 1: archive two notes in a single session ----
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("x")  # archive note 1 (ensure_folder + move_note)
        await pilot.pause()
        await pilot.press("x")  # archive note 2 (ensure_folder + move_note)
        await pilot.pause()

        assert len(mock_inner.moves) == 2, f"two notes should move, got {mock_inner.moves!r}"
        assert spy.create.call_count == 1, (
            f"ONE backup for the whole visit (per-session latch), got {spy.create.call_count}"
        )

        # Return to Home, then start a fresh visit on the SAME app/repo.
        app.pop_screen()
        await pilot.pause()

        # ---- Visit 2: a new session must re-arm the latch ----
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # The re-arm happens in _apply_inbox_refs; the latch only fires create()
        # on the visit's FIRST write — archive the remaining note to trigger it.
        await pilot.press("x")
        await pilot.pause()

        assert len(mock_inner.moves) == 3, (
            f"third note should move on visit 2, got {mock_inner.moves!r}"
        )
        assert spy.create.call_count == 2, (
            f"a fresh SortScreen visit must re-arm the latch and back up again, "
            f"got {spy.create.call_count}"
        )


# ---------------------------------------------------------------------------
# PERF-01/02/03: background bulk paged preview load (Plan 10-02)
# ---------------------------------------------------------------------------


def _make_bulk_notes(count: int) -> list[Note]:
    """Return *count* notes with distinct ids and previews for bulk-load tests.

    Each note has id ``bulk-{i}`` and preview ``preview {i}`` so a test can
    assert which note's body landed (id-keyed cache merge) and that the real
    preview — not the "Loading preview…" placeholder — is rendered.

    Args:
        count: Number of notes to synthesise.

    Returns:
        A list of *count* :class:`~notes_os.sorter.models.Note` objects.
    """
    return [
        Note(
            id=f"bulk-{i}",
            title=f"Bulk Note {i}",
            body=f"<p>preview {i}</p>",
            preview=f"preview {i}",
        )
        for i in range(count)
    ]


async def test_small_inbox_single_bulk_no_indicator(tui_config: SorterConfig) -> None:
    """PERF-01: a <=threshold inbox fills the cache in one silent bulk call.

    Seed 5 notes (well under ``_BULK_THRESHOLD``).  After draining the bulk
    worker: every note body is in ``_note_cache``, ``_previews_streaming`` is
    False, the first note's REAL preview shows (not "Loading preview…"), and
    the ``#progress`` text never contains a "Loading previews…" indicator.

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = _make_bulk_notes(5)
    assert len(notes) <= _BULK_THRESHOLD
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Whole inbox is cached by the single silent bulk call.
        assert all(n.id in sort_screen._note_cache for n in notes), (
            f"Expected all ids cached, got {sorted(sort_screen._note_cache)!r}"
        )
        assert sort_screen._previews_streaming is False

        # First note's real preview is rendered (not the loading placeholder).
        preview_text = str(sort_screen.query_one("#note-preview", Static).render())
        assert "preview 0" in preview_text, preview_text
        assert "Loading preview" not in preview_text, preview_text

        # No streaming indicator was ever shown for a sub-threshold inbox.
        progress_text = str(sort_screen.query_one("#progress", Static).render())
        assert "Loading previews" not in progress_text, progress_text


async def test_large_inbox_paged_indicator_and_never_blocks(
    tui_config: SorterConfig,
) -> None:
    """PERF-02: a >threshold inbox streams pages with an N/M indicator; keys live.

    Seed ``_BULK_THRESHOLD + _BULK_PAGE_SIZE + 1`` notes (forces >=3 pages and
    is definitely over threshold).  The mock's ``get_inbox_note_bodies`` is
    wrapped to pause until released, so the indicator can be observed mid-stream
    and a keystroke proven non-blocking BEFORE all bodies have landed.

    Asserts:
    - (a) never-block: a skip keystroke pressed mid-stream is honored
      (``session.skipped == 1``) — the streaming body load did not gate the key.
    - (b) indicator lifecycle: mid-stream the ``#progress`` text contains
      "Loading previews…" and the "/M" fragment using the imported constant for
      M; after draining, the full cache is populated, ``_previews_streaming`` is
      False, and the indicator is gone.

    Args:
        tui_config: SorterConfig fixture.
    """
    total = _BULK_THRESHOLD + _BULK_PAGE_SIZE + 1
    notes = _make_bulk_notes(total)
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    # Gate the bulk page fetch so we can observe the streaming state mid-flight.
    # The FIRST page is released immediately (so the screen is interactive and a
    # keystroke can be sent); subsequent pages block on the gate until set.
    gate = threading.Event()
    first_page_done = threading.Event()
    real_bodies = mock_inner.get_inbox_note_bodies

    def gated_bodies(offset: int, count: int) -> list[Note]:
        if offset == 0:
            result = real_bodies(offset, count)
            first_page_done.set()
            return result
        gate.wait(timeout=5.0)
        return real_bodies(offset, count)

    mock_inner.get_inbox_note_bodies = gated_bodies  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Wait for the first page to land while later pages are still gated.
        while not first_page_done.is_set():
            await pilot.pause()
        await pilot.pause()

        # Indicator is live mid-stream: "Loading previews… N/M" with M == total.
        assert sort_screen._previews_streaming is True
        progress_mid = str(sort_screen.query_one("#progress", Static).render())
        assert "Loading previews" in progress_mid, progress_mid
        assert f"/{total}" in progress_mid, progress_mid
        assert sort_screen._previews_total == total

        # (a) Never-block: a skip keystroke is honored while bodies still stream.
        await pilot.press("s")
        await pilot.pause()
        assert sort_screen._session.summary().skipped == 1, (
            "skip keystroke must be honored mid-stream (body load must not block keys)"
        )

        # Release the gate and drain the remaining pages.
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # (b) Lifecycle: all bodies merged, streaming cleared, indicator gone.
        assert sort_screen._previews_streaming is False
        assert all(n.id in sort_screen._note_cache for n in notes), (
            f"Expected all {total} ids cached, got {len(sort_screen._note_cache)}"
        )
        progress_done = str(sort_screen.query_one("#progress", Static).render())
        assert "Loading previews" not in progress_done, progress_done


async def test_cold_note_resolves_via_get_note_fallback(
    tui_config: SorterConfig,
) -> None:
    """PERF-03: a note reached before its page lands resolves via get_note.

    Force the cache-miss path: stub the bulk fetch to return ``[]`` (a page that
    never arrives / errored), so the bulk load leaves ``_note_cache`` empty.
    Spy on ``get_note``.  When the screen renders the current note, the cache
    miss must route through the by-id ``get_note`` fallback and resolve the real
    preview — proving the single-note fallback survives the ``_prefetch_next``
    retirement.

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = _make_bulk_notes(3)
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    # Simulate a bulk page that never arrives — leaves _note_cache empty so the
    # render hits the by-id fallback.
    mock_inner.get_inbox_note_bodies = lambda offset, count: []  # type: ignore[method-assign]
    get_note_spy = MagicMock(side_effect=mock_inner.get_note)
    mock_inner.get_note = get_note_spy  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Bulk path left the cache empty; the by-id fallback was kicked.
        get_note_spy.assert_any_call("bulk-0")

        # After the fallback worker drains, the real preview is rendered.
        await app.workers.wait_for_complete()
        await pilot.pause()
        preview_text = str(sort_screen.query_one("#note-preview", Static).render())
        assert "preview 0" in preview_text, preview_text
        assert "Loading preview" not in preview_text, preview_text
