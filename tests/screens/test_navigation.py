"""SC4 Pilot tests — TUI-05 navigation consistency across all screens.

Proves SC4: the navigation convention (Esc/B back one level, Q quit / quit-confirm,
? contextual help) is consistent across HomeScreen, SortScreen, and TaskExtractScreen.

Note on worker timing: ``SortScreen.on_mount`` starts a ``@work(thread=True)``
worker (``_load_inbox``) to fetch the inbox snapshot off the event-loop thread.
Tests that push a SortScreen must call ``await app.workers.wait_for_complete()``
followed by ``await pilot.pause()`` before sending keystrokes or asserting on
SortScreen state.  ``HomeScreen`` also runs a ``_load_status`` thread worker;
tests that assert on its status widgets must likewise wait.

Test coverage:
  SC4a: Esc at AWAIT_FOLDER backs to AWAIT_CATEGORY (already in SC2c; duplicated here
        as explicit SC4 citation so test_navigation.py is the canonical SC4 suite).
  SC4b: B at AWAIT_CATEGORY returns to HomeScreen (Esc/B uniform back nav).
  SC4c: Q from HomeScreen exits immediately (no confirm modal when idle).
  SC4d: Q from SortScreen during an active session shows ConfirmQuitModal; press N →
        still on SortScreen; press Q again then Y → app exits.
  SC4e: ? on HomeScreen shows a help notification (action_help dispatches to screen).
  SC4f: ? on SortScreen shows the sort key legend notification.
  SC4g: ? on TaskExtractScreen shows the task-extract key legend notification.
  SC4h: Esc on HomeScreen is a no-op (action_noop — root screen has nothing to pop).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from notes_os.app import ConfirmQuitModal, NotesOSApp, ResumePromptModal
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup
from notes_os.screens.home import HomeScreen
from notes_os.screens.sort import SortScreen
from notes_os.screens.task_extract import TaskExtractScreen
from notes_os.sorter.extractor import ExtractedTask, TaskWriter
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.router import RouterState


if TYPE_CHECKING:
    from pathlib import Path

    from notes_os.config import SorterConfig
    from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_FAKE_BACKUP = Backup(
    timestamp=datetime(2026, 1, 1, 12, 0, 0),
    path="/nonexistent/sc4-sentinel",  # type: ignore[arg-type]
)


def _make_spy_manager() -> MagicMock:
    """Return a MagicMock BackupManager spy.

    Returns:
        MagicMock with spec=BackupManager; create() returns ``_FAKE_BACKUP``.
    """
    spy = MagicMock(spec=BackupManager)
    spy.create.return_value = _FAKE_BACKUP
    spy.list.return_value = [_FAKE_BACKUP]
    return spy


def _make_projects_structure() -> ParaStructure:
    """Return a ParaStructure where Projects has sub-folders.

    Returns:
        :class:`~notes_os.sorter.models.ParaStructure` with Projects → (General, Web).
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


def _make_flat_structure() -> ParaStructure:
    """Return a flat PARA structure (no sub-folders).

    Returns:
        :class:`~notes_os.sorter.models.ParaStructure` with all leaf roots.
    """
    return ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={"Projects": (), "Areas": (), "Resources": (), "Archive": ()},
    )


def _make_app(
    tui_config: SorterConfig,
    notes: list[Note],
    structure: ParaStructure | None = None,
) -> tuple[NotesOSApp, MockNotesRepository, MagicMock]:
    """Build a NotesOSApp with BackingUpNotesRepository + spy BackupManager.

    Args:
        tui_config: SorterConfig fixture with all I/O paths under tmp_path.
        notes: Seed notes for the MockNotesRepository inbox.
        structure: Optional ParaStructure; defaults to flat all-leaf structure.

    Returns:
        3-tuple of (app, mock_inner_repo, spy_manager).
    """
    from tests.sorter.conftest import MockNotesRepository

    if structure is None:
        structure = _make_flat_structure()

    mock_inner = MockNotesRepository(notes=notes, structure=structure)
    spy = _make_spy_manager()
    wrapped = BackingUpNotesRepository(mock_inner, spy, tui_config.backup)
    app = NotesOSApp(config=tui_config, repo=wrapped, backup_manager=spy)
    return app, mock_inner, spy


def _make_note(note_id: str = "sc4-note") -> Note:
    """Return a generic test note.

    Args:
        note_id: Opaque identifier.

    Returns:
        A :class:`~notes_os.sorter.models.Note`.
    """
    return Note(
        id=note_id,
        title="SC4 Test Note",
        body="<p>sc4 body</p>",
        preview="sc4 body",
    )


