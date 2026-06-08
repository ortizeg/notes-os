"""SC3 Pilot tests for TaskExtractScreen — post-move task extraction TUI.

Proves SC3: when ``config.features.task_extraction`` is ``True`` and the moved
note's preview contains a signal phrase, ``TaskExtractScreen`` appears as a
modal after the move keystroke and the Add-all path writes the daily Markdown
checkbox file.  The off-by-default path (``task_extraction=False``) asserts
that no modal appears and no file is written.

Test coverage:
  SC3a (enabled write path): task_extraction=True, note preview contains "need
        to follow up" action phrase → route via 'x' → TaskExtractScreen appears
        → press 'a' (Add all) → daily .md file written with "- [ ] " line.
  SC3b (off-by-default path): task_extraction=False (default) → route same note
        → TaskExtractScreen NEVER appears → no file written under
        extracted_tasks_dir.
  SC3c (skip path): task_extraction=True → route → TaskExtractScreen appears →
        press 'x' (Skip) → no file written, flow advances normally.

Note on querying: ModalScreen lives on app.screen after push_screen().
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from notes_os.app import NotesOSApp
from notes_os.backup import BackingUpNotesRepository, BackupManager
from notes_os.backup_models import Backup
from notes_os.config import FeaturesConfig, SorterConfig
from notes_os.screens.sort import SortScreen
from notes_os.screens.task_extract import TaskExtractScreen
from notes_os.sorter.models import Note, ParaStructure


if TYPE_CHECKING:
    from pathlib import Path

    from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_FAKE_BACKUP_PATH = "/nonexistent/NoteStore_sc3-sentinel"
_FAKE_BACKUP = Backup(
    timestamp=datetime(2026, 1, 1, 12, 0, 0),
    path=_FAKE_BACKUP_PATH,  # type: ignore[arg-type]  # test sentinel
)

# Note preview that matches the extractor's action-phrase family:
# "need to" + "by Monday" both fire → at least one ExtractedTask.
_TASK_NOTE_PREVIEW = "I need to follow up with Sam by Monday."


def _make_spy_manager() -> MagicMock:
    """Return a MagicMock BackupManager spy that returns a stub Backup.

    Returns:
        MagicMock with spec=BackupManager; create() returns ``_FAKE_BACKUP``.
    """
    spy = MagicMock(spec=BackupManager)
    spy.create.return_value = _FAKE_BACKUP
    spy.list.return_value = [_FAKE_BACKUP]
    return spy


def _make_extraction_note(note_id: str = "sc3-note-1") -> Note:
    """Return a Note whose preview contains action signal phrases.

    The preview ``"I need to follow up with Sam by Monday."`` matches both the
    ``need to`` action-phrase family and the ``by Monday`` weekday-deadline
    family, guaranteeing at least one extracted task.

    Args:
        note_id: Opaque identifier for the note.

    Returns:
        A :class:`~notes_os.sorter.models.Note` with a task-rich preview.
    """
    return Note(
        id=note_id,
        title="Task-Rich Note",
        body=f"<p>{_TASK_NOTE_PREVIEW}</p>",
        preview=_TASK_NOTE_PREVIEW,
    )


def _make_archive_structure() -> ParaStructure:
    """Return a flat PARA structure where Archive is a leaf (no subfolders).

    Returns:
        :class:`~notes_os.sorter.models.ParaStructure` with all leaf roots.
    """
    return ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": (),
            "Areas": (),
            "Resources": (),
            "Archive": (),
        },
    )


def _make_app(
    config: SorterConfig,
    notes: list[Note],
) -> tuple[NotesOSApp, MockNotesRepository, MagicMock]:
    """Build a NotesOSApp with BackingUpNotesRepository + spy BackupManager.

    Args:
        config: SorterConfig (may have task_extraction True/False).
        notes: Seed notes for MockNotesRepository inbox.

    Returns:
        3-tuple of (app, mock_inner_repo, spy_manager).
    """
    from tests.sorter.conftest import MockNotesRepository

    structure = _make_archive_structure()
    mock_inner = MockNotesRepository(notes=notes, structure=structure)
    spy_manager = _make_spy_manager()
    wrapped_repo = BackingUpNotesRepository(mock_inner, spy_manager, config.backup)
    app = NotesOSApp(config=config, repo=wrapped_repo, backup_manager=spy_manager)
    return app, mock_inner, spy_manager


def _make_extraction_config(
    tmp_path: Path,
    *,
    task_extraction: bool,
) -> SorterConfig:
    """Build a SorterConfig with extraction flag set and all I/O under tmp_path.

    Args:
        tmp_path: pytest temporary directory (unique per test).
        task_extraction: Whether to enable task extraction.

    Returns:
        Frozen :class:`~notes_os.config.SorterConfig`.
    """
    from notes_os.backup_models import BackupConfig

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


# ---------------------------------------------------------------------------
# SC3a: enabled write path
# ---------------------------------------------------------------------------


async def test_sc3a_enabled_write_path(tmp_path: Path) -> None:
    """SC3a: enabled + matching note → TaskExtractScreen appears → add-all writes file.

    Steps:
    1. Build app with task_extraction=True; seed note has action-phrase preview.
    2. Push SortScreen, route note to Archive via 'x'.
    3. Assert TaskExtractScreen appeared (app.screen is TaskExtractScreen).
    4. Press 'a' (Add all) — TaskWriter writes the daily Markdown file.
    5. Assert the daily .md file exists under extracted_tasks_dir and contains
       at least one '- [ ] ' checkbox line.

    Args:
        tmp_path: pytest temporary directory (unique per test).
    """
    config = _make_extraction_config(tmp_path, task_extraction=True)
    note = _make_extraction_note("sc3a-1")
    app, mock_inner, _spy = _make_app(config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen(year_provider=lambda: 2026)
        await app.push_screen(screen)
        await pilot.pause()

        assert isinstance(app.screen, SortScreen), (
            f"Expected SortScreen on top before routing, got {type(app.screen).__name__}"
        )

        # Route to Archive — 'x' = single keystroke, no subfolder drill
        await pilot.press("x")
        # call_after_refresh defers the push_screen to the next Textual cycle
        # to avoid the 'x' keypress propagating to TaskExtractScreen.
        # We need two pause() calls: one for call_after_refresh to fire, one
        # for the modal to mount and become the active screen.
        await pilot.pause()
        await pilot.pause()

        # SC3a-1: TaskExtractScreen should be on top (modal pushed by _after_move)
        assert isinstance(app.screen, TaskExtractScreen), (
            f"Expected TaskExtractScreen after move with task_extraction=True, "
            f"got {type(app.screen).__name__}"
        )

        # SC3a-2: The note was moved (regardless of task selection)
        assert len(mock_inner.moves) == 1, (
            f"Expected 1 move recorded before extract screen, got {mock_inner.moves!r}"
        )

        # Press 'a' — Add all; TaskWriter writes the daily file inside the screen
        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

        # SC3a-3: After dismiss, SortScreen should be on top again
        # (either showing next note or session-complete view)
        assert not isinstance(app.screen, TaskExtractScreen), (
            "Expected TaskExtractScreen dismissed after 'a', but it is still on top"
        )

        # SC3a-4: Daily Markdown file must exist under extracted_tasks_dir
        tasks_dir = config.features.extracted_tasks_dir
        md_files = list(tasks_dir.glob("*.md"))
        assert len(md_files) == 1, f"Expected exactly 1 .md file in {tasks_dir}, found {md_files!r}"
        md_content = md_files[0].read_text(encoding="utf-8")
        assert "- [ ] " in md_content, (
            f"Expected '- [ ] ' checkbox line in {md_files[0]}, got:\n{md_content!r}"
        )
        # The extracted task text should contain part of the signal phrase
        assert "follow up" in md_content or "need to" in md_content, (
            f"Expected action-phrase text in task file, got:\n{md_content!r}"
        )


# ---------------------------------------------------------------------------
# SC3b: off-by-default path
# ---------------------------------------------------------------------------


async def test_sc3b_off_by_default(tmp_path: Path) -> None:
    """SC3b: task_extraction=False → no modal, no file written (M1 default).

    Steps:
    1. Build app with task_extraction=False (the M1 default).
    2. Push SortScreen, route same note to Archive via 'x'.
    3. Assert TaskExtractScreen NEVER appeared on the screen stack.
    4. Assert no .md files written under extracted_tasks_dir.

    Args:
        tmp_path: pytest temporary directory (unique per test).
    """
    config = _make_extraction_config(tmp_path, task_extraction=False)
    note = _make_extraction_note("sc3b-1")
    app, mock_inner, _spy = _make_app(config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen(year_provider=lambda: 2026)
        await app.push_screen(screen)
        await pilot.pause()

        # Route to Archive — extraction is disabled
        await pilot.press("x")
        await pilot.pause()

        # SC3b-1: TaskExtractScreen must NOT appear
        assert not isinstance(app.screen, TaskExtractScreen), (
            f"TaskExtractScreen appeared despite task_extraction=False (M1 default); "
            f"current screen: {type(app.screen).__name__}"
        )

        # SC3b-2: Move was recorded (the sort itself should still work)
        assert len(mock_inner.moves) == 1, (
            f"Expected 1 move recorded even on disabled extraction path, got {mock_inner.moves!r}"
        )

        # SC3b-3: No .md file written
        tasks_dir = config.features.extracted_tasks_dir
        if tasks_dir.exists():
            md_files = list(tasks_dir.glob("*.md"))
            assert len(md_files) == 0, (
                f"Expected no .md files when task_extraction=False, found {md_files!r}"
            )
        # If directory doesn't even exist, that's fine too — TaskWriter never ran


# ---------------------------------------------------------------------------
# SC3c: skip path (enabled, user presses X)
# ---------------------------------------------------------------------------


async def test_sc3c_skip_writes_nothing(tmp_path: Path) -> None:
    """SC3c: enabled + matching note → TaskExtractScreen appears → skip → no file.

    Steps:
    1. Build app with task_extraction=True.
    2. Push SortScreen, route note to Archive via 'x'.
    3. Assert TaskExtractScreen appeared.
    4. Press 'x' (Skip) — no file should be written.
    5. Assert no .md file under extracted_tasks_dir.

    Args:
        tmp_path: pytest temporary directory (unique per test).
    """
    config = _make_extraction_config(tmp_path, task_extraction=True)
    note = _make_extraction_note("sc3c-1")
    app, _mock_inner, _spy = _make_app(config, [note])

    async with app.run_test() as pilot:
        await pilot.pause()

        screen = SortScreen(year_provider=lambda: 2026)
        await app.push_screen(screen)
        await pilot.pause()

        # Route to Archive
        await pilot.press("x")
        # Two pauses: one for call_after_refresh, one for modal mount
        await pilot.pause()
        await pilot.pause()

        # TaskExtractScreen should appear
        assert isinstance(app.screen, TaskExtractScreen), (
            f"Expected TaskExtractScreen, got {type(app.screen).__name__}"
        )

        # Press 'x' — Skip; no tasks written
        await pilot.press("x")
        await pilot.pause()
        await pilot.pause()

        # SC3c-1: Modal dismissed
        assert not isinstance(app.screen, TaskExtractScreen), (
            "Expected TaskExtractScreen dismissed after 'x' (Skip)"
        )

        # SC3c-2: No .md file written
        tasks_dir = config.features.extracted_tasks_dir
        if tasks_dir.exists():
            md_files = list(tasks_dir.glob("*.md"))
            assert len(md_files) == 0, f"Expected no .md files on Skip, found {md_files!r}"
