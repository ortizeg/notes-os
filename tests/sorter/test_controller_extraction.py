"""Controller extraction integration tests (SC1 + enabled path).

Proves:
- SC1 (DISABLED, default): task_extraction=False → extractor/UI/writer call
  counts all == 0 while the move still lands (session.moved == 1).
- ENABLED-MOVE: after a successful move, extractor runs, SpyUI presents
  tasks, writer receives selected tasks.
- ENABLED-SKIP: skip path → no extraction (extractor/UI/writer call count 0).
- ENABLED-NO-TASKS: extractor returns [] → no prompt, no write.

All tests use SpyUI (FakeUI-style with prompt_task_selection recording),
spy extractor, spy writer, MockNotesRepository, and conftest fixtures.
"""

from __future__ import annotations

from collections import deque
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from notes_os.config import FeaturesConfig, SorterConfig
from notes_os.sorter.controller import SortController
from notes_os.sorter.extractor import ExtractedTask, TaskWriter
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.router import Router
from notes_os.sorter.session import SortSession
from tests.sorter.conftest import MockNotesRepository


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


# ---------------------------------------------------------------------------
# SpyUI — FakeUI extended with prompt_task_selection recording
# ---------------------------------------------------------------------------


class SpyUI:
    """Scripted SortUIProtocol implementation that also spies on extraction calls.

    Feeds pre-programmed category keystrokes and records all method calls
    including ``prompt_task_selection`` invocations.

    Args:
        category_keys: Sequence of single-key strings for ``prompt_category``.
        choices: Sequence of ``int | None`` for ``prompt_choice``.
        task_selection_return: Value to return from ``prompt_task_selection``.
            Defaults to ``[]`` (user skips / no selection).
    """

    def __init__(
        self,
        category_keys: list[str],
        choices: list[int | None],
        task_selection_return: list[ExtractedTask] | None = None,
    ) -> None:
        """Initialise SpyUI with scripted inputs.

        Args:
            category_keys: Category keystroke queue (FIFO).
            choices: Numeric choice queue (FIFO).
            task_selection_return: Canned return value for prompt_task_selection.
        """
        self._category_keys: deque[str] = deque(category_keys)
        self._choices: deque[int | None] = deque(choices)
        self._task_selection_return: list[ExtractedTask] = (
            task_selection_return if task_selection_return is not None else []
        )

        # Call-recording attributes
        self.inbox_count_arg: int | None = None
        self.rendered_titles: list[str] = []
        self.show_help_count: int = 0
        self.show_summary_arg: Any = None
        self.prompt_task_selection_call_count: int = 0
        self.prompt_task_selection_last_tasks: list[ExtractedTask] = []

    # ------------------------------------------------------------------
    # SortUIProtocol methods
    # ------------------------------------------------------------------

    def show_inbox_count(self, count: int) -> None:
        """Record inbox count.

        Args:
            count: Number of notes in inbox.
        """
        self.inbox_count_arg = count

    def render_note(self, note: Any) -> None:
        """Record rendered note title.

        Args:
            note: Note object with ``.title``.
        """
        self.rendered_titles.append(note.title)

    def prompt_category(self) -> str:
        """Return next scripted keystroke.

        Returns:
            Next pre-programmed key string.
        """
        return self._category_keys.popleft()

    def prompt_choice(self, options: Any) -> int | None:
        """Return next scripted choice.

        Args:
            options: Option list (not inspected by spy).

        Returns:
            Next scripted choice or ``None``.
        """
        return self._choices.popleft()

    def show_help(self) -> None:
        """Record help call."""
        self.show_help_count += 1

    def show_summary(self, summary: Any) -> None:
        """Record summary argument.

        Args:
            summary: Session summary object.
        """
        self.show_summary_arg = summary

    def prompt_task_selection(self, tasks: Sequence[ExtractedTask]) -> list[ExtractedTask]:
        """Record the call and return the scripted selection.

        Args:
            tasks: Extracted tasks presented for selection.

        Returns:
            Scripted task selection (set at construction time).
        """
        self.prompt_task_selection_call_count += 1
        self.prompt_task_selection_last_tasks = list(tasks)
        return self._task_selection_return


