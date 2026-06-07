"""Pure heuristic task extractor for NotesOS.

Scans plain-text note bodies for action items using three LOCKED signal
families: action phrases, named commitments, and inline dates/deadlines.

This module is intentionally pure — no I/O, no configuration loading, no
network or filesystem access.  ``extract_tasks`` is a deterministic function
that maps ``str -> list[ExtractedTask]`` with no side effects observable by
the caller.  The same input always produces the same output.

Signal families (LOCKED per PRD):
    1. Action phrases  — "need to", "follow up", "TODO", "schedule",
       "remind", "I will", "we should"
    2. Named commitments — ``[Capitalized name] will`` + literal "I promised"
    3. Inline dates — "by <Weekday>", "next week", ISO ``YYYY-MM-DD``,
       numeric ``M/D`` or ``MM/DD``
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frozen data model
# ---------------------------------------------------------------------------


class ExtractedTask(BaseModel):
    """A single extracted action item from a note's plain-text body.

    This model is intentionally minimal — a single ``text`` field holding
    the cleaned sentence fragment that matched at least one signal regex.
    Frozen so that downstream consumers (UI, writer) cannot mutate it.

    Attributes:
        text: The cleaned sentence fragment that triggered extraction.
            Always a non-empty string (empty fragments are filtered before
            constructing this object).
    """

    model_config = ConfigDict(frozen=True)

    text: str


# ---------------------------------------------------------------------------
# Compiled signal regexes (module-level for performance; LOCKED families)
# ---------------------------------------------------------------------------

# Family 1 — action phrases (case-insensitive alternation over 7 phrases)
# Uses word-boundary + alternation; no nested quantifiers (ReDoS safe).
_RE_ACTION = re.compile(
    r"\b(?:need\s+to|follow\s+up|todo|schedule|remind|i\s+will|we\s+should)\b",
    re.IGNORECASE,
)

# Family 2 — named commitments
# 2a. [Capitalized name] will (single word, first-letter upper, rest lower)
_RE_NAME_WILL = re.compile(r"\b[A-Z][a-z]+\s+will\b")
# 2b. Literal "I promised"
_RE_I_PROMISED = re.compile(r"\bI\s+promised\b", re.IGNORECASE)

# Family 3 — inline dates / deadlines (three sub-patterns, no backtracking)
# 3a. "by <Weekday>" — anchored to a limited set of English weekday names
_RE_BY_WEEKDAY = re.compile(
    r"\bby\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
# 3b. "next week" (common deadline shorthand)
_RE_NEXT_WEEK = re.compile(r"\bnext\s+week\b", re.IGNORECASE)
# 3c. ISO date (YYYY-MM-DD) or numeric M/D or MM/DD
_RE_DATE_NUMERIC = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}\b")

# Ordered list of all signal regexes (used in _matches_any_signal)
_SIGNAL_REGEXES: list[re.Pattern[str]] = [
    _RE_ACTION,
    _RE_NAME_WILL,
    _RE_I_PROMISED,
    _RE_BY_WEEKDAY,
    _RE_NEXT_WEEK,
    _RE_DATE_NUMERIC,
]

# Sentence splitter — splits on sentence-ending punctuation or newlines.
# Using a simple character class (no nested quantifiers) to avoid ReDoS.
_RE_SPLIT = re.compile(r"[.\n!?]+")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _matches_any_signal(fragment: str) -> bool:
    """Return True if *fragment* matches at least one signal regex.

    Args:
        fragment: A single stripped sentence fragment.

    Returns:
        ``True`` if any compiled signal regex finds a match; ``False`` otherwise.
    """
    return any(pat.search(fragment) for pat in _SIGNAL_REGEXES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_tasks(text: str) -> list[ExtractedTask]:
    """Scan *text* for action items using heuristic signal families.

    Splits *text* into sentence fragments (on ``[.\\n!?]+``), strips
    whitespace, and returns one :class:`ExtractedTask` per fragment that
    matches at least one signal regex.  Results are de-duplicated by
    ``.text``, preserving first-seen order.

    This function is **pure**: it performs no I/O, reads no configuration,
    makes no network calls, and has no observable side effects.  Calling it
    twice with the same *text* always returns an equal result.

    Args:
        text: The plain-text body of a note.  May be empty, whitespace-only,
            or multi-line.  HTML tags are NOT stripped here — callers should
            pass the plain-text preview, not the raw HTML body.

    Returns:
        An ordered list of :class:`ExtractedTask` objects, one per distinct
        matching fragment.  Returns ``[]`` when *text* is empty, whitespace-
        only, or contains no known signal patterns.
    """
    stripped = text.strip()
    if not stripped:
        return []

    fragments = _RE_SPLIT.split(stripped)
    seen: set[str] = set()
    results: list[ExtractedTask] = []

    for raw_fragment in fragments:
        fragment = raw_fragment.strip()
        if not fragment:
            continue
        if not _matches_any_signal(fragment):
            continue
        if fragment in seen:
            continue
        seen.add(fragment)
        results.append(ExtractedTask(text=fragment))

    return results


# ---------------------------------------------------------------------------
# TaskWriter — Markdown checkbox file writer
# ---------------------------------------------------------------------------


class TaskWriter:
    """Appends extracted tasks as Markdown checkboxes to a daily file.

    Each call to :meth:`write` appends ``- [ ] {task.text}`` lines to
    ``{target_dir}/YYYY-MM-DD.md``, where the date is supplied by an
    injectable clock callable.  The target directory and its parents are
    created if absent.  Calling :meth:`write` with an empty sequence is a
    no-op — no file is created and nothing is written.

    This class is NOT a Pydantic model.  It is a plain Python class with
    injected dependencies so that tests can supply a deterministic clock and
    a temporary directory without touching the real filesystem.

    Args:
        target_dir: Directory under which daily ``YYYY-MM-DD.md`` files are
            written.  Created on first write if absent.
        clock: Zero-argument callable that returns today's :class:`datetime.date`.
            Defaults to :func:`datetime.date.today`.  Inject a fixed-date
            lambda in tests to make output deterministic.
    """

    def __init__(
        self,
        target_dir: Path,
        clock: Callable[[], date] | None = None,
    ) -> None:
        """Initialise TaskWriter with an output directory and optional clock.

        Args:
            target_dir: Directory for daily Markdown task files.
            clock: Date provider callable (default: ``date.today``).
        """
        self._target_dir = target_dir
        self._clock: Callable[[], date] = clock if clock is not None else date.today

    def write(self, tasks: Sequence[ExtractedTask]) -> Path | None:
        """Append *tasks* as Markdown checkboxes to today's daily file.

        If *tasks* is empty, this method is a no-op and returns ``None`` —
        no file is created and no filesystem access occurs.

        Otherwise the method ensures ``target_dir`` exists, then opens
        ``{target_dir}/{YYYY-MM-DD}.md`` in append mode and writes one
        ``- [ ] {task.text}`` line per task.  If the file already exists its
        content is preserved; new lines follow any previously written content
        (append-if-present semantics).

        Args:
            tasks: Sequence of :class:`ExtractedTask` objects to write.
                Empty sequence is a no-op.

        Returns:
            The :class:`~pathlib.Path` of the written file, or ``None`` if
            *tasks* was empty.
        """
        if not tasks:
            return None

        self._target_dir.mkdir(parents=True, exist_ok=True)
        filename = self._clock().isoformat() + ".md"
        file_path = self._target_dir / filename

        with file_path.open("a", encoding="utf-8") as fh:
            for task in tasks:
                fh.write(f"- [ ] {task.text}\n")

        logger.info(
            "Wrote %d task(s) to %s",
            len(tasks),
            file_path,
        )
        return file_path
