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

from notes_os.app import NotesOSApp, ResumePromptModal
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup
from notes_os.exceptions import BackupError, NotesMoveError
from notes_os.screens.sort import (
    _BULK_PAGE_SIZE,
    _BULK_THRESHOLD,
    _CATEGORY_PROMPT,
    _NOTHING_TO_UNDO,
    _PREVIEW_SKELETON,
    _PREVIEW_SKELETON_CLASS,
    SortScreen,
)
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.resume import ResumeStore, SessionState
from notes_os.sorter.router import RouterState


if TYPE_CHECKING:
    from pathlib import Path

    from notes_os.config import SorterConfig
    from notes_os.sorter.models import FolderPath
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

    Updated for Phase 13-02's off-thread write: the move is now deferred
    (``defer_writes=True``) and runs on the serialized drainer.  When the backup
    raises (e.g. Full Disk Access not granted → PermissionError → BackupError) the
    worker's write fails, so the screen surfaces it via ``_on_write_failed``:
    the optimistic move is reconciled to an error (``record_move_failure``),
    tracked in ``_failed_moves``, and the note stays in the inbox — the app never
    crashes (BRDG-06 resilience + BKUP-06 + PERF-05).

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

        await pilot.press("x")  # archive → deferred → worker write → backup.create() raises
        await pilot.pause()
        await app.workers.wait_for_complete()  # drain the failing write
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert isinstance(sort_screen, SortScreen), "TUI crashed off SortScreen"
        assert mock_inner.moves == [], f"note must NOT move on backup failure: {mock_inner.moves!r}"
        summary = sort_screen._session.summary()
        assert summary.errors == 1, f"expected 1 recorded error, got {summary!r}"
        assert summary.moved == 0
        assert len(sort_screen._failed_moves) == 1, "failed move must be tracked"
        assert sort_screen._failed_moves[0][0] == "err-1"


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


# ---------------------------------------------------------------------------
# Phase 11: dim skeleton placeholder while the body loads (UX-01)
# ---------------------------------------------------------------------------


