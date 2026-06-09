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


# ---------------------------------------------------------------------------
# Phase 13-01 — record_move_failure: convert an optimistic move into an error
# (PERF-05 enabler)
# ---------------------------------------------------------------------------


class TestRecordMoveFailure:
    """record_move_failure reconciles an optimistic move whose write failed."""

    def test_move_then_failure_converts_count(self) -> None:
        """move -> move_failure for the same id: moved 1->0, errors 0->1."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move_failure("n1", "osascript timeout")
        assert session.moved == 0
        assert session.errors == 1
        assert session.skipped == 0

    def test_summary_reflects_conversion(self) -> None:
        """summary() reads the reconciled counters."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move_failure("n1", "osascript timeout")
        s = session.summary()
        assert s.moved == 0
        assert s.errors == 1

    def test_event_rewritten_to_error_in_log(self, tmp_path: Path) -> None:
        """The MOVE event for n1 becomes an [ERROR] line carrying the message."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move_failure("n1", "osascript timeout")
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        content = session.write_log(tmp_path, now=fixed_dt).read_text()
        # n1 surfaces as an ERROR line with the message; no MOVE line for n1.
        assert "[ERROR]" in content
        assert "osascript timeout" in content
        assert "[MOVE ]  n1" not in content

    def test_no_prior_move_records_fresh_error(self) -> None:
        """No prior move for the id: errors increments, moved stays at 0."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move_failure("ghost", "boom")
        assert session.errors == 1
        assert session.moved == 0

    def test_count_never_goes_negative(self) -> None:
        """A move_failure with no matching move never drives moved below zero."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("a", ("Projects",))
        # 'b' was never moved — must not decrement the unrelated 'a' move.
        session.record_move_failure("b", "boom")
        assert session.moved == 1
        assert session.errors == 1

    def test_mixed_sequence_counts(self) -> None:
        """move(a), move(b), skip(c), fail(a) -> moved 1, skipped 1, errors 1."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("a", ("Projects",))
        session.record_move("b", ("Areas",))
        session.record_skip("c")
        session.record_move_failure("a", "fail")
        assert session.moved == 1
        assert session.skipped == 1
        assert session.errors == 1
        assert session.summary().total == 3

    def test_failure_targets_most_recent_move_for_id(self, tmp_path: Path) -> None:
        """When a note was moved twice, the most-recent MOVE is the one rewritten."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",))
        session.record_move("n1", ("Areas",))
        session.record_move_failure("n1", "second move failed")
        assert session.moved == 1
        assert session.errors == 1
        fixed_dt = datetime.datetime(2031, 1, 2, 3, 4, 5)
        content = session.write_log(tmp_path, now=fixed_dt).read_text()
        # The earlier move to Projects survives; the later one is the error.
        assert "Projects" in content
        assert "second move failed" in content


# ---------------------------------------------------------------------------
# Phase 14-01 — UndoEntry + SortSession undo stack (UX-02)
# ---------------------------------------------------------------------------


class TestUndoStackInitialState:
    """A fresh session has an empty undo stack — pop_undo returns None."""

    def test_pop_undo_on_empty_returns_none(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        assert session.pop_undo() is None

    def test_pop_undo_on_empty_leaves_counters_at_zero(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.pop_undo()
        assert session.moved == 0
        assert session.skipped == 0
        assert session.errors == 0


class TestUndoEntryModel:
    """UndoEntry is a frozen Pydantic V2 value object carrying the undo context."""

    def test_undo_entry_is_frozen(self) -> None:
        import pydantic

        from notes_os.sorter.session import UndoEntry

        entry = UndoEntry(note_id="n1", kind="move", index=0)
        with pytest.raises(pydantic.ValidationError):
            entry.note_id = "other"  # type: ignore[misc]


class TestUndoStackPushAndPop:
    """record_move/record_skip push undo entries; pop_undo reverses LIFO."""

    def test_record_move_pushes_undo_entry_with_full_context(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",), source_path=("Notes",), index=3)
        assert session.moved == 1
        entry = session.pop_undo()
        assert entry is not None
        assert entry.note_id == "n1"
        assert entry.kind == "move"
        assert entry.source_path == ("Notes",)
        assert entry.dest_path == ("Projects",)
        assert entry.index == 3
        assert session.moved == 0

    def test_record_skip_pushes_undo_entry(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_skip("n2", index=4)
        assert session.skipped == 1
        entry = session.pop_undo()
        assert entry is not None
        assert entry.kind == "skip"
        assert entry.source_path is None
        assert entry.dest_path is None
        assert entry.index == 4
        assert session.skipped == 0

    def test_pop_undo_is_lifo_and_unbounded(self) -> None:
        """record move, skip, move -> pop returns most-recent first, then None."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("a", ("Projects",), index=0)
        session.record_skip("b", index=1)
        session.record_move("c", ("Areas",), index=2)

        first = session.pop_undo()
        second = session.pop_undo()
        third = session.pop_undo()
        assert first is not None and first.note_id == "c"
        assert second is not None and second.note_id == "b"
        assert third is not None and third.note_id == "a"
        assert session.pop_undo() is None

    def test_pop_undo_guards_moved_at_zero(self) -> None:
        """A move entry whose counter was already reconciled never goes negative."""
        from notes_os.sorter.session import SortSession, UndoEntry

        session = SortSession()
        # Inject an entry directly with the counter at zero (defensive guard path).
        session._undo_stack.append(
            UndoEntry(note_id="x", kind="move", dest_path=("Projects",), index=0)
        )
        assert session.moved == 0
        session.pop_undo()
        assert session.moved == 0

    def test_pop_undo_guards_skipped_at_zero(self) -> None:
        from notes_os.sorter.session import SortSession, UndoEntry

        session = SortSession()
        session._undo_stack.append(UndoEntry(note_id="x", kind="skip", index=0))
        assert session.skipped == 0
        session.pop_undo()
        assert session.skipped == 0


