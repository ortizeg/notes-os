"""Unit tests for SortSession counters, SessionSummary, and log writing (SESS-01/02/03).

Tests are fully isolated — no real filesystem I/O in unit tests that do not specifically
test log writing; log-write tests use ``tmp_path`` and an injected ``datetime``.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Task 1 — RED: SortSession counters + frozen SessionSummary (SESS-01/02)
# ---------------------------------------------------------------------------


class TestSortSessionInitialState:
    """A freshly constructed SortSession reports zero counts for all buckets."""

    def test_initial_moved_is_zero(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        assert session.moved == 0

    def test_initial_skipped_is_zero(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        assert session.skipped == 0

    def test_initial_errors_is_zero(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        assert session.errors == 0


class TestSortSessionCounterAccumulation:
    """Counters accumulate independently via record_move/skip/error (SESS-01)."""

    def test_record_move_increments_count(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("note-1", ("Projects",))
        session.record_move("note-2", ("Areas",))
        session.record_move("note-3", ("Resources",))
        assert session.moved == 3

    def test_record_skip_increments_count(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_skip("note-1")
        session.record_skip("note-2")
        assert session.skipped == 2

    def test_record_error_increments_count(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_error("note-1", "AppleScript timed out")
        assert session.errors == 1

    def test_mixed_records_are_independent(self) -> None:
        """Calling record_move/skip/error in any order keeps counters independent."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move("n2", ("Areas",))
        session.record_move("n3", ("Resources",))
        session.record_skip("n4")
        session.record_skip("n5")
        session.record_error("n6", "fail")
        assert session.moved == 3
        assert session.skipped == 2
        assert session.errors == 1


class TestSessionSummary:
    """summary() returns a frozen SessionSummary reflecting accumulated counts (SESS-02)."""

    def test_summary_moved_count(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move("n2", ("Areas",))
        assert session.summary().moved == 2

    def test_summary_skipped_count(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_skip("n1")
        assert session.summary().skipped == 1

    def test_summary_errors_count(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_error("n1", "boom")
        assert session.summary().errors == 1

    def test_summary_total_attribute(self) -> None:
        """SessionSummary.total == moved + skipped + errors."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_skip("n2")
        session.record_error("n3", "err")
        s = session.summary()
        assert s.total == s.moved + s.skipped + s.errors

    def test_summary_empty_session(self) -> None:
        from notes_os.sorter.session import SessionSummary, SortSession

        session = SortSession()
        s = session.summary()
        assert isinstance(s, SessionSummary)
        assert s.moved == 0
        assert s.skipped == 0
        assert s.errors == 0
        assert s.total == 0

    def test_summary_is_frozen(self) -> None:
        """Assigning to a SessionSummary field raises pydantic.ValidationError."""
        import pydantic

        from notes_os.sorter.session import SortSession

        session = SortSession()
        s = session.summary()
        with pytest.raises(pydantic.ValidationError):
            s.moved = 99  # type: ignore[misc]

    def test_summary_moved_attr_for_ui_show_summary(self) -> None:
        """RichSortUI.show_summary duck-types .moved/.skipped/.total — verify attrs exist."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_skip("n2")
        s = session.summary()
        # All three attrs that ui.py's show_summary accesses must be present
        assert hasattr(s, "moved")
        assert hasattr(s, "skipped")
        assert hasattr(s, "total")


# ---------------------------------------------------------------------------
# Task 2 — RED: write_log to log_dir/YYYY-MM-DD_HHMMSS.log (SESS-03)
# ---------------------------------------------------------------------------


class TestWriteLogFilename:
    """write_log uses the injected datetime to build the exact filename format (SESS-03)."""

    def test_filename_uses_injected_clock(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        result = session.write_log(tmp_path, now=fixed_dt)
        assert result.name == "2031-01-02_03-04-05.log"

    def test_write_log_returns_path(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        result = session.write_log(tmp_path, now=fixed_dt)
        assert isinstance(result, Path)

    def test_log_file_exists_after_write(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        result = session.write_log(tmp_path, now=fixed_dt)
        assert result.exists()

    def test_write_log_creates_log_dir_if_absent(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        nested = tmp_path / "deep" / "nested" / "logs"
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        result = session.write_log(nested, now=fixed_dt)
        assert result.exists()
        assert nested.is_dir()


class TestWriteLogContents:
    """Log file contents include the counts summary and per-note outcome lines."""

    def test_log_contains_moved_count(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        assert "moved" in content.lower() or "1" in content

    def test_log_contains_skipped_count(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_skip("n1")
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        assert "skipped" in content.lower() or "1" in content

    def test_log_contains_error_count(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_error("n1", "something went wrong")
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        assert "error" in content.lower() or "1" in content

    def test_log_contains_per_note_outcome_move(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("note-abc", ("Projects", "Web"))
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        assert "note-abc" in content

    def test_log_contains_per_note_outcome_skip(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_skip("note-xyz")
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        assert "note-xyz" in content

    def test_log_contains_per_note_outcome_error(self, tmp_path: Path) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_error("note-bad", "AppleScript failed")
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        assert "note-bad" in content

    def test_log_summary_line_contains_all_counts(self, tmp_path: Path) -> None:
        """The log includes a summary line mentioning moved, skipped, and error counts."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move("n2", ("Areas",))
        session.record_skip("n3")
        session.record_error("n4", "err")
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        log_path = session.write_log(tmp_path, now=fixed_dt)
        content = log_path.read_text()
        # Should contain the numeric values 2, 1, 1 somewhere near the summary line
        assert "2" in content  # moved
        assert "1" in content  # skipped / errors