async def test_skeleton_shown_until_body_lands(tui_config: SorterConfig) -> None:
    """UX-01: a not-yet-cached note shows the dim skeleton; the real preview replaces it.

    Force the cache-miss path so the FIRST render happens with the current note's
    body NOT yet cached: stub ``get_inbox_note_bodies`` to return ``[]`` (the bulk
    page never lands) and GATE the by-id ``get_note`` fallback on a
    ``threading.Event`` so the skeleton state is observable deterministically.

    Pre-load (gate held): ``#note-preview`` renders ``_PREVIEW_SKELETON`` (and NOT
    the old "Loading preview" text) and the Static carries the
    ``_PREVIEW_SKELETON_CLASS`` (``preview-loading``) CSS class.

    Post-load (gate released, fallback drains): the Static no longer has the
    ``preview-loading`` class and ``#note-preview`` shows the real preview text.

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = _make_bulk_notes(1)
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    # Bulk page never arrives → render hits the by-id fallback (cache miss).
    mock_inner.get_inbox_note_bodies = lambda offset, count: []  # type: ignore[method-assign]

    # Gate the single-note fallback so the skeleton is observable before the body
    # lands (deterministic; the worker would otherwise drain during the pause).
    gate = threading.Event()
    real_get_note = mock_inner.get_note

    def gated_get_note(note_id: str) -> Note:
        gate.wait(timeout=5.0)
        return real_get_note(note_id)

    mock_inner.get_note = gated_get_note  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        # Do NOT wait_for_complete — the gated fallback is still in flight, so the
        # current note's body is withheld and the skeleton must be showing.
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        preview = sort_screen.query_one("#note-preview", Static)

        # Pre-load: dim skeleton + preview-loading class, NOT the old loading text.
        assert preview.has_class(_PREVIEW_SKELETON_CLASS), (
            "the #note-preview Static must carry the preview-loading class while loading"
        )
        skeleton_text = str(preview.render())
        assert _PREVIEW_SKELETON in skeleton_text, skeleton_text
        assert "Loading preview" not in skeleton_text, skeleton_text

        # Release the gate and let the by-id fallback resolve the real body.
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Post-load: class removed, real preview shown (never dim once loaded).
        assert not preview.has_class(_PREVIEW_SKELETON_CLASS), (
            "the preview-loading class must be removed once the real preview lands"
        )
        loaded_text = str(preview.render())
        assert "preview 0" in loaded_text, loaded_text
        assert _PREVIEW_SKELETON not in loaded_text, loaded_text


async def test_category_prompt_live_while_body_streams(tui_config: SorterConfig) -> None:
    """UX-04: the action line is live from first paint while the body still streams.

    Regression guard for UX-04: the ``#prompt`` category line must render the live
    ``_CATEGORY_PROMPT`` the instant the note title shows — even while the body is
    still loading and ``#note-preview`` shows the Phase-11 skeleton — and a category
    keystroke (here ``'x'`` → Archive) must be honored without waiting for the body.

    The body is withheld deterministically (the same cache-miss pattern as
    ``test_skeleton_shown_until_body_lands``): ``get_inbox_note_bodies`` returns
    ``[]`` so the bulk page never lands, and the by-id ``get_note`` fallback is
    gated on an un-set ``threading.Event`` so the skeleton state is observable.
    Workers are NOT drained before the assertions, so the body is provably still
    streaming.

    Pre-keystroke (gate held): ``#note-preview`` carries ``_PREVIEW_SKELETON_CLASS``
    (body not loaded), ``#prompt`` renders ``_CATEGORY_PROMPT`` (live action line),
    and the router is at ``AWAIT_CATEGORY``. Pressing ``'x'`` then records a move
    (``summary().moved == 1``) — proving the category move was honored mid-stream.

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = [_make_archive_note("ux04-note-1")]
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    # Bulk page never arrives → the current note's body is withheld (cache miss).
    mock_inner.get_inbox_note_bodies = lambda offset, count: []  # type: ignore[method-assign]

    # Gate the single-note fallback so the body stays unloaded (skeleton observable)
    # across the keystroke; the worker would otherwise drain during the pause.
    gate = threading.Event()
    real_get_note = mock_inner.get_note

    def gated_get_note(note_id: str) -> Note:
        gate.wait(timeout=5.0)
        return real_get_note(note_id)

    mock_inner.get_note = gated_get_note  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        # Do NOT wait_for_complete — the gated fallback is still in flight, so the
        # body is still streaming and the skeleton must be showing.
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        preview = sort_screen.query_one("#note-preview", Static)
        prompt = sort_screen.query_one("#prompt", Static)

        # Body still streaming: the skeleton is on #note-preview …
        assert preview.has_class(_PREVIEW_SKELETON_CLASS), (
            "the #note-preview Static must carry the preview-loading class while loading"
        )
        # … but the action line is ALREADY live (UX-04 — never gated on body load).
        prompt_text = str(prompt.render())
        assert _CATEGORY_PROMPT in prompt_text, prompt_text
        assert sort_screen._router_state is RouterState.AWAIT_CATEGORY

        # A category keystroke is honored while the body still streams.
        await pilot.press("x")
        await pilot.pause()
        assert sort_screen._session.summary().moved == 1, (
            "a category move must be honored while the body is still loading"
        )

        # Release the gate so the gated worker can drain cleanly before teardown.
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()


# ---------------------------------------------------------------------------
# Phase 13-02: optimistic advance + serialized off-thread write (PERF-04/05)
# ---------------------------------------------------------------------------


async def test_move_advances_optimistically_before_write(
    tui_config: SorterConfig,
) -> None:
    """PERF-04: a move advances synchronously; the write is queued, not inline.

    Push a two-note inbox, press 'x', and pause ONCE (do NOT drain workers).
    The screen must ALREADY have advanced — ``moved == 1`` and ``_index == 1`` —
    with the write still pending (queued or a writer in flight), proving the move
    was dispatched off-thread and never blocked the event loop.  After draining,
    the inner repo recorded the move and exactly one backup create() fired.

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = [_make_archive_note("opt-1"), _make_archive_note("opt-2")]
    app, mock_inner, spy_manager = _make_app_with_spy(tui_config, notes)

    # Gate the worker write so the "still pending" state is observable
    # deterministically (the thread worker would otherwise drain during the pause).
    gate = threading.Event()
    real_move = mock_inner.move_note

    def gated_move(note_id: str, folder_path: FolderPath) -> None:
        gate.wait(timeout=5.0)
        real_move(note_id, folder_path)

    mock_inner.move_note = gated_move  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        await pilot.press("x")
        await pilot.pause()

        # Advanced optimistically while the gated write is still in flight.
        assert sort_screen._session.summary().moved == 1
        assert sort_screen._index == 1, f"expected advance to index 1, got {sort_screen._index}"
        assert sort_screen._writer_active is True, "move must be in flight off-thread, not inline"

        # Release the gate and drain the write worker — the move and one backup land.
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(mock_inner.moves) == 1, (
            f"expected the queued move to land, got {mock_inner.moves!r}"
        )
        assert mock_inner.moves[0][0] == "opt-1"
        assert spy_manager.create.call_count == 1


async def test_router_runs_in_defer_writes_mode(tui_config: SorterConfig) -> None:
    """PERF-04: the SortScreen Router is constructed with defer_writes=True.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_archive_note("defer-1")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router is not None
        assert sort_screen._router._defer_writes is True