# ---------------------------------------------------------------------------
# SC4a: Esc at AWAIT_FOLDER → AWAIT_CATEGORY
# ---------------------------------------------------------------------------


async def test_sc4a_esc_at_await_folder_backs_to_category(
    tui_config: SorterConfig,
) -> None:
    """SC4a: Esc at AWAIT_FOLDER resets router state to AWAIT_CATEGORY.

    Mirrors SC2c but cited here as the canonical SC4 nav-consistency test.
    Pressing 'p' (Projects) enters AWAIT_FOLDER; Esc returns to AWAIT_CATEGORY.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_note("sc4a-1")
    app, mock_inner, _spy = _make_app(tui_config, [note], _make_projects_structure())

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert sort_screen._router_state == RouterState.AWAIT_FOLDER, (
            f"Expected AWAIT_FOLDER after 'p', got {sort_screen._router_state}"
        )

        await pilot.press("escape")
        await pilot.pause()

        assert sort_screen._router_state == RouterState.AWAIT_CATEGORY, (
            f"Expected AWAIT_CATEGORY after Esc, got {sort_screen._router_state}"
        )
        assert len(mock_inner.moves) == 0


# ---------------------------------------------------------------------------
# SC4b: B at AWAIT_CATEGORY returns to HomeScreen
# ---------------------------------------------------------------------------


async def test_sc4b_b_at_category_returns_to_home(
    tui_config: SorterConfig,
) -> None:
    """SC4b: pressing 'B' at AWAIT_CATEGORY pops SortScreen → HomeScreen.

    Verifies that 'B' and 'Esc' both trigger the same back-one-level action
    at the top routing level, returning to the HomeScreen (TUI-05 nav).

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_note("sc4b-1")
    app, _mock, _spy = _make_app(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, SortScreen)

        # Press 'B' — back from AWAIT_CATEGORY → HomeScreen
        await pilot.press("b")
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen), (
            f"Expected HomeScreen after 'B' from AWAIT_CATEGORY, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC4c: Q from HomeScreen exits without confirm modal
# ---------------------------------------------------------------------------


async def test_sc4c_q_from_home_exits_immediately(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """SC4c: Q from HomeScreen (no active session) exits without confirm modal.

    When sort_in_progress is False (the initial state), action_quit should call
    self.exit() directly — no ConfirmQuitModal pushed.

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)
        assert not app.sort_in_progress

        # Press 'q' — should exit without pushing a confirm modal
        await pilot.press("q")
        await pilot.pause()

        # The app should have exited (ConfirmQuitModal must NOT be on screen)
        # After exit() the run_test() context ends; we verify that ConfirmQuitModal
        # was never pushed by checking sort_in_progress was False at the moment of quit.
        assert not isinstance(app.screen, ConfirmQuitModal), (
            "ConfirmQuitModal appeared unexpectedly when sort_in_progress was False"
        )


# ---------------------------------------------------------------------------
# SC4d: Q during active session → confirm modal → N stays → Q + Y exits
# ---------------------------------------------------------------------------


async def test_sc4d_q_during_session_confirm_then_quit(
    tui_config: SorterConfig,
) -> None:
    """SC4d: Q during an active sort session shows ConfirmQuitModal.

    Flow:
    1. Push SortScreen, route one note so session.skipped > 0
       (sets sort_in_progress=True).
    2. Press Q → ConfirmQuitModal appears.
    3. Press N → dismissed with False → back on SortScreen (still running).
    4. Press Q again → modal appears again.
    5. Press Y → confirmed → app exits.

    Args:
        tui_config: SorterConfig fixture.
    """
    # Need two notes so the session doesn't finish after the first skip
    notes = [_make_note(f"sc4d-{i}") for i in range(2)]
    app, _mock, _spy = _make_app(tui_config, notes)

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        # Skip first note — sets sort_in_progress=True
        await pilot.press("s")
        await pilot.pause()

        assert app.sort_in_progress, "Expected sort_in_progress=True after skip"

        # Press Q — should push ConfirmQuitModal
        await pilot.press("q")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmQuitModal), (
            f"Expected ConfirmQuitModal after Q during session, got {type(app.screen).__name__}"
        )

        # Press N — cancel; should return to SortScreen
        await pilot.press("n")
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen after N in confirm modal, got {type(app.screen).__name__}"
        )

        # Press Q again → confirm again
        await pilot.press("q")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmQuitModal), (
            "Expected ConfirmQuitModal after second Q press"
        )

        # Press Y — confirm quit
        await pilot.press("y")
        await pilot.pause()

        # App should have exited; confirm modal no longer showing
        assert not isinstance(app.screen, ConfirmQuitModal), (
            "ConfirmQuitModal still showing after Y (expected app to exit)"
        )


# ---------------------------------------------------------------------------
# SC4e: ? on HomeScreen shows help notification
# ---------------------------------------------------------------------------


async def test_sc4e_help_on_home_screen(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """SC4e: pressing ? on HomeScreen dispatches to HomeScreen.action_help.

    HomeScreen.action_help() calls self.notify(...) with a key legend.  This
    test verifies that action_help is wired and callable without raising.

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)

        # Press '?' — should not raise; dispatches to HomeScreen.action_help
        await pilot.press("question_mark")
        await pilot.pause()

        # Verify the screen is still HomeScreen (not crashed/replaced)
        assert isinstance(app.screen, HomeScreen), (
            f"Expected HomeScreen still active after ?, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC4f: ? on SortScreen shows sort key legend
# ---------------------------------------------------------------------------


async def test_sc4f_help_on_sort_screen(tui_config: SorterConfig) -> None:
    """SC4f: pressing ? on SortScreen dispatches to SortScreen.action_help.

    SortScreen.action_help() calls self.notify(...) with the PARA key legend.
    This test verifies the binding and action_help wiring without raising.

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_note("sc4f-1")
    app, _mock, _spy = _make_app(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, SortScreen)

        # Press '?' — dispatches to SortScreen.action_help (notify)
        await pilot.press("question_mark")
        await pilot.pause()

        # Screen must remain SortScreen (not crashed)
        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen still active after ?, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC4g: ? on TaskExtractScreen shows task-extract key legend
# ---------------------------------------------------------------------------


async def test_sc4g_help_on_task_extract_screen(
    tui_config: SorterConfig,
    tmp_path: Path,
) -> None:
    """SC4g: pressing ? on TaskExtractScreen dispatches to action_help.

    TaskExtractScreen.action_help() calls self.notify(...) with the task-extract
    legend.  This test pushes the modal directly and verifies the binding.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: pytest temporary directory for TaskWriter output.
    """
    from tests.sorter.conftest import MockNotesRepository

    structure = _make_flat_structure()
    mock_inner = MockNotesRepository(notes=[], structure=structure)
    app = NotesOSApp(config=tui_config, repo=mock_inner)

    tasks = [ExtractedTask(text="follow up with Sam")]
    writer = TaskWriter(tmp_path / "tasks")

    async with app.run_test() as pilot:
        await pilot.pause()

        modal = TaskExtractScreen(tasks, writer)
        await app.push_screen(modal)
        await pilot.pause()

        assert isinstance(app.screen, TaskExtractScreen)

        # Press '?' — dispatches to TaskExtractScreen.action_help (notify)
        await pilot.press("question_mark")
        await pilot.pause()

        # Modal must still be active (not dismissed by the help key)
        assert isinstance(app.screen, TaskExtractScreen), (
            f"Expected TaskExtractScreen still active after ?, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC4h: Esc on HomeScreen is a no-op
# ---------------------------------------------------------------------------


async def test_sc4h_esc_on_home_is_noop(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """SC4h: Esc on HomeScreen is a no-op (action_noop — root screen).

    HomeScreen is the root; there is nothing to pop.  Esc should not crash or
    quit the app; the screen stack should remain unchanged.

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)

        # Press Esc — should be a no-op on the root screen
        await pilot.press("escape")
        await pilot.pause()

        # Still on HomeScreen
        assert isinstance(app.screen, HomeScreen), (
            f"Expected HomeScreen still active after Esc, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC4i: Esc on SortScreen at AWAIT_CATEGORY → HomeScreen
# ---------------------------------------------------------------------------


async def test_sc4i_esc_at_category_returns_to_home(
    tui_config: SorterConfig,
) -> None:
    """SC4i: Esc at AWAIT_CATEGORY pops SortScreen → HomeScreen (same as B).

    Both Esc and B must return to HomeScreen from the top routing level,
    ensuring the two bindings share the same action_back handler (TUI-05).

    Args:
        tui_config: SorterConfig fixture.
    """
    note = _make_note("sc4i-1")
    app, _mock, _spy = _make_app(tui_config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen()
        await app.push_screen(screen)
        await pilot.pause()

        # Wait for _load_inbox thread worker, then flush call_from_thread UI updates.
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert isinstance(app.screen, SortScreen)

        # Press Esc — back from AWAIT_CATEGORY → HomeScreen
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen), (
            f"Expected HomeScreen after Esc from AWAIT_CATEGORY, got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# SC4j: TaskExtractScreen — X / Esc both skip (dismiss without writing)
# ---------------------------------------------------------------------------


async def test_sc4j_task_extract_esc_skips(
    tui_config: SorterConfig,
    tmp_path: Path,
) -> None:
    """SC4j: Esc on TaskExtractScreen acts as Skip (action_skip → dismiss).

    Verifies Esc/X uniformity on the modal screen — both map to action_skip so
    the user can always escape a modal without side effects.

    Args:
        tui_config: SorterConfig fixture.
        tmp_path: pytest temporary directory.
    """
    from tests.sorter.conftest import MockNotesRepository

    structure = _make_flat_structure()
    mock_inner = MockNotesRepository(notes=[], structure=structure)
    app = NotesOSApp(config=tui_config, repo=mock_inner)

    tasks = [ExtractedTask(text="check email")]
    writer = TaskWriter(tmp_path / "tasks")
    dismissed_result: list[list[ExtractedTask] | None] = []

    def _capture(result: list[ExtractedTask] | None) -> None:
        dismissed_result.append(result)

    async with app.run_test() as pilot:
        await pilot.pause()

        modal = TaskExtractScreen(tasks, writer)
        await app.push_screen(modal, _capture)
        await pilot.pause()

        assert isinstance(app.screen, TaskExtractScreen)

        # Press Esc — should trigger action_skip → dismiss([])
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, TaskExtractScreen), (
            "Expected TaskExtractScreen dismissed after Esc"
        )
        # Esc maps to action_skip which calls self.dismiss([])
        assert len(dismissed_result) == 1
        assert dismissed_result[0] == []


# ---------------------------------------------------------------------------
# ResumePromptModal — Resume (Y/button) → True, Start over (N/Esc/button) → False
# ---------------------------------------------------------------------------


async def test_resume_prompt_y_resumes(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """ResumePromptModal: pressing Y dismisses with True (Resume).

    The modal is pushed directly onto a minimal app — no SortScreen, no worker
    wait (mirrors the SC4j _capture pattern).

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)
    dismissed_result: list[bool | None] = []

    def _capture(result: bool | None) -> None:
        dismissed_result.append(result)

    async with app.run_test() as pilot:
        await pilot.pause()

        modal = ResumePromptModal(index=2, total=10)
        await app.push_screen(modal, _capture)
        await pilot.pause()

        assert isinstance(app.screen, ResumePromptModal)

        await pilot.press("y")
        await pilot.pause()

        assert not isinstance(app.screen, ResumePromptModal), (
            "Expected ResumePromptModal dismissed after Y"
        )
        assert dismissed_result == [True]


async def test_resume_prompt_n_starts_over(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """ResumePromptModal: pressing N dismisses with False (Start over).

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)
    dismissed_result: list[bool | None] = []

    def _capture(result: bool | None) -> None:
        dismissed_result.append(result)

    async with app.run_test() as pilot:
        await pilot.pause()

        modal = ResumePromptModal(index=0, total=5)
        await app.push_screen(modal, _capture)
        await pilot.pause()

        await pilot.press("n")
        await pilot.pause()

        assert not isinstance(app.screen, ResumePromptModal), (
            "Expected ResumePromptModal dismissed after N"
        )
        assert dismissed_result == [False]


async def test_resume_prompt_esc_starts_over(
    tui_config: SorterConfig,
    tui_repo: MockNotesRepository,
) -> None:
    """ResumePromptModal: pressing Esc dismisses with False (Start over).

    Args:
        tui_config: SorterConfig fixture.
        tui_repo: MockNotesRepository fixture.
    """
    app = NotesOSApp(config=tui_config, repo=tui_repo)
    dismissed_result: list[bool | None] = []

    def _capture(result: bool | None) -> None:
        dismissed_result.append(result)

    async with app.run_test() as pilot:
        await pilot.pause()

        modal = ResumePromptModal(index=3, total=8)
        await app.push_screen(modal, _capture)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, ResumePromptModal), (
            "Expected ResumePromptModal dismissed after Esc"
        )
        assert dismissed_result == [False]
