"""TaskExtractScreen — post-move task review TUI screen.

Shown by :class:`~notes_os.screens.sort.SortScreen` after a note is
successfully moved, when ``config.features.task_extraction`` is ``True``.

Receives a pre-computed list of :class:`~notes_os.sorter.extractor.ExtractedTask`
objects (extracted by ``extract_tasks`` in SortScreen — never re-extracted here)
and a :class:`~notes_os.sorter.extractor.TaskWriter` pointed at
``config.features.extracted_tasks_dir``.

Selection modes (mirrors :class:`~notes_os.sorter.ui.SortUIProtocol.prompt_task_selection`
semantics):
- **A** — Add all: pre-select every task, write all, dismiss.
- **S** — Select: enter per-item toggle mode (Space toggles, Enter confirms).
- **X** / **Esc** — Skip: dismiss without writing anything.
- **?** — Show key legend as a Textual notification (TUI-05).

After the user resolves the selection, any selected tasks are written via
``TaskWriter.write(selected)`` and the screen is dismissed — passing back the
list of tasks that were written so SortScreen / tests can assert.

Threat mitigations
------------------
- T-06-08 (extraction running when disabled): gate is in SortScreen._after_move;
  this screen is NEVER instantiated unless extraction is enabled.
- T-06-09 (writing outside configured dir): TaskWriter writes only under
  ``extracted_tasks_dir`` — enforced by Phase-5 TaskWriter contract.
- T-06-10 (blocking event loop): extract_tasks runs in SortScreen (not here);
  TaskWriter.write is I/O-bounded but fast (append to a small daily file) and
  runs synchronously inside the dismiss handler — acceptable for M1.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import SelectionList, Static
from textual.widgets.selection_list import Selection


if TYPE_CHECKING:
    from textual.app import ComposeResult

    from notes_os.sorter.extractor import ExtractedTask, TaskWriter


logger = logging.getLogger(__name__)

_HELP_TEXT = """\
Key legend - Task Extract Screen
  A        Add all extracted tasks
  S        Select a subset (Space toggles, Enter confirms)
  X / Esc  Skip — write nothing
  ? / ?    Show this help
  Q        Quit NotesOS