async def test_rapid_moves_never_freeze(tui_config: SorterConfig) -> None:
    """PERF-04: a skip issued right after a move is honored — the loop never froze.

    Press 'x' (move note 1) then immediately 's' (skip note 2) with only a
    ``pilot.pause()`` between (no ``wait_for_complete``).  BOTH must be honored —
    ``moved == 1``, ``skipped == 1``, ``_index == 2`` — proving the event loop
    stayed responsive while the move's write was still in flight.  After draining,
    the one move landed and exactly one backup create() fired.

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = [_make_archive_note("rapid-1"), _make_archive_note("rapid-2")]
    app, mock_inner, spy_manager = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        await pilot.press("x")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        assert sort_screen._session.summary().moved == 1
        assert sort_screen._session.summary().skipped == 1
        assert sort_screen._index == 2, (
            f"both keystrokes must advance; got index {sort_screen._index}"
        )

        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(mock_inner.moves) == 1, f"expected one landed move, got {mock_inner.moves!r}"
        assert spy_manager.create.call_count == 1


async def test_serialized_writes_one_backup_fifo_order(
    tui_config: SorterConfig,
) -> None:
    """Serialized single-writer: two moves keep FIFO order with ONE backup.

    Press 'x', pause, 'x', pause, then drain.  The inner repo's moves preserve
    enqueue order (note 1 before note 2 — T-13-06) and exactly one backup
    create() fired for the whole session (the per-session latch was not corrupted
    by concurrency — T-13-05).

    Args:
        tui_config: SorterConfig fixture.
    """
    notes = [_make_archive_note("fifo-1"), _make_archive_note("fifo-2")]
    app, mock_inner, spy_manager = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()

        await app.workers.wait_for_complete()
        await pilot.pause()

        assert [m[0] for m in mock_inner.moves] == ["fifo-1", "fifo-2"], (
            f"moves must preserve FIFO order, got {mock_inner.moves!r}"
        )
        assert spy_manager.create.call_count == 1, (
            f"exactly one session backup (single-writer latch safe), got "
            f"{spy_manager.create.call_count}"
        )


async def test_failed_write_surfaced_recorded_and_note_retained(
    tui_config: SorterConfig,
) -> None:
    """PERF-05: a failed off-thread write is surfaced, recorded, and the note kept.

    Inject a worker ``move_note`` failure for the target note.  The screen
    advances optimistically (``moved == 1`` immediately).  After draining, the
    move is reconciled to an error (``moved == 0`` / ``errors == 1`` via
    ``record_move_failure``), ``_failed_moves`` names the note, the note is
    RETAINED in the inner inbox (never dropped), and the TUI did not crash.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_archive_note("fail-1")
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note])

    # Gate the failing write so the OPTIMISTIC move count is observable before
    # the worker reconciles it to an error (deterministic; no thread-timing race).
    gate = threading.Event()

    def gated_failing_move(note_id: str, folder_path: FolderPath) -> None:
        gate.wait(timeout=5.0)
        raise NotesMoveError(note_id)

    mock_inner.move_note = gated_failing_move  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        await pilot.press("x")
        await pilot.pause()
        # Optimistic count before the gated worker write fails.
        assert sort_screen._session.summary().moved == 1

        # Release the gate — the worker write raises and reconciles the count.
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Reconciled: move → error.
        summary = sort_screen._session.summary()
        assert summary.moved == 0, f"failed move must be reconciled to 0, got {summary.moved}"
        assert summary.errors == 1, f"expected 1 error after reconcile, got {summary.errors}"

        # Tracked in the needs-attention list, naming the note.
        assert len(sort_screen._failed_moves) == 1
        failed_id, _failed_display, _failed_msg = sort_screen._failed_moves[0]
        assert failed_id == "fail-1"

        # Note RETAINED — move_note raised before removing it from the inbox.
        inbox_ids = {n.id for n in mock_inner.get_inbox_notes()}
        assert "fail-1" in inbox_ids, "failed note must stay in the inbox (never dropped)"

        # No write recorded; TUI still alive.  (notify is a non-blocking toast.)
        assert mock_inner.moves == []
        assert isinstance(app.screen, SortScreen)


