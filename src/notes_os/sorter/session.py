"""Sort session tracker for NotesOS triage sessions.

Provides :class:`SortSession` (a mutable accumulator for triage events) and the
frozen :class:`SessionSummary` (an immutable snapshot of counts produced at the
end of a session).  Together they satisfy SESS-01, SESS-02, and SESS-03.

Usage::

    from notes_os.sorter.session import SortSession

    session = SortSession()
    session.record_move("x-coredata://...", ("Projects", "Web"))
    session.record_skip("x-coredata://...")
    summary = session.summary()  # SESS-02 — frozen snapshot
    log_path = session.write_log(cfg.log_dir)  # SESS-03 — audit log
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field


if TYPE_CHECKING:
    from notes_os.sorter.models import FolderPath


logger = logging.getLogger(__name__)


class SessionSummary(BaseModel):
    """Immutable end-of-session snapshot of triage outcome counts.

    Frozen so callers cannot mutate a summary that has already been handed to
    the UI or written to a log.  All counts default to zero and must be
    non-negative.

    Attributes:
        moved: Number of notes successfully moved to a PARA destination.
        skipped: Number of notes explicitly left in the inbox by the user.
        errors: Number of notes that could not be processed due to an error.
        total: Derived accessor — ``moved + skipped + errors``.
    """

    model_config = ConfigDict(frozen=True)

    moved: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        """Return the total number of notes processed in the session.

        Returns:
            ``moved + skipped + errors``.
        """
        return self.moved + self.skipped + self.errors


# ---------------------------------------------------------------------------
# Internal event record (not exposed to callers; used for per-note log lines)
# ---------------------------------------------------------------------------

_OUTCOME_MOVE = "MOVE"
_OUTCOME_SKIP = "SKIP"
_OUTCOME_ERROR = "ERROR"


class _NoteEvent:
    """Lightweight value-object for a single triage event.

    Not a Pydantic model — it never leaves the session; it is consumed only by
    :meth:`SortSession.write_log`.

    Args:
        note_id: The opaque note identifier.
        outcome: One of ``"MOVE"``, ``"SKIP"``, or ``"ERROR"``.
        detail: Extra context (destination path for moves; error message for errors).
    """

    __slots__ = ("detail", "note_id", "outcome")

    def __init__(self, note_id: str, outcome: str, detail: str) -> None:
        """Initialise the event record.

        Args:
            note_id: The opaque note identifier.
            outcome: Outcome label (``"MOVE"``, ``"SKIP"``, or ``"ERROR"``).
            detail: Human-readable detail string for the log line.
        """
        self.note_id = note_id
        self.outcome = outcome
        self.detail = detail


# ---------------------------------------------------------------------------
# SortSession
# ---------------------------------------------------------------------------


class SortSession:
    """Mutable accumulator for triage events across one sort session.

    Call :meth:`record_move`, :meth:`record_skip`, and :meth:`record_error` as
    the user triages each note.  When the session ends, call :meth:`summary` to
    obtain a frozen :class:`SessionSummary` for the UI and :meth:`write_log` to
    persist an audit log.

    This is a plain class (NOT a Pydantic model) because it accumulates state
    during the session.  Only the final :class:`SessionSummary` snapshot is
    frozen.

    Attributes:
        moved: Running count of notes moved to a PARA destination.
        skipped: Running count of notes explicitly left in the inbox.
        errors: Running count of notes that failed during move.
    """

    def __init__(self) -> None:
        """Initialise a new session with all counters at zero."""
        self.moved: int = 0
        self.skipped: int = 0
        self.errors: int = 0
        self._events: list[_NoteEvent] = []

    # ------------------------------------------------------------------
    # Recording triage events (SESS-01)
    # ------------------------------------------------------------------

    def record_move(self, note_id: str, destination: FolderPath) -> None:
        """Record that a note was successfully moved to *destination*.

        Increments :attr:`moved` by one and stores a per-note event for the
        audit log.

        Args:
            note_id: The opaque note identifier (e.g. ``"x-coredata://..."``).
            destination: Ordered tuple of folder names describing where the note
                was moved (e.g. ``("Projects", "Web")``).
        """
        self.moved += 1
        dest_str = " > ".join(destination)
        self._events.append(_NoteEvent(note_id, _OUTCOME_MOVE, dest_str))
        logger.debug("Recorded move: %s -> %s", note_id, dest_str)

    def record_skip(self, note_id: str) -> None:
        """Record that a note was deliberately left in the inbox.

        Increments :attr:`skipped` by one.

        Args:
            note_id: The opaque note identifier.
        """
        self.skipped += 1
        self._events.append(_NoteEvent(note_id, _OUTCOME_SKIP, "skipped"))
        logger.debug("Recorded skip: %s", note_id)

    def record_error(self, note_id: str, message: str) -> None:
        """Record that processing a note raised an error.

        Increments :attr:`errors` by one and stores the error message for the
        audit log so operators can investigate failed moves.

        Args:
            note_id: The opaque note identifier.
            message: Human-readable error description.
        """
        self.errors += 1
        self._events.append(_NoteEvent(note_id, _OUTCOME_ERROR, message))
        logger.warning("Recorded error: %s — %s", note_id, message)

    def record_move_failure(self, note_id: str, message: str) -> None:
        """Reconcile an optimistically-counted move whose write later failed.

        The TUI (Phase 13-02) records a move OPTIMISTICALLY — it increments
        :attr:`moved` before the off-thread ``move_note`` write is known to
        succeed.  When that write later fails the note physically stays in the
        inbox, so the already-counted move must become an error (PERF-05).

        Behaviour:

        - If the most-recent ``MOVE`` event for *note_id* is found, it is
          rewritten in place to an ``ERROR`` event carrying *message*,
          :attr:`moved` is decremented (guarded so it never goes below zero),
          and :attr:`errors` is incremented.  Net effect: the note is counted
          exactly once, as an error.
        - If NO prior move event exists for *note_id* (defensive), a fresh
          ``ERROR`` event is appended and only :attr:`errors` is incremented —
          :attr:`moved` is left untouched so it can never go negative.

        Args:
            note_id: The opaque note identifier whose optimistic move failed.
            message: Human-readable failure description recorded on the event.
        """
        for event in reversed(self._events):
            if event.note_id == note_id and event.outcome == _OUTCOME_MOVE:
                event.outcome = _OUTCOME_ERROR
                event.detail = message
                if self.moved > 0:
                    self.moved -= 1
                self.errors += 1
                logger.warning("Reclassified optimistic move as error: %s — %s", note_id, message)
                return

        # Defensive: no prior optimistic move for this id — record a fresh error.
        self._events.append(_NoteEvent(note_id, _OUTCOME_ERROR, message))
        self.errors += 1
        logger.warning("Recorded move failure with no prior move: %s — %s", note_id, message)

    # ------------------------------------------------------------------
    # Summary + log (SESS-02 / SESS-03)
    # ------------------------------------------------------------------

    def summary(self) -> SessionSummary:
        """Return a frozen :class:`SessionSummary` snapshot of the current counts.

        The snapshot is immutable — subsequent calls to ``record_*`` do NOT
        retroactively update a summary that was already produced.  Call this
        method again after additional events to get a fresh snapshot.

        Returns:
            A frozen :class:`SessionSummary` with the counts at the time of
            the call (SESS-02).
        """
        return SessionSummary(
            moved=self.moved,
            skipped=self.skipped,
            errors=self.errors,
        )

    def write_log(
        self,
        log_dir: Path,
        now: datetime | None = None,
    ) -> Path:
        """Write an audit log of the session to *log_dir*.

        The log filename is formatted as ``YYYY-MM-DD_HH-MM-SS.log`` using
        *now* (the injected clock).  When *now* is ``None`` the current
        wall-clock time is used — pass an explicit ``datetime`` in tests for
        determinism.

        ``log_dir`` is created (including all parents) if it does not exist.
        The log is written exclusively via :func:`pathlib.Path.write_text`
        — no ``print()``, no ``os.path``.

        Args:
            log_dir: Directory in which to write the session log.  Typically
                ``SorterConfig.log_dir`` (``~/.notes-os/logs``).  Created if
                absent.
            now: Datetime used for the filename timestamp.  Defaults to
                ``datetime.now()`` at call time.  Pass a fixed value in tests
                to assert the exact filename without relying on the wall clock.

        Returns:
            The :class:`~pathlib.Path` of the written log file so the controller
            can log or display the location.
        """
        if now is None:
            now = datetime.now()

        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        log_path = Path(log_dir) / f"{timestamp}.log"

        Path(log_dir).mkdir(parents=True, exist_ok=True)

        lines: list[str] = [
            f"NotesOS sort session — {timestamp}",
            "=" * 50,
            "",
            "Summary",
            "-------",
            f"  Moved:   {self.moved}",
            f"  Skipped: {self.skipped}",
            f"  Errors:  {self.errors}",
            f"  Total:   {self.moved + self.skipped + self.errors}",
            "",
            "Per-note outcomes",
            "-----------------",
        ]
        for event in self._events:
            lines.append(f"  [{event.outcome:5s}]  {event.note_id}  —  {event.detail}")

        if not self._events:
            lines.append("  (no notes processed)")

        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Session log written to %s", log_path)
        return log_path