# ---------------------------------------------------------------------------
# Spy extractor + writer
# ---------------------------------------------------------------------------


class SpyExtractor:
    """Callable spy for the extractor function.

    Records every call and returns scripted tasks.

    Args:
        return_tasks: The list of tasks to return on each call.
    """

    def __init__(self, return_tasks: list[ExtractedTask]) -> None:
        """Initialise with scripted return value.

        Args:
            return_tasks: Tasks to return from each ``__call__`` invocation.
        """
        self.return_tasks = return_tasks
        self.call_count: int = 0
        self.call_args: list[str] = []

    def __call__(self, text: str) -> list[ExtractedTask]:
        """Record the call and return scripted tasks.

        Args:
            text: The note preview text passed to the extractor.

        Returns:
            The scripted task list.
        """
        self.call_count += 1
        self.call_args.append(text)
        return self.return_tasks


class SpyWriter:
    """Spy for TaskWriter.write — records calls without touching the filesystem.

    Args:
        (none — constructed as a stub)
    """

    def __init__(self) -> None:
        """Initialise spy counters."""
        self.call_count: int = 0
        self.written_tasks: list[list[ExtractedTask]] = []

    def write(self, tasks: Sequence[ExtractedTask]) -> None:
        """Record the call.

        Args:
            tasks: Tasks passed to write.
        """
        self.call_count += 1
        self.written_tasks.append(list(tasks))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_structure() -> ParaStructure:
    """A minimal PARA structure: four roots, no subfolders.

    Returns:
        A :class:`~notes_os.sorter.models.ParaStructure` with flat roots.
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


@pytest.fixture()
def one_note() -> list[Note]:
    """A single inbox note whose preview contains an action phrase.

    Returns:
        One-element list with a Note that has extraction-triggering preview.
    """
    return [
        Note(
            id="note1",
            title="Meeting Notes",
            body="",
            preview="I need to follow up with Alice by Friday",
        )
    ]


def _build_config(
    log_dir: Path,
    task_extraction: bool = False,
    extracted_tasks_dir: Path | None = None,
) -> SorterConfig:
    """Build a test SorterConfig with controlled feature flags.

    Args:
        log_dir: Directory for the session audit log.
        task_extraction: Value for FeaturesConfig.task_extraction.
        extracted_tasks_dir: Override for extracted_tasks_dir (default: log_dir).

    Returns:
        A frozen :class:`~notes_os.config.SorterConfig`.
    """
    tasks_dir = extracted_tasks_dir if extracted_tasks_dir is not None else log_dir
    features = FeaturesConfig(
        task_extraction=task_extraction,
        extracted_tasks_dir=tasks_dir,
    )
    return SorterConfig(log_dir=log_dir, features=features)


# ---------------------------------------------------------------------------
# SC1: DISABLED path (task_extraction=False — the default)
# ---------------------------------------------------------------------------


class TestExtractionDisabled:
    """SC1 proof: task_extraction=False → zero extraction calls, move still lands."""

    def test_disabled_move_no_extraction_calls(
        self,
        tmp_path: Path,
        one_note: list[Note],
        simple_structure: ParaStructure,
    ) -> None:
        """Disabled flag: extractor/UI/writer call counts == 0; session.moved == 1.

        Args:
            tmp_path: pytest temp dir.
            one_note: Single note with action-phrase preview.
            simple_structure: Flat PARA structure fixture.
        """
        config = _build_config(tmp_path, task_extraction=False)
        repo = MockNotesRepository(notes=one_note, structure=simple_structure)

        spy_extractor = SpyExtractor(return_tasks=[ExtractedTask(text="Need to call Bob")])
        spy_writer = SpyWriter()
        # Use 'x' (Archive) — a direct move requiring no subfolder selection
        spy_ui = SpyUI(
            category_keys=["x"],
            choices=[],
            task_selection_return=[],
        )

        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2026)
        controller = SortController(
            repo=repo,
            ui=spy_ui,
            session=session,
            router=router,
            config=config,
            extractor=spy_extractor,
            writer=spy_writer,
        )

        controller.run()

        # SC1: ALL extraction-related calls must be zero
        assert spy_extractor.call_count == 0, (
            "SC1 VIOLATED: extractor called despite task_extraction=False"
        )
        assert spy_ui.prompt_task_selection_call_count == 0, (
            "SC1 VIOLATED: prompt_task_selection called despite task_extraction=False"
        )
        assert spy_writer.call_count == 0, (
            "SC1 VIOLATED: writer.write called despite task_extraction=False"
        )

        # The move must still land
        assert session.summary().moved == 1, (
            "SC1: move must still succeed when extraction is disabled"
        )


# ---------------------------------------------------------------------------
# Enabled path: MOVE triggers extraction
# ---------------------------------------------------------------------------


class TestExtractionEnabled:
    """Enabled path: extractor → UI → writer called after a successful move."""

    def test_enabled_move_full_extraction_pipeline(
        self,
        tmp_path: Path,
        one_note: list[Note],
        simple_structure: ParaStructure,
    ) -> None:
        """Full extraction pipeline fires after a move when enabled.

        Extractor returns two tasks; SpyUI.prompt_task_selection returns
        one task; writer.write is called once with that one task.

        Args:
            tmp_path: pytest temp dir.
            one_note: Single note fixture.
            simple_structure: Flat PARA structure fixture.
        """
        tasks_dir = tmp_path / "tasks"
        config = _build_config(tmp_path, task_extraction=True, extracted_tasks_dir=tasks_dir)
        repo = MockNotesRepository(notes=one_note, structure=simple_structure)

        task_a = ExtractedTask(text="Need to call Alice")
        task_b = ExtractedTask(text="Follow up by Friday")
        spy_extractor = SpyExtractor(return_tasks=[task_a, task_b])

        # Use a real TaskWriter with a fixed clock and injected dir
        real_writer = TaskWriter(target_dir=tasks_dir, clock=lambda: date(2026, 6, 7))

        # SpyUI selects only task_b
        spy_ui = SpyUI(
            category_keys=["x"],
            choices=[],
            task_selection_return=[task_b],
        )

        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2026)
        controller = SortController(
            repo=repo,
            ui=spy_ui,
            session=session,
            router=router,
            config=config,
            extractor=spy_extractor,
            writer=real_writer,
        )

        controller.run()

        # Move landed
        assert session.summary().moved == 1

        # Extractor called once with the note's preview
        assert spy_extractor.call_count == 1
        assert spy_extractor.call_args[0] == one_note[0].preview

        # UI prompt called once
        assert spy_ui.prompt_task_selection_call_count == 1
        assert spy_ui.prompt_task_selection_last_tasks == [task_a, task_b]

        # Daily file written with only the selected task (task_b)
        daily_file = tasks_dir / "2026-06-07.md"
        assert daily_file.exists(), "Daily tasks file must be created after write"
        content = daily_file.read_text(encoding="utf-8")
        assert "- [ ] Follow up by Friday\n" in content
        assert "Need to call Alice" not in content

    def test_enabled_uses_note_preview_as_extraction_input(
        self,
        tmp_path: Path,
        simple_structure: ParaStructure,
    ) -> None:
        """Extractor receives note.preview (not body) as input text.

        Args:
            tmp_path: pytest temp dir.
            simple_structure: Flat PARA structure fixture.
        """
        note_with_preview = Note(
            id="n1",
            title="Preview Test",
            body="<html>raw body</html>",
            preview="I need to finish the report by Monday",
        )
        config = _build_config(tmp_path, task_extraction=True)
        repo = MockNotesRepository(notes=[note_with_preview], structure=simple_structure)

        spy_extractor = SpyExtractor(return_tasks=[])
        spy_ui = SpyUI(category_keys=["x"], choices=[], task_selection_return=[])
        spy_writer = SpyWriter()

        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2026)
        controller = SortController(
            repo=repo,
            ui=spy_ui,
            session=session,
            router=router,
            config=config,
            extractor=spy_extractor,
            writer=spy_writer,
        )

        controller.run()

        assert spy_extractor.call_count == 1
        assert spy_extractor.call_args[0] == "I need to finish the report by Monday"


# ---------------------------------------------------------------------------
# Enabled-but-SKIP: skip path → no extraction
# ---------------------------------------------------------------------------


class TestExtractionSkipPath:
    """Enabled but note is skipped: extractor/UI/writer call counts all 0."""

    def test_enabled_skip_no_extraction_calls(
        self,
        tmp_path: Path,
        one_note: list[Note],
        simple_structure: ParaStructure,
    ) -> None:
        """Skip path: enabled config, 's' keystroke → zero extraction calls.

        Args:
            tmp_path: pytest temp dir.
            one_note: Single note fixture.
            simple_structure: Flat PARA structure fixture.
        """
        config = _build_config(tmp_path, task_extraction=True)
        repo = MockNotesRepository(notes=one_note, structure=simple_structure)

        spy_extractor = SpyExtractor(return_tasks=[ExtractedTask(text="Need to call Bob")])
        spy_writer = SpyWriter()
        spy_ui = SpyUI(
            category_keys=["s"],  # 's' = skip
            choices=[],
            task_selection_return=[],
        )

        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2026)
        controller = SortController(
            repo=repo,
            ui=spy_ui,
            session=session,
            router=router,
            config=config,
            extractor=spy_extractor,
            writer=spy_writer,
        )

        controller.run()

        # All extraction-related calls must be zero
        assert spy_extractor.call_count == 0, "Extractor must not run on skip"
        assert spy_ui.prompt_task_selection_call_count == 0, (
            "prompt_task_selection must not be called on skip"
        )
        assert spy_writer.call_count == 0, "Writer must not run on skip"

        # Note was skipped
        assert session.summary().skipped == 1
        assert session.summary().moved == 0


# ---------------------------------------------------------------------------
# Enabled-but-no-tasks: extractor returns [] → no prompt, no write
# ---------------------------------------------------------------------------


class TestExtractionNoTasks:
    """Enabled, move happens, but extractor finds no tasks → UI and writer silent."""

    def test_enabled_no_tasks_skips_prompt_and_write(
        self,
        tmp_path: Path,
        one_note: list[Note],
        simple_structure: ParaStructure,
    ) -> None:
        """Extractor returns [] → prompt_task_selection and writer not called.

        Args:
            tmp_path: pytest temp dir.
            one_note: Single note fixture.
            simple_structure: Flat PARA structure fixture.
        """
        config = _build_config(tmp_path, task_extraction=True)
        repo = MockNotesRepository(notes=one_note, structure=simple_structure)

        # Extractor returns empty list
        spy_extractor = SpyExtractor(return_tasks=[])
        spy_writer = SpyWriter()
        spy_ui = SpyUI(category_keys=["x"], choices=[], task_selection_return=[])

        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2026)
        controller = SortController(
            repo=repo,
            ui=spy_ui,
            session=session,
            router=router,
            config=config,
            extractor=spy_extractor,
            writer=spy_writer,
        )

        controller.run()

        # Move succeeded
        assert session.summary().moved == 1

        # Extractor was called once (to check for tasks)
        assert spy_extractor.call_count == 1

        # But UI prompt and writer must NOT be called when no tasks found
        assert spy_ui.prompt_task_selection_call_count == 0, (
            "prompt_task_selection must not be called when extractor returns []"
        )
        assert spy_writer.call_count == 0, "writer.write must not be called when no tasks extracted"