async def test_finish_drains_before_summary(tui_config: SorterConfig) -> None:
    """T-13-08: finish defers until writes drain; the summary reflects the failure.

    A single note FAILS its worker write.  Pressing 'x' advances to the end and
    reaches ``_finish`` while the write is still in flight → ``_finish_pending``
    is True right after the keystroke (summary not yet finalized).  After
    draining, the failure landed in the FINAL summary (Errors 1 / Moved 0 with a
    "Needs attention" line naming the note) and ``app.sort_in_progress`` is False
    only after the drain completed.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_archive_note("drain-1")
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note])

    # Gate the failing write so _finish_pending is observable while the write is
    # still in flight (deterministic; the worker would otherwise drain in the pause).
    gate = threading.Event()

    def gated_failing_move(note_id: str, folder_path: FolderPath) -> None:
        gate.wait(timeout=5.0)
        raise NotesMoveError(note_id)

    mock_inner.move_note = gated_failing_move  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        await pilot.press("x")
        await pilot.pause()
        # Finish was deferred while the gated write is in flight (drain-before-summary).
        assert sort_screen._finish_pending is True
        assert app.sort_in_progress is True, "guard must stay armed while writes pend"

        # Release the gate — the write fails, the drainer completes the finish.
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Finish completed after the drain — failure reflected in the final summary.
        summary = sort_screen._session.summary()
        assert summary.errors == 1
        assert summary.moved == 0
        preview_text = str(sort_screen.query_one("#note-preview", Static).render())
        assert "Errors:  1" in preview_text, preview_text
        assert "Moved:   0" in preview_text, preview_text
        assert "Needs attention" in preview_text, preview_text
        assert "drain-1" in preview_text, preview_text
        # Guard cleared only after the drain completed the finish.
        assert app.sort_in_progress is False


async def test_drained_requeue_rearms_writer(tui_config: SorterConfig) -> None:
    """T-13-09 lost-wakeup: _on_writer_drained re-arms when an item arrived in the gap.

    Drive the re-check branch deterministically (no thread-timing reliance): with
    the writer idle, append an item to ``_write_queue`` while ``_writer_active`` is
    False, then call ``_on_writer_drained()`` directly on the main thread.  It MUST
    re-arm (clear flag → re-check non-empty queue → restart drainer).  A regression
    that reorders the clear/re-check would leave the item stranded — caught here by
    asserting the queued move is actually written after draining.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_archive_note("wake-1")
    app, mock_inner, _spy = _make_app_with_spy(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Writer idle; simulate an item enqueued in the lost-wakeup gap.
        assert sort_screen._writer_active is False
        sort_screen._write_queue.append(("wake-1", ("Archive", "2026"), "Archive › 2026"))
        sort_screen._on_writer_drained()

        # Re-armed: a fresh drainer was started for the stranded item.
        assert sort_screen._writer_active is True

        # Drain it and confirm the queued move was actually written (not stranded).
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert ("wake-1", ("Archive", "2026")) in mock_inner.moves, (
            f"lost-wakeup item must be written after re-arm, got {mock_inner.moves!r}"
        )
        assert len(sort_screen._write_queue) == 0
        assert sort_screen._writer_active is False


# ---------------------------------------------------------------------------
# Phase 14: undo last action (UX-02)
# ---------------------------------------------------------------------------


async def test_move_then_undo_restores_note_count_and_position(
    tui_config: SorterConfig,
) -> None:
    """UX-02: undo a move — note returns to the inbox, count and position restored.

    Move one note to Archive via 'x' and drain.  Assert ``moved == 1``, the note
    left the inbox, and ``_index`` advanced to 1.  Press 'U', drain the queued
    move-back, then assert ``moved == 0``, ``_index == 0``, a move-back to the
    captured inbox path ``("Notes",)`` is recorded on the inner repo, and the note
    is back in ``get_inbox_notes()``.  The move-back routes through the Phase-13
    serialized ``_enqueue_write`` queue (never a synchronous write).

    Args:
        tui_config: SorterConfig fixture.
    """
    # A trailing note keeps the session OPEN after the first move (a single-note
    # inbox would finish the session and set _inbox_empty=True, where U is a no-op).
    notes = [_make_archive_note("undo-move-1"), _make_archive_note("undo-move-tail")]
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Move the note and drain the off-thread write.
        await pilot.press("x")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert sort_screen._session.summary().moved == 1
        assert sort_screen._index == 1
        assert "undo-move-1" not in {n.id for n in mock_inner.get_inbox_notes()}

        # Undo the move — enqueues a move-back; drain it.
        await pilot.press("u")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Count + position reversed.
        assert sort_screen._session.summary().moved == 0, "undo must decrement moved"
        assert sort_screen._index == 0, f"undo must step _index back, got {sort_screen._index}"
        assert sort_screen._router_state is RouterState.AWAIT_CATEGORY

        # A move-back to the captured inbox path was queued + written.
        assert ("undo-move-1", ("Notes",)) in mock_inner.moves, (
            f"move-back to the inbox must be recorded, got {mock_inner.moves!r}"
        )

        # The note is back in the inbox (move-back restored membership via the mock).
        assert "undo-move-1" in {n.id for n in mock_inner.get_inbox_notes()}, (
            "the undone note must be back in the inbox"
        )


async def test_skip_then_undo_steps_back_no_write(tui_config: SorterConfig) -> None:
    """UX-02: undo a skip — pointer steps back, ``skipped`` decrements, NO write.

    Skip one note via 's' (``_index`` 0→1, ``skipped == 1``).  Press 'U' and pause.
    Assert ``skipped == 0``, ``_index == 0``, router back at AWAIT_CATEGORY, and
    NO new entry on ``mock_inner.moves`` (a skip-undo writes nothing).

    Args:
        tui_config: SorterConfig fixture.
    """
    # A trailing note keeps the session OPEN after the skip (a single-note inbox
    # would finish and set _inbox_empty=True, where U is a no-op).
    notes = [
        Note(id="undo-skip-1", title="Skip Note", body="<p>s</p>", preview="s"),
        Note(id="undo-skip-tail", title="Tail", body="<p>t</p>", preview="t"),
    ]
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        await pilot.press("s")
        await pilot.pause()
        assert sort_screen._session.summary().skipped == 1
        assert sort_screen._index == 1

        await pilot.press("u")
        await pilot.pause()

        assert sort_screen._session.summary().skipped == 0, "undo must decrement skipped"
        assert sort_screen._index == 0, f"undo must step _index back, got {sort_screen._index}"
        assert sort_screen._router_state is RouterState.AWAIT_CATEGORY
        assert mock_inner.moves == [], f"skip-undo must write nothing, got {mock_inner.moves!r}"


async def test_undo_repeatable_to_session_start(tui_config: SorterConfig) -> None:
    """UX-02: undo is repeatable LIFO to session start; a third press is a no-op.

    Move note 0 (drain), skip note 1 (``_index == 2``).  Press 'U' (undo the skip
    → ``_index 1``, ``skipped 0``).  Press 'U' (undo the move → ``_index 0``,
    ``moved 0``, move-back enqueued; drain).  Press 'U' a THIRD time → no-op:
    ``_index`` stays 0 and counters are unchanged.

    Args:
        tui_config: SorterConfig fixture.
    """
    # A trailing note keeps the session OPEN after move-0 + skip-1 (otherwise the
    # session finishes at index 2 and _inbox_empty=True blocks U).
    notes = [
        _make_archive_note("rep-move-0"),
        Note(id="rep-skip-1", title="Skip", body="<p>s</p>", preview="s"),
        Note(id="rep-tail-2", title="Tail", body="<p>t</p>", preview="t"),
    ]
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Move note 0, then skip note 1 → index advances to 2.
        await pilot.press("x")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert sort_screen._index == 2
        assert sort_screen._session.summary().moved == 1
        assert sort_screen._session.summary().skipped == 1

        # Undo the skip (LIFO top) → index 1, skipped 0.
        await pilot.press("u")
        await pilot.pause()
        assert sort_screen._index == 1
        assert sort_screen._session.summary().skipped == 0
        assert sort_screen._session.summary().moved == 1

        # Undo the move → index 0, moved 0, move-back enqueued; drain it.
        await pilot.press("u")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert sort_screen._index == 0
        assert sort_screen._session.summary().moved == 0
        assert ("rep-move-0", ("Notes",)) in mock_inner.moves

        # Third undo → nothing left: no-op (index + counters unchanged).
        await pilot.press("u")
        await pilot.pause()
        assert sort_screen._index == 0, "a third undo at session start must not move the pointer"
        assert sort_screen._session.summary().moved == 0
        assert sort_screen._session.summary().skipped == 0


async def test_undo_empty_stack_is_noop_with_hint(tui_config: SorterConfig) -> None:
    """UX-02: ``U`` with an empty undo stack is a no-op and surfaces the hint.

    Seed one note, do nothing, press 'U'.  Assert ``_index``/``moved``/``skipped``
    are all unchanged and that ``notify`` was called with :data:`_NOTHING_TO_UNDO`
    (the brief no-op hint).  ``screen.notify`` is replaced with a ``MagicMock`` spy
    (the suite's existing spy style) so the hint assertion is deterministic.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = Note(id="undo-empty-1", title="Note", body="<p>n</p>", preview="n")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen())
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        notify_spy = MagicMock()
        sort_screen.notify = notify_spy  # type: ignore[method-assign]

        await pilot.press("u")
        await pilot.pause()

        # No-op: nothing changed.
        assert sort_screen._index == 0
        assert sort_screen._session.summary().moved == 0
        assert sort_screen._session.summary().skipped == 0
        assert isinstance(app.screen, SortScreen), "empty-stack undo must not crash"

        # The brief hint was surfaced.
        notify_spy.assert_called_once_with(_NOTHING_TO_UNDO)


async def test_undo_move_back_failure_surfaced_without_corruption(
    tui_config: SorterConfig,
) -> None:
    """UX-02 / T-14-05: a failed undo move-back is surfaced without crash or corruption.

    Move one note (drain).  Then GATE the move-back's ``move_note`` to raise
    ``NotesMoveError``.  Press 'U', release the gate, drain.  Assert the app is
    still a SortScreen (no crash), counts are non-negative and sane, and the failed
    move-back was recorded in ``_failed_moves`` via the EXISTING ``_on_write_failed``
    path (no bespoke failure handling).  Mirrors
    ``test_failed_write_surfaced_recorded_and_note_retained``.

    Args:
        tui_config: SorterConfig fixture.
    """
    # A trailing note keeps the session OPEN after the move (so U is dispatched).
    notes = [_make_archive_note("undo-fail-1"), _make_archive_note("undo-fail-tail")]
    app, mock_inner, _spy = _make_app_with_spy(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(year_provider=lambda: 2026))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]

        # Move the note successfully and drain.
        await pilot.press("x")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert sort_screen._session.summary().moved == 1

        # Gate the move-back so it fails deterministically off-thread.
        gate = threading.Event()

        def gated_failing_move(note_id: str, folder_path: FolderPath) -> None:
            gate.wait(timeout=5.0)
            raise NotesMoveError(note_id)

        mock_inner.move_note = gated_failing_move  # type: ignore[method-assign]

        # Undo → enqueues the move-back; release the gate and drain.
        await pilot.press("u")
        await pilot.pause()
        # pop_undo already decremented moved to 0 optimistically.
        assert sort_screen._session.summary().moved == 0

        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # No crash; counts non-negative and sane.
        assert isinstance(app.screen, SortScreen), "undo move-back failure must not crash the TUI"
        summary = sort_screen._session.summary()
        assert summary.moved >= 0, f"moved must stay non-negative, got {summary.moved}"
        assert summary.skipped >= 0

        # The failed move-back surfaced through the EXISTING _on_write_failed path.
        assert len(sort_screen._failed_moves) == 1, "failed move-back must be tracked"
        assert sort_screen._failed_moves[0][0] == "undo-fail-1"


# ---------------------------------------------------------------------------
# Session resume (UX-03) — save points, always-ask modal, clear points
# ---------------------------------------------------------------------------

# Fixed clock injected as ``now_provider`` so the persisted ``saved_at`` is
# deterministic across runs (CLAUDE.md inject-the-clock; no wall-clock reliance).
_RESUME_SAVED_AT = datetime(2026, 6, 9, 10, 30, 0)


def _resume_notes(count: int) -> list[Note]:
    """Return *count* distinct notes for a resume-session inbox.

    Each note has a stable, position-encoded id (``r-note-0``..) so a test can
    assert the saved ``note_ids`` signature and the resumed ``_index`` deterministically.

    Args:
        count: Number of notes to build (the inbox size).

    Returns:
        A list of *count* distinct :class:`~notes_os.sorter.models.Note` objects.
    """
    return [
        Note(id=f"r-note-{i}", title=f"Resume Note {i}", body=f"<p>n{i}</p>", preview=f"n{i}")
        for i in range(count)
    ]


async def test_advance_saves_session_state(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 save-point: skipping a note persists a matching SessionState.

    Skip note 0 of a 3-note inbox; the per-note save at the end of ``_advance``
    must persist a state with the current inbox folder, the exact id signature,
    the NEW ``_index == 1``, and ``skipped == 1`` / ``moved == 0``.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()

        state = store.load()
        assert state is not None, "advance must persist a session state"
        assert state.inbox_folder == "Notes", state.inbox_folder
        assert state.note_ids == ("r-note-0", "r-note-1", "r-note-2"), state.note_ids
        assert state.index == 1, state.index
        assert state.skipped == 1, state.skipped
        assert state.moved == 0, state.moved
        assert state.saved_at == _RESUME_SAVED_AT


async def test_leave_mid_session_saves_state(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 save-point: Esc at AWAIT_CATEGORY after starting persists the position.

    Skip one note (index → 1), then press Esc to leave; ``action_back`` must save
    BEFORE ``pop_screen`` so the INJECTED store (held by reference here, since the
    popped screen's ``_store`` is detached) reports ``index == 1``.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("s")  # index → 1
        await pilot.pause()
        await pilot.press("escape")  # leave mid-session — pops the screen
        await pilot.pause()

        state = store.load()
        assert state is not None, "leave-mid-session must persist a state before pop"
        assert state.index == 1, state.index


async def test_leave_at_index_zero_does_not_save(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 save-point guard: leaving an unstarted (index-0) session saves nothing.

    Push the screen, immediately press Esc without processing a note; the save-point
    guard (``0 < _index < len(refs)``) suppresses the save, so ``store.load()`` is None.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("escape")  # leave with index still 0
        await pilot.pause()

        assert store.load() is None, "an unstarted (index-0) session must not be saved"


async def test_empty_inbox_never_saves(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 save-point guard: an empty inbox saves nothing.

    Push the screen over an EMPTY inbox; ``_inbox_empty`` is True so no save point
    can fire and ``store.load()`` is None.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, [])

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert store.load() is None, "an empty inbox must never save a resume state"


async def test_finish_leaves_no_saved_session_state(
    tui_config: SorterConfig, tmp_path: Path
) -> None:
    """UX-03: finishing a single-note session leaves no resumable file.

    The per-note save is suppressed at the finish boundary (``_index >= len(refs)``)
    AND ``_complete_finish`` explicitly clears — so after the only note is skipped,
    ``store.load()`` is None.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(1))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("s")  # skip the only note → session finishes
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert store.load() is None, "a finished session must leave no resumable file"


