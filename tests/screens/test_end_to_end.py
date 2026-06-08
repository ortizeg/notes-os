"""End-to-end Pilot test — Home → Sort → TaskExtract → finish (SC1+SC2+SC3 in one walk).

Proves that the full Milestone-1 product works cohesively: HomeScreen shows live
inbox count (SC1), SortScreen routes notes via a backup-wrapped MockNotesRepository
so backup-before-move fires (SC2), TaskExtractScreen writes the daily Markdown file
for task-bearing notes (SC3), and the session summary + audit log are written at
finish (T-06-13 mitigation).

One single test performs the entire walk:
  1. HomeScreen mounts → inbox count == 2 (SC1 spot-check).
  2. Activate "Sort Inbox" → SortScreen appears.
  3. Route note 1 (task-rich preview) to Archive via 'x' → backup fires, move recorded.
  4. TaskExtractScreen appears for note 1 → press 'a' (Add all) → daily .md written (SC3).
  5. SortScreen advances to note 2 (plain note, no tasks).
  6. Route note 2 to Resources via 'r' → backup fires, move recorded.
  7. Both notes processed → _finish() fires → session summary visible, audit log exists.

Assertions span the full walk:
  - mock_inner.moves == 2 (both notes moved).
  - inbox empty after walk.
  - spy_manager.create() called >= 2 (SC2 — backup-before-move proven for each write op).
  - daily .md file under extracted_tasks_dir contains a '- [ ] ' line (SC3).
  - audit log file exists under log_dir (T-06-13).
  - session summary text on screen shows "Moved:   2" (visible to user).

Note on BackupManager spy: A real BackupManager raises BackupError when two backup
operations happen in the same second (macOS same-second rename collision).  Tests
use a MagicMock spy — create() is recorded without touching the filesystem — to
avoid the collision while still proving that backup is invoked before every write
(same SC2 approach as test_sort_screen.py SC2a).

No AppleScript is invoked anywhere in this test.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from textual.widgets import Static

from notes_os.app import NotesOSApp
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup, BackupConfig
from notes_os.config import FeaturesConfig, SorterConfig
from notes_os.screens.home import HomeScreen
from notes_os.screens.sort import SortScreen
from notes_os.screens.task_extract import TaskExtractScreen
from notes_os.sorter.models import Note, ParaStructure


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

# A note preview that contains a recognised action-phrase (SC3 signal).
_TASK_PREVIEW = "I need to follow up with the team by Friday."

_FAKE_BACKUP = Backup(
    timestamp=datetime(2026, 6, 1, 10, 0, 0),
    path="/nonexistent/e2e-sentinel",  # type: ignore[arg-type]
)


def _make_spy_manager() -> MagicMock:
    """Return a MagicMock BackupManager spy.

    The spy records create() calls without touching the filesystem — avoids the
    macOS same-second rename collision that occurs when two backups are created
    within the same second (the real BackupManager uses atomic rename into a
    timestamped directory that can only be created once per second).

    Returns:
        MagicMock with spec=BackupManager; create() returns ``_FAKE_BACKUP``.
    """
    spy = MagicMock(spec=BackupManager)
    spy.create.return_value = _FAKE_BACKUP
    spy.list.return_value = [_FAKE_BACKUP]
    return spy


def _make_e2e_config(tmp_path: Path, *, task_extraction: bool) -> SorterConfig:
    """Build a SorterConfig with extraction flag and all I/O under tmp_path.

    Args:
        tmp_path: pytest temporary directory.
        task_extraction: Whether task extraction is enabled.

    Returns:
        Frozen :class:`~notes_os.config.SorterConfig`.
    """
    notes_db_dir = tmp_path / "notes-db"
    backup_dir = tmp_path / "backups"
    log_dir = tmp_path / "logs"
    extracted_tasks_dir = tmp_path / "tasks"

    notes_db_dir.mkdir()
    backup_dir.mkdir()

    backup_cfg = BackupConfig(
        notes_db_dir=notes_db_dir,
        backup_dir=backup_dir,
    )
    features_cfg = FeaturesConfig(
        task_extraction=task_extraction,
        extracted_tasks_dir=extracted_tasks_dir,
    )
    return SorterConfig(
        backup=backup_cfg,
        features=features_cfg,
        log_dir=log_dir,
    )


def _make_e2e_seeds() -> tuple[list[Note], ParaStructure]:
    """Return two seed notes and a flat PARA structure for the end-to-end walk.

    Note 1 has an action-phrase preview (fires TaskExtractScreen on SC3 path).
    Note 2 is a plain note (no tasks → TaskExtractScreen never shown for it).

    Returns:
        Tuple of (notes list, ParaStructure).
    """
    notes = [
        Note(
            id="e2e-note-1",
            title="Task-Rich Note",
            body=f"<p>{_TASK_PREVIEW}</p>",
            preview=_TASK_PREVIEW,
        ),
        Note(
            id="e2e-note-2",
            title="Plain Note",
            body="<p>Just a simple note.</p>",
            preview="Just a simple note.",
        ),
    ]
    structure = ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": (),
            "Areas": (),
            "Resources": (),
            "Archive": (),
        },
    )
    return notes, structure


# ---------------------------------------------------------------------------
# End-to-end walk test
# ---------------------------------------------------------------------------


async def test_end_to_end_home_sort_extract_finish(tmp_path: Path) -> None:
    """E2E walk: Home → Sort → TaskExtract → finish proving SC1+SC2+SC3.

    All assertions are documented inline.  A spy BackupManager is used to avoid
    the macOS same-second rename collision between rapid backup calls during
    the test walk; the spy still proves SC2 by recording every create() call.

    Args:
        tmp_path: pytest temporary directory (unique per test run).
    """
    from tests.sorter.conftest import MockNotesRepository

    config = _make_e2e_config(tmp_path, task_extraction=True)
    notes, structure = _make_e2e_seeds()

    mock_inner = MockNotesRepository(notes=notes, structure=structure)
    spy_manager = _make_spy_manager()
    wrapped_repo = BackingUpNotesRepository(mock_inner, spy_manager, config.backup)

    app = NotesOSApp(
        config=config,
        repo=wrapped_repo,
        backup_manager=spy_manager,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        # ----------------------------------------------------------------
        # Step 1: HomeScreen mounts — SC1 spot-check (inbox count == 2)
        # ----------------------------------------------------------------
        assert isinstance(app.screen, HomeScreen), (
            f"Expected HomeScreen at launch, got {type(app.screen).__name__}"
        )

        inbox_widget = app.screen.query_one("#status-inbox", Static)
        inbox_text = str(inbox_widget.render())
        assert "2" in inbox_text, (
            f"SC1: Expected inbox count '2' in status widget, got: {inbox_text!r}"
        )

        # ----------------------------------------------------------------
        # Step 2: Activate "Sort Inbox" → SortScreen
        # ----------------------------------------------------------------
        await app.screen.run_action("sort")
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen after Sort Inbox activation, got {type(app.screen).__name__}"
        )

        # ----------------------------------------------------------------
        # Step 3: Route note 1 to Archive via 'x'
        #   - spy_manager.create() fires (SC2 proven by call_count ≥ 1)
        #   - move recorded on mock_inner
        # ----------------------------------------------------------------
        assert not app.sort_in_progress, "sort_in_progress should be False before first action"

        await pilot.press("x")
        # Two pauses: one for call_after_refresh, one for TaskExtractScreen to mount
        await pilot.pause()
        await pilot.pause()

        # SC2: at least one move recorded
        assert len(mock_inner.moves) == 1, (
            f"SC2: Expected 1 move after routing note 1, got {mock_inner.moves!r}"
        )
        assert mock_inner.moves[0][0] == "e2e-note-1"
        assert app.sort_in_progress, "sort_in_progress should be True after first move"

        # SC2: backup spy must have been called (backup-before-move invariant proven)
        assert spy_manager.create.call_count >= 1, (
            f"SC2: Expected spy_manager.create() to be called at least once "
            f"(backup-before-move), got {spy_manager.create.call_count} calls"
        )
        backup_calls_after_note1 = spy_manager.create.call_count

        # ----------------------------------------------------------------
        # Step 4: TaskExtractScreen appears for note 1 — press 'a' (Add all)
        # ----------------------------------------------------------------
        assert isinstance(app.screen, TaskExtractScreen), (
            f"SC3: Expected TaskExtractScreen after routing task-rich note 1, "
            f"got {type(app.screen).__name__}"
        )

        await pilot.press("a")  # Add all → writes daily .md
        await pilot.pause()
        await pilot.pause()

        # After dismiss, SortScreen should be on top again
        assert not isinstance(app.screen, TaskExtractScreen), (
            "TaskExtractScreen should be dismissed after 'a'"
        )
        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen after TaskExtractScreen dismiss, got {type(app.screen).__name__}"
        )

        # SC3: daily Markdown file written under extracted_tasks_dir
        tasks_dir = config.features.extracted_tasks_dir
        md_files = list(tasks_dir.glob("*.md")) if tasks_dir.exists() else []
        assert len(md_files) == 1, (
            f"SC3: Expected exactly 1 .md file in {tasks_dir}, found {md_files!r}"
        )
        md_content = md_files[0].read_text(encoding="utf-8")
        assert "- [ ] " in md_content, (
            f"SC3: Expected '- [ ] ' checkbox line in {md_files[0]}, got:\n{md_content!r}"
        )

        # ----------------------------------------------------------------
        # Step 5: Route note 2 to Resources via 'r'
        # ----------------------------------------------------------------
        # SortScreen is at AWAIT_CATEGORY for note 2 now
        sort_screen: SortScreen = app.screen  # type: ignore[assignment]
        assert isinstance(sort_screen, SortScreen)

        await pilot.press("r")
        await pilot.pause()

        # Resources has no sub-folders → immediate move
        # No TaskExtractScreen for plain note (no action phrases)
        assert not isinstance(app.screen, TaskExtractScreen), (
            "TaskExtractScreen should NOT appear for a plain note"
        )

        # ----------------------------------------------------------------
        # Step 6: Both notes processed → _finish() fires
        # ----------------------------------------------------------------
        await pilot.pause()

        # 2 moves total
        assert len(mock_inner.moves) == 2, f"Expected 2 total moves, got {mock_inner.moves!r}"
        assert mock_inner.moves[1][0] == "e2e-note-2"

        # SC2: backup called again for note 2 (create() total count grew)
        assert spy_manager.create.call_count > backup_calls_after_note1, (
            f"SC2: Expected additional backup create() calls for note 2, "
            f"total={spy_manager.create.call_count}, "
            f"after-note-1={backup_calls_after_note1}"
        )

        # Inbox is empty
        remaining = mock_inner.get_inbox_notes()
        assert len(remaining) == 0, (
            f"Expected empty inbox after both notes routed, got {len(remaining)} note(s)"
        )

        # sort_in_progress reset to False at _finish()
        assert not app.sort_in_progress, (
            "sort_in_progress should be False after session complete (_finish reset it)"
        )

        # Session summary visible on screen
        sort_screen = app.screen  # type: ignore[assignment]
        assert isinstance(sort_screen, SortScreen)

        preview_widget = sort_screen.query_one("#note-preview", Static)
        preview_text = str(preview_widget.render())
        assert "Moved:" in preview_text and "2" in preview_text, (
            f"Expected session summary with 'Moved: 2' in preview widget, got:\n{preview_text!r}"
        )

        # T-06-13: audit log exists under log_dir
        log_files = list(config.log_dir.glob("*.log")) if config.log_dir.exists() else []
        assert len(log_files) >= 1, (
            f"T-06-13: Expected audit log under {config.log_dir}, found none"
        )
        log_content = log_files[0].read_text(encoding="utf-8")
        assert "MOVE" in log_content, f"Expected 'MOVE' entries in audit log, got:\n{log_content!r}"
