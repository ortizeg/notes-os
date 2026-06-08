"""Tests for TaskWriter — Markdown checkbox file writer.

Verifies:
- write(tasks) with a non-empty list creates YYYY-MM-DD.md under target_dir.
- File content contains exactly one ``- [ ] {task.text}`` line per task.
- A second write call APPENDS (does not truncate); original lines preserved.
- write([]) is a no-op — returns None, creates no file.
- Filename format is YYYY-MM-DD.md derived from the injected clock.
- Parent directory is created if absent (mkdir parents=True).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from notes_os.sorter.extractor import ExtractedTask, TaskWriter


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_DATE = date(2026, 6, 7)
_FIXED_CLOCK = lambda: _FIXED_DATE  # noqa: E731 — simple lambda, test-only


def _make_tasks(*texts: str) -> list[ExtractedTask]:
    """Build a list of ExtractedTask from text strings.

    Args:
        texts: Task text strings.

    Returns:
        List of frozen ExtractedTask objects.
    """
    return [ExtractedTask(text=t) for t in texts]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTaskWriterWrite:
    """Core write-path tests for TaskWriter."""

    def test_creates_file_with_correct_name(self, tmp_path: Path) -> None:
        """write() creates YYYY-MM-DD.md named from the injected clock.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path, clock=_FIXED_CLOCK)
        result = writer.write(_make_tasks("Buy milk"))
        assert result is not None
        assert result.name == "2026-06-07.md"

    def test_file_contains_checkbox_lines(self, tmp_path: Path) -> None:
        """write() writes one ``- [ ] {text}`` line per task.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path, clock=_FIXED_CLOCK)
        writer.write(_make_tasks("Need to call Bob", "Schedule review"))

        content = (tmp_path / "2026-06-07.md").read_text(encoding="utf-8")
        lines = content.splitlines()
        assert lines == [
            "- [ ] Need to call Bob",
            "- [ ] Schedule review",
        ]

    def test_second_write_appends_not_truncates(self, tmp_path: Path) -> None:
        """A second write() call appends — original lines are preserved.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path, clock=_FIXED_CLOCK)
        writer.write(_make_tasks("Task one", "Task two"))
        writer.write(_make_tasks("Task three"))

        content = (tmp_path / "2026-06-07.md").read_text(encoding="utf-8")
        lines = content.splitlines()
        assert len(lines) == 3
        assert lines[0] == "- [ ] Task one"
        assert lines[1] == "- [ ] Task two"
        assert lines[2] == "- [ ] Task three"

    def test_empty_write_returns_none_and_no_file(self, tmp_path: Path) -> None:
        """write([]) is a no-op: returns None and creates no file.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path, clock=_FIXED_CLOCK)
        result = writer.write([])
        assert result is None
        assert not (tmp_path / "2026-06-07.md").exists()

    def test_returns_path_on_success(self, tmp_path: Path) -> None:
        """write() returns the Path of the written file.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path, clock=_FIXED_CLOCK)
        result = writer.write(_make_tasks("Follow up with team"))
        assert result == tmp_path / "2026-06-07.md"

    def test_creates_parent_dir_if_absent(self, tmp_path: Path) -> None:
        """write() creates the target directory (and parents) if absent.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        nested_dir = tmp_path / "deep" / "nested" / "tasks"
        assert not nested_dir.exists()
        writer = TaskWriter(target_dir=nested_dir, clock=_FIXED_CLOCK)
        writer.write(_make_tasks("I will schedule the meeting"))
        assert nested_dir.exists()
        assert (nested_dir / "2026-06-07.md").exists()

    def test_filename_format_is_iso_date(self, tmp_path: Path) -> None:
        """Filename is exactly YYYY-MM-DD.md from the clock's isoformat.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        clock = lambda: date(2025, 1, 3)  # noqa: E731
        writer = TaskWriter(target_dir=tmp_path, clock=clock)
        result = writer.write(_make_tasks("Remind Alice"))
        assert result is not None
        assert result.name == "2025-01-03.md"

    def test_default_clock_is_date_today(self, tmp_path: Path) -> None:
        """Without an injected clock, TaskWriter uses date.today().

        Verifies the file is named after today's date (dynamic check).

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path)
        result = writer.write(_make_tasks("TODO something"))
        assert result is not None
        today_name = date.today().isoformat() + ".md"
        assert result.name == today_name

    def test_single_task_list(self, tmp_path: Path) -> None:
        """A single-task list writes exactly one line.

        Args:
            tmp_path: pytest temporary directory fixture.
        """
        writer = TaskWriter(target_dir=tmp_path, clock=_FIXED_CLOCK)
        writer.write(_make_tasks("I will finish the report"))
        content = (tmp_path / "2026-06-07.md").read_text(encoding="utf-8")
        assert content == "- [ ] I will finish the report\n"