async def test_matching_state_resume_lands_and_restores_counts(
    tui_config: SorterConfig, tmp_path: Path
) -> None:
    """UX-03 success criterion 1: a matching saved state → modal → Resume.

    Pre-save a matching state (index=2, moved=1, skipped=1).  Push the screen; a
    ResumePromptModal must appear.  Press 'y' (Resume): ``_index == 2`` and the
    restored counts (moved=1, skipped=1, errors=0) carry into the session.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    store.save(
        SessionState(
            inbox_folder="Notes",
            note_ids=("r-note-0", "r-note-1", "r-note-2"),
            index=2,
            moved=1,
            skipped=1,
            errors=0,
            saved_at=_RESUME_SAVED_AT,
        )
    )
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, ResumePromptModal), (
            f"a matching saved state must always ask, got {type(app.screen)}"
        )

        await pilot.press("y")  # Resume
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert isinstance(sort_screen, SortScreen), type(sort_screen)
        assert sort_screen._index == 2, sort_screen._index
        summary = sort_screen._session.summary()
        assert (summary.moved, summary.skipped, summary.errors) == (1, 1, 0), summary


async def test_start_over_clears_and_resets_index(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 success criterion 2: Start over clears the saved state and resets to 0.

    Same pre-saved matching state; on the modal press 'n' (Start over): ``_index == 0``,
    ``store.load()`` is None (cleared), and the session counts are all zero (fresh).

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    store.save(
        SessionState(
            inbox_folder="Notes",
            note_ids=("r-note-0", "r-note-1", "r-note-2"),
            index=2,
            moved=1,
            skipped=1,
            errors=0,
            saved_at=_RESUME_SAVED_AT,
        )
    )
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, ResumePromptModal), type(app.screen)

        await pilot.press("n")  # Start over
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert isinstance(sort_screen, SortScreen), type(sort_screen)
        assert sort_screen._index == 0, sort_screen._index
        assert store.load() is None, "Start over must clear the saved state"
        summary = sort_screen._session.summary()
        assert (summary.moved, summary.skipped, summary.errors) == (0, 0, 0), summary


async def test_stale_ids_no_prompt_index_zero_and_cleared(
    tui_config: SorterConfig, tmp_path: Path
) -> None:
    """UX-03 success criterion 3: a stale id signature → no prompt, index 0, cleared.

    Pre-save a state whose ``note_ids`` do NOT match the current inbox; the screen
    must render directly (NO ResumePromptModal), land at ``_index == 0``, and clear
    the stale file so it can never mislead a later launch.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    store.save(
        SessionState(
            inbox_folder="Notes",
            note_ids=("x", "y", "z"),  # do not match the r-note-* inbox
            index=2,
            moved=1,
            skipped=0,
            errors=0,
            saved_at=_RESUME_SAVED_AT,
        )
    )
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"a stale signature must NOT prompt, got {type(app.screen)}"
        )
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._index == 0, sort_screen._index
        assert store.load() is None, "a stale file must be cleared"


