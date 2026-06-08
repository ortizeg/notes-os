"""Tests for SortUIProtocol.prompt_task_selection + RichSortUI implementation.

Verifies:
- Key 'a' (add-all) returns all tasks unchanged.
- Key 'x' (skip) returns [] with no further reads.
- Key 's' (select) prompts for numbers; "1, 3" returns tasks 1 and 3.
- Key 's' with "9, x, 2" returns only task 2 (out-of-range/non-numeric ignored).
- An unknown key returns [].
- De-duplication: duplicate indices return each task only once.
"""

from __future__ import annotations

import io
from collections import deque

from notes_os.sorter.extractor import ExtractedTask
from notes_os.sorter.ui import RichSortUI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tasks(*texts: str) -> list[ExtractedTask]:
    """Build ExtractedTask list from text strings.

    Args:
        texts: Task text strings.

    Returns:
        List of frozen ExtractedTask objects.
    """
    return [ExtractedTask(text=t) for t in texts]


def _make_ui(keys: list[str], lines: list[str]) -> RichSortUI:
    """Build a RichSortUI with scripted key and line readers.

    Args:
        keys: Pre-programmed single-key responses (FIFO).
        lines: Pre-programmed line responses (FIFO).

    Returns:
        A RichSortUI with fake I/O, rendering to a StringIO console.
    """
    from rich.console import Console

    console = Console(file=io.StringIO(), highlight=False, markup=False)
    key_queue: deque[str] = deque(keys)
    line_queue: deque[str] = deque(lines)
    return RichSortUI(
        console=console,
        key_reader=lambda: key_queue.popleft(),
        line_reader=lambda: line_queue.popleft(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPromptTaskSelectionAddAll:
    """Tests for the 'a' (add-all) key path."""

    def test_key_a_returns_all_tasks(self) -> None:
        """Key 'a' returns all tasks unchanged."""
        tasks = _make_tasks("Need to call Bob", "Schedule review", "I will finish report")
        ui = _make_ui(keys=["a"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == tasks

    def test_key_a_uppercase_returns_all_tasks(self) -> None:
        """Key 'A' (uppercase) is normalised and returns all tasks."""
        tasks = _make_tasks("Need to call Bob", "Follow up with Alice")
        ui = _make_ui(keys=["A"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == tasks

    def test_key_a_single_task(self) -> None:
        """Key 'a' with a single-task list returns a one-element list.

        Verifies list(tasks) conversion works for length-1 input.
        """
        tasks = _make_tasks("TODO update docs")
        ui = _make_ui(keys=["a"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == tasks
        assert len(result) == 1


class TestPromptTaskSelectionSkip:
    """Tests for the 'x' (skip) key path."""

    def test_key_x_returns_empty(self) -> None:
        """Key 'x' returns [] without further reads."""
        tasks = _make_tasks("Need to call Bob", "Schedule review")
        ui = _make_ui(keys=["x"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == []

    def test_key_x_uppercase_returns_empty(self) -> None:
        """Key 'X' (uppercase) normalises to 'x' and returns []."""
        tasks = _make_tasks("Need to call Bob")
        ui = _make_ui(keys=["X"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == []


class TestPromptTaskSelectionUnknownKey:
    """Tests for any unknown key (treated as skip)."""

    def test_unknown_key_z_returns_empty(self) -> None:
        """An unrecognised key ('z') returns []."""
        tasks = _make_tasks("Need to call Bob", "Schedule review")
        ui = _make_ui(keys=["z"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == []

    def test_unknown_key_b_returns_empty(self) -> None:
        """Key 'b' (not bound here) returns []."""
        tasks = _make_tasks("Need to call Bob")
        ui = _make_ui(keys=["b"], lines=[])
        result = ui.prompt_task_selection(tasks)
        assert result == []


class TestPromptTaskSelectionSelect:
    """Tests for the 's' (select-subset) key path."""

    def test_key_s_comma_separated_selects_subset(self) -> None:
        """'s' with '1, 3' returns tasks at 1-based indices 1 and 3.

        Args: (none — uses local helpers)
        """
        tasks = _make_tasks("Task A", "Task B", "Task C")
        ui = _make_ui(keys=["s"], lines=["1, 3"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[0], tasks[2]]

    def test_key_s_space_separated_selects_subset(self) -> None:
        """'s' with '2 3' (space separated) returns tasks at indices 2 and 3."""
        tasks = _make_tasks("Task A", "Task B", "Task C")
        ui = _make_ui(keys=["s"], lines=["2 3"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[1], tasks[2]]

    def test_key_s_ignores_out_of_range_and_nonnumeric(self) -> None:
        """'9, x, 2' returns only task 2; 9 is out-of-range, 'x' is non-numeric."""
        tasks = _make_tasks("Task A", "Task B", "Task C")
        ui = _make_ui(keys=["s"], lines=["9, x, 2"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[1]]

    def test_key_s_all_invalid_returns_empty(self) -> None:
        """'s' with all invalid tokens returns empty list."""
        tasks = _make_tasks("Task A", "Task B")
        ui = _make_ui(keys=["s"], lines=["abc, 99, 0"])
        result = ui.prompt_task_selection(tasks)
        assert result == []

    def test_key_s_deduplicates_repeated_indices(self) -> None:
        """Duplicate indices yield each task only once."""
        tasks = _make_tasks("Task A", "Task B")
        ui = _make_ui(keys=["s"], lines=["1 1 2 1"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[0], tasks[1]]

    def test_key_s_uppercase_works(self) -> None:
        """'S' (uppercase) normalises to 's' and reads the number line."""
        tasks = _make_tasks("Task A", "Task B", "Task C")
        ui = _make_ui(keys=["S"], lines=["2"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[1]]

    def test_key_s_single_valid_index(self) -> None:
        """'s' with a single valid index returns that one task."""
        tasks = _make_tasks("Need to call Bob", "Schedule meeting")
        ui = _make_ui(keys=["s"], lines=["1"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[0]]

    def test_key_s_preserves_input_order(self) -> None:
        """'s' returns tasks in the order indices were entered, not natural order."""
        tasks = _make_tasks("Task A", "Task B", "Task C")
        ui = _make_ui(keys=["s"], lines=["3,1"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[2], tasks[0]]

    def test_key_s_mixed_comma_and_space(self) -> None:
        """Mixed delimiters ('1, 3 2') are handled correctly."""
        tasks = _make_tasks("Task A", "Task B", "Task C")
        ui = _make_ui(keys=["s"], lines=["1, 3 2"])
        result = ui.prompt_task_selection(tasks)
        assert result == [tasks[0], tasks[2], tasks[1]]


class TestPromptTaskSelectionProtocol:
    """Structural tests — RichSortUI satisfies SortUIProtocol."""

    def test_richsortui_satisfies_protocol(self) -> None:
        """RichSortUI is a structural subtype of SortUIProtocol at runtime."""
        from notes_os.sorter.ui import SortUIProtocol

        ui = _make_ui(keys=[], lines=[])
        assert isinstance(ui, SortUIProtocol), (
            "RichSortUI must be a runtime instance of SortUIProtocol"
        )