"""

_FOOTER_LEGEND = "[A] Add all   [S] Select subset   [X] Skip   [?] Help"


class TaskExtractScreen(ModalScreen[list["ExtractedTask"]]):
    """Modal screen for reviewing and selecting extracted tasks after a move.

    Presents the ``tasks`` list with a numbered SelectionList and a footer
    legend.  The three selection modes mirror the readchar-era
    ``SortUIProtocol.prompt_task_selection`` contract so behaviour is consistent
    between the CLI and TUI.

    Dismissed with the list of :class:`~notes_os.sorter.extractor.ExtractedTask`
    objects that should be written (may be empty on Skip).  The *caller*
    (SortScreen._on_tasks_resolved) receives the dismiss result via callback and
    writes with TaskWriter so that SortScreen controls the write lifecycle.

    Args:
        tasks: Pre-extracted task list from ``extract_tasks(note.preview)``.
            The screen never re-extracts.  Must be non-empty — SortScreen
            skips the push when ``not tasks``.
        writer: A ``TaskWriter`` instance built from
            ``config.features.extracted_tasks_dir``.  Passed for the
            Add-all / Select paths; not called on Skip.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "add_all", "Add all", show=True),
        Binding("s", "select_mode", "Select", show=True),
        Binding("x", "skip", "Skip", show=True),
        Binding("escape", "skip", "Skip", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(
        self,
        tasks: list[ExtractedTask],
        writer: TaskWriter,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 — mirrors Textual Screen signature
        classes: str | None = None,
    ) -> None:
        """Initialise the screen with a task list and a writer.

        Args:
            tasks: Non-empty list of :class:`~notes_os.sorter.extractor.ExtractedTask`
                objects already extracted from the moved note's preview.
            writer: :class:`~notes_os.sorter.extractor.TaskWriter` instance that
                appends to ``{extracted_tasks_dir}/YYYY-MM-DD.md``.
            name: Textual widget name (passed to super).
            id: Textual widget id (passed to super).
            classes: Textual CSS classes (passed to super).
        """
        super().__init__(name=name, id=id, classes=classes)
        self._tasks = tasks
        self._writer = writer
        self._select_mode_active: bool = False

    def compose(self) -> ComposeResult:
        """Lay out the task-extract modal widgets.

        Yields a header Static, a SelectionList of tasks, and a footer legend
        Static.  Modal screens do not include Header/Footer widgets — those are
        reserved for full-screen layouts.

        Yields:
            Static label, SelectionList, Static legend.
        """
        yield Static(
            f"Potential tasks found: ({len(self._tasks)})\n"
            "Press [A] to add all, [S] to select, [X] or Esc to skip.",
            id="task-header",
        )
        selections = [
            Selection(f"{i + 1}. {task.text}", i, initial_state=False)
            for i, task in enumerate(self._tasks)
        ]
        yield SelectionList[int](*selections, id="task-list")
        yield Static(_FOOTER_LEGEND, id="task-legend")

    def on_mount(self) -> None:
        """Focus the task list on mount so keyboard navigation works immediately."""
        self.query_one("#task-list", SelectionList).focus()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_add_all(self) -> None:
        """Add all extracted tasks — select everything and write immediately.

        Selects all tasks, calls ``TaskWriter.write(all_tasks)``, and dismisses
        the screen passing ``self._tasks`` as the result.
        """
        logger.debug("TaskExtractScreen: add-all — %d task(s)", len(self._tasks))
        self._write_and_dismiss(self._tasks)

    def action_select_mode(self) -> None:
        """Enter per-item toggle mode.

        Activates ``_select_mode_active`` so the ``Enter`` key confirms the
        current SelectionList selection.  Updates the legend to reflect the
        new mode (Space toggles, Enter confirms).
        """
        self._select_mode_active = True
        self.query_one("#task-legend", Static).update(
            "[Space] Toggle   [Enter] Confirm   [X/Esc] Cancel"
        )
        logger.debug("TaskExtractScreen: entering select mode")

    def action_skip(self) -> None:
        """Skip — dismiss without writing any tasks.

        Passes an empty list as the dismiss result so the SortScreen callback
        knows nothing was written (and skips calling TaskWriter.write).
        """
        logger.debug("TaskExtractScreen: skip — no tasks written")
        self.dismiss([])

    def action_help(self) -> None:
        """Show the task-extract key legend as a Textual notification (TUI-05)."""
        self.notify(_HELP_TEXT, title="Task Extract Help", timeout=8.0)

    def on_key(self, event: object) -> None:
        """Handle Enter key in select mode to confirm the current selection.

        In normal mode all navigation is handled via BINDINGS.  In select mode
        (after pressing S), Enter confirms whichever items are currently toggled
        in the SelectionList.

        Args:
            event: The Textual key event (typed as ``object`` to satisfy mypy
                when the actual ``events.Key`` type is imported only under
                TYPE_CHECKING).
        """
        from textual import events  # local import — avoid circular at module level

        if not isinstance(event, events.Key):
            return
        if not self._select_mode_active:
            return
        if event.key == "enter":
            task_list = self.query_one("#task-list", SelectionList)
            selected_indices: list[int] = list(task_list.selected)
            selected = [self._tasks[i] for i in sorted(selected_indices)]
            logger.debug("TaskExtractScreen: confirmed %d task(s)", len(selected))
            self._write_and_dismiss(selected)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_and_dismiss(self, selected: list[ExtractedTask]) -> None:
        """Write ``selected`` via TaskWriter (if non-empty) then dismiss.

        Args:
            selected: Tasks to persist.  Empty list is a no-op for the writer
                (``TaskWriter.write([])`` returns ``None`` without filesystem access).
        """
        if selected:
            written_path = self._writer.write(selected)
            logger.info(
                "TaskExtractScreen: wrote %d task(s) to %s",
                len(selected),
                written_path,
            )
        self.dismiss(selected)