async def test_no_saved_state_no_prompt(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03: an empty store renders directly with no prompt at index 0.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), type(app.screen)
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._index == 0, sort_screen._index


async def test_out_of_range_index_no_prompt(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 / T-15-07: a matching state with an out-of-range index → no prompt, index 0.

    Pre-save a matching-ids state with ``index == len(refs)`` (out of range).  The
    in-range bound (``0 < index < len(refs)``) filters it to start-over: no modal,
    ``_index == 0``.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    store.save(
        SessionState(
            inbox_folder="Notes",
            note_ids=("r-note-0", "r-note-1", "r-note-2"),
            index=3,  # == len(refs) — out of range
            moved=2,
            skipped=1,
            errors=0,
            saved_at=_RESUME_SAVED_AT,
        )
    )
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"an out-of-range index must NOT prompt, got {type(app.screen)}"
        )
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._index == 0, sort_screen._index


async def test_resume_to_finish_clears_state(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 / T-15-10: resuming into the last note and finishing clears the state.

    Pre-save a matching state at index=2 of a 3-note inbox.  Resume, then skip the
    final note so the session finishes; ``_complete_finish`` clears, so
    ``store.load()`` is None afterwards.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    store.save(
        SessionState(
            inbox_folder="Notes",
            note_ids=("r-note-0", "r-note-1", "r-note-2"),
            index=2,
            moved=1,
            skipped=1,
            errors=0,
            saved_at=_RESUME_SAVED_AT,
        )
    )
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, ResumePromptModal), type(app.screen)
        await pilot.press("y")  # Resume at index 2 (last note)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("s")  # skip last note → finish
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert store.load() is None, "a resumed session that finishes must clear its state"