class TestUndoStackErroredEventRule:
    """record_error pushes nothing; record_move_failure pops the reconciled move."""

    def test_record_error_pushes_no_undo_entry(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_error("e1", "boom")
        assert session.pop_undo() is None

    def test_move_failure_pops_reconciled_entry(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("n1", ("Projects",), source_path=("Notes",), index=0)
        session.record_move_failure("n1", "timeout")
        # The failed move is NOT undoable.
        assert session.pop_undo() is None
        assert session.moved == 0
        assert session.errors == 1

    def test_move_failure_pops_only_matching_move(self) -> None:
        """move(a), move(b), fail(a): pop returns b, then None."""
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move("a", ("Projects",), index=0)
        session.record_move("b", ("Areas",), index=1)
        session.record_move_failure("a", "fail")

        entry = session.pop_undo()
        assert entry is not None
        assert entry.note_id == "b"
        assert session.pop_undo() is None

    def test_move_failure_with_no_prior_move_leaves_stack_empty(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.record_move_failure("ghost", "boom")
        assert session.pop_undo() is None


# ---------------------------------------------------------------------------
# restore_counts — re-seed the running tally on resume (UX-03)
# ---------------------------------------------------------------------------


class TestRestoreCounts:
    """restore_counts seeds moved/skipped/errors without touching undo/events."""

    def test_restore_counts_seeds_counters(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.restore_counts(moved=5, skipped=3, errors=1)

        summary = session.summary()
        assert summary.moved == 5
        assert summary.skipped == 3
        assert summary.errors == 1
        assert summary.total == 9

    def test_restore_counts_leaves_undo_stack_untouched(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.restore_counts(moved=2, skipped=1, errors=0)

        # The undo stack is still empty — restore_counts only moved the integers.
        assert session.pop_undo() is None

        # A subsequent record_skip then pop_undo reverses cleanly.
        session.record_skip("n1", index=0)
        entry = session.pop_undo()
        assert entry is not None
        assert entry.note_id == "n1"
        # The restored skipped base (1) plus the recorded-then-undone skip nets to 1.
        assert session.skipped == 1

    def test_restore_counts_guards_negative_to_zero(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.restore_counts(moved=-1, skipped=-2, errors=-3)

        summary = session.summary()
        assert summary.moved == 0
        assert summary.skipped == 0
        assert summary.errors == 0

    def test_restore_then_record_continues_tally(self) -> None:
        from notes_os.sorter.session import SortSession

        session = SortSession()
        session.restore_counts(moved=10, skipped=0, errors=0)
        session.record_move("n1", ("Projects",))

        assert session.summary().moved == 11
