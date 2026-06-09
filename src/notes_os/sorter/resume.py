"""Session-resume persistence layer for NotesOS triage sessions (UX-03).

A small, UI-agnostic (Textual-free) contract for persisting and restoring the
position of an in-progress sort session so a relaunch can offer to resume:

- :class:`SessionState` — a frozen Pydantic V2 snapshot of the session position
  (inbox folder, the note-id signature used for staleness detection, the current
  index, and the running ``moved``/``skipped``/``errors`` counters) plus an
  INJECTED ``saved_at`` timestamp.
- :class:`ResumeStore` — saves the state ATOMICALLY (temp file + ``Path.replace``),
  loads it None-safely (a missing OR corrupt file degrades to ``None`` — never
  raises), and clears it idempotently.  The path is injectable; production uses
  :data:`_DEFAULT_STATE_PATH` (``~/.notes-os/session-state.json``).

Design decisions (settled here):

1. STALENESS = EXACT id-tuple equality.  :meth:`SessionState.matches` is True only
   when ``inbox_folder`` is unchanged AND ``note_ids`` is exactly equal (same ids,
   same order) to the current refs' ids.  Any reorder/add/remove/different-inbox is
   stale.  ``saved_at`` is NOT part of this check.
2. ``saved_at`` IS INJECTED, never defaulted.  A frozen model must not bake
   ``datetime.now()`` into a ``default_factory``: test determinism and round-trip
   equality both depend on an explicit value (mirrors the ``write_log`` injected
   clock).
3. ATOMIC WRITE.  :meth:`ResumeStore.save` writes the JSON to a temp file in the
   SAME directory then ``Path.replace``s it over the target — a crash mid-write
   leaves the old file or none, never a torn JSON (threat T-15-02).
4. LOAD NEVER RAISES.  :meth:`ResumeStore.load` catches ``OSError`` and
   ``ValueError`` (Pydantic ``ValidationError`` is a ``ValueError`` subclass) and
   returns ``None`` so a tampered or torn file degrades to "start over" rather than
   crashing the launch (threat T-15-01).
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003  # runtime-needed for Pydantic field validation
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)

_DEFAULT_STATE_PATH: Path = Path.home() / ".notes-os" / "session-state.json"
"""Default location for the persisted session-resume state.

A sibling of the config file (``~/.notes-os/config.toml``) and the log directory
(``~/.notes-os/logs``).
"""

_TEMP_SUFFIX: str = ".tmp"
"""Suffix appended to the target path to form the atomic-write temp file."""


class SessionState(BaseModel):
    """Immutable snapshot of an in-progress sort session's position (UX-03).

    Persisted by :class:`ResumeStore` so a relaunch can offer to resume where the
    user left off.  Frozen so a state handed to the screen or written to disk can
    never be mutated after capture.

    The ``saved_at`` timestamp is INJECTED by the caller (production passes
    ``datetime.now()``; tests pass a fixed value) — it is never a
    ``default_factory`` on this frozen model.  ``saved_at`` is persisted for
    diagnostics / future "resume a stale session?" logic; it is NOT part of the
    :meth:`matches` staleness check.

    Attributes:
        inbox_folder: Name of the Apple Notes inbox folder the session was
            triaging (matches ``BridgeConfig.inbox_folder`` — a plain ``str``).
        note_ids: Ordered tuple of the inbox note ids at save time — the
            "signature" used for staleness detection (see :meth:`matches`).
        index: The current 0-based inbox position to resume at (``ge=0``).
        moved: Running count of notes moved so far (``ge=0``).
        skipped: Running count of notes skipped so far (``ge=0``).
        errors: Running count of notes that errored so far (``ge=0``).
        saved_at: Wall-clock time the state was captured.  INJECTED by the caller,
            never defaulted.  Not part of the staleness check.
    """

    model_config = ConfigDict(frozen=True)

    inbox_folder: str
    note_ids: tuple[str, ...]
    index: int = Field(ge=0)
    moved: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    saved_at: datetime

    def matches(self, inbox_folder: str, note_ids: tuple[str, ...]) -> bool:
        """Return whether this saved state is still fresh for the current inbox.

        Staleness rule (design decision 1): the state matches ONLY when the saved
        ``inbox_folder`` equals *inbox_folder* AND the saved ``note_ids`` tuple is
        EXACTLY equal (same ids, same order) to *note_ids*.  A reorder, an added
        note, a removed note, or a different inbox all make it stale.  ``saved_at``
        is intentionally NOT consulted.

        Args:
            inbox_folder: The current inbox folder name to compare against.
            note_ids: The current inbox note-id signature to compare against.

        Returns:
            ``True`` if the saved position still applies exactly to the current
            inbox; ``False`` otherwise (stale → the screen should start over).
        """
        return self.inbox_folder == inbox_folder and self.note_ids == note_ids


class ResumeStore:
    """Persists and restores a :class:`SessionState` on disk (UX-03).

    A plain class (not a Pydantic model — it holds a path and performs I/O).  The
    path is injectable for tests; production uses :data:`_DEFAULT_STATE_PATH`.

    Contract:

    - :meth:`save` writes atomically (temp file + ``Path.replace``) and creates
      missing parent directories.
    - :meth:`load` returns the state on a well-formed file, ``None`` on a missing
      file, and ``None`` on a corrupt/schema-invalid file — it NEVER raises.
    - :meth:`clear` removes the file (no-op when absent; never raises).
    """

    def __init__(self, path: Path | None = None) -> None:
        """Initialise the store with an optional explicit state-file path.

        Args:
            path: Explicit path to the state file, or ``None`` to use the default
                location (:data:`_DEFAULT_STATE_PATH`, ``~/.notes-os/session-state.json``).
        """
        self.path: Path = path if path is not None else _DEFAULT_STATE_PATH

    def save(self, state: SessionState) -> None:
        """Persist *state* to :attr:`path` atomically.

        Creates the parent directory if absent, writes the serialised JSON to a
        temp file in the SAME directory, then ``Path.replace``s it over the target
        (an atomic same-filesystem rename).  A crash between the two steps leaves
        either the old file or no file — never a torn/partial JSON (threat
        T-15-02).

        Args:
            state: The :class:`SessionState` snapshot to persist.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + _TEMP_SUFFIX)
        temp.write_text(state.model_dump_json(), encoding="utf-8")
        temp.replace(self.path)
        logger.debug("Saved session state to %s", self.path)

    def load(self) -> SessionState | None:
        """Load the persisted :class:`SessionState`, or ``None`` — NEVER raises.

        Returns ``None`` when the file is missing AND when it exists but is
        corrupt/unparseable (catching ``OSError`` and ``ValueError``; Pydantic's
        ``ValidationError`` is a ``ValueError`` subclass).  A tampered or torn file
        degrades to "start over" rather than crashing the launch (threat T-15-01,
        design decision 4).

        Returns:
            The loaded :class:`SessionState`, or ``None`` if the file is missing or
            cannot be parsed/validated.
        """
        if not self.path.exists():
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
            return SessionState.model_validate_json(text)
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable session state at %s", self.path, exc_info=True)
            return None

    def clear(self) -> None:
        """Remove the persisted state file, if present.

        Idempotent: clearing an absent file is a no-op (``missing_ok=True``) and
        never raises.
        """
        self.path.unlink(missing_ok=True)
        logger.debug("Cleared session state at %s", self.path)