async def test_previews_load_on_resumed_note(tui_config: SorterConfig, tmp_path: Path) -> None:
    """UX-03 / T-15-09: the resumed note's real preview loads (no bulk-load race).

    Resume into index=2 on a small inbox; after workers + pause the current note's
    preview must be the real body (the id-keyed bulk cache resolved the resumed
    note — Phase-10 self-correcting guard), not the dim skeleton placeholder.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: Per-test temp dir for the injected store.
    """
    store = ResumeStore(path=tmp_path / "session-state.json")
    store.save(
        SessionState(
            inbox_folder="Notes",
            note_ids=("r-note-0", "r-note-1", "r-note-2"),
            index=2,
            moved=1,
            skipped=1,
            errors=0,
            saved_at=_RESUME_SAVED_AT,
        )
    )
    app, _mock_inner, _spy = _make_app_with_spy(tui_config, _resume_notes(3))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(SortScreen(store=store, now_provider=lambda: _RESUME_SAVED_AT))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("y")  # Resume at index 2
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        preview_text = str(sort_screen.query_one("#note-preview", Static).render())
        assert preview_text == "n2", (
            f"resumed note preview must be the real body, got {preview_text!r}"
        )
        assert _PREVIEW_SKELETON not in preview_text, "resumed note must not show the skeleton"
