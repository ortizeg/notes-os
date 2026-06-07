"""Apple Notes AppleScript bridge — read operations and protocol contract.

Provides the ``NotesRepositoryProtocol`` interface that every caller (router,
UI, session, TUI) uses instead of raw AppleScript, plus the
``AppleScriptNotesRepository`` implementation for the read side of the bridge
(``get_inbox_notes``, ``get_para_structure``).

Write operations (``move_note``, ``ensure_folder``) are declared on the protocol
and stubbed as ``NotImplementedError`` placeholders; plan 02-02 fills their bodies.

Delimiter constants
-------------------
AppleScript output is parsed using two control characters that cannot appear in
note titles or bodies as structural delimiters:

- ``_FIELD_SEP`` — ASCII Unit Separator (US, chr(31), ``\\x1f``) separates fields
  within a single record (e.g. id, title, body for one note).
- ``_RECORD_SEP`` — ASCII Record Separator (RS, chr(30), ``\\x1e``) separates
  consecutive records (e.g. one note from the next).

These characters are chosen because they cannot appear in Apple Notes HTML bodies
or titles as meaningful content, so note text containing commas, quotes,
apostrophes, newlines, or Unicode cannot forge a record boundary.
"""

from __future__ import annotations

import html
import logging
import re
import subprocess
from html.parser import HTMLParser
from typing import Protocol, runtime_checkable

from notes_os.exceptions import NotesOSError
from notes_os.sorter.models import BridgeConfig, FolderPath, Note, ParaStructure


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delimiter constants — must match the AppleScript output format exactly.
# ---------------------------------------------------------------------------

_FIELD_SEP: str = chr(31)
"""ASCII Unit Separator (US, 0x1F) — separates fields within one record."""

_RECORD_SEP: str = chr(30)
"""ASCII Record Separator (RS, 0x1E) — separates consecutive records."""

# Compiled pattern for collapsing runs of whitespace (used by _strip_html).
_WS_RE: re.Pattern[str] = re.compile(r"\s+")

# Block-level HTML tags whose boundaries should inject whitespace so adjacent
# text blocks do not run together in the plain-text preview.
_BLOCK_TAGS: frozenset[str] = frozenset(
    {"div", "p", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}
)


# ---------------------------------------------------------------------------
# Protocol contract (BRDG-07)
# ---------------------------------------------------------------------------


@runtime_checkable
class NotesRepositoryProtocol(Protocol):
    """The sole AppleScript boundary in NotesOS.

    Every caller (router, UI, session, TUI) communicates with Apple Notes
    exclusively through this protocol.  No module outside ``notes.py`` invokes
    ``osascript`` directly.

    Read operations (``get_inbox_notes``, ``get_para_structure``) are
    implemented in plan 02-01.  Write operations (``move_note``,
    ``ensure_folder``) are implemented in plan 02-02.
    """

    def get_inbox_notes(self) -> list[Note]:
        """Return all notes in the configured inbox folder.

        Returns:
            A list of :class:`~notes_os.sorter.models.Note` objects, each
            with ``id``, ``title``, ``body`` (raw HTML), and ``preview``
            (plain-text excerpt).  Returns an empty list when the inbox is
            empty or the AppleScript returns no output.

        Raises:
            NotesOSError: If the osascript subprocess exits with a non-zero
                return code.
        """
        ...

    def get_para_structure(self) -> ParaStructure:
        """Return a snapshot of the PARA folder hierarchy in Apple Notes.

        Returns:
            A :class:`~notes_os.sorter.models.ParaStructure` mapping each
            configured PARA root to its runtime-discovered subfolders.  Roots
            with no immediate children map to an empty tuple.

        Raises:
            NotesOSError: If the osascript subprocess exits with a non-zero
                return code.
        """
        ...

    def move_note(self, note_id: str, folder_path: FolderPath) -> None:
        """Move a note to the specified folder path.

        Args:
            note_id: The opaque Apple Notes note identifier.
            folder_path: Ordered tuple of folder names describing the
                destination (e.g. ``("Projects", "NotesOS")``).

        Raises:
            NotesOSError: If the osascript subprocess exits with a non-zero
                return code.
        """
        ...

    def ensure_folder(self, folder_path: FolderPath) -> None:
        """Create a folder (and any missing ancestors) if it does not exist.

        Args:
            folder_path: Ordered tuple of folder names to create if absent
                (e.g. ``("Archive", "2026")``).

        Raises:
            NotesOSError: If the osascript subprocess exits with a non-zero
                return code.
        """
        ...


# ---------------------------------------------------------------------------
# HTML stripper (BRDG-05)
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Minimal HTML-to-plain-text converter using only the stdlib.

    Collects text runs from ``handle_data`` and injects whitespace boundaries
    at block-level tags so adjacent blocks (``<div>``, ``<p>``, ``<br>``, etc.)
    do not run their text together in the plain-text output.

    Use :func:`_strip_html` rather than instantiating this class directly.
    """

    def __init__(self) -> None:
        """Initialise the parser with an empty text buffer."""
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        """Accumulate a text run.

        Args:
            data: Raw text content between or after HTML tags.
        """
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Inject a space boundary before block-level opening tags.

        Args:
            tag: Lower-cased HTML tag name.
            attrs: Sequence of ``(name, value)`` attribute pairs (unused).
        """
        if tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        """Inject a space boundary after block-level closing tags.

        Args:
            tag: Lower-cased HTML tag name.
        """
        if tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def get_text(self) -> str:
        """Return the accumulated plain text with collapsed whitespace.

        Returns:
            A single string with all runs of whitespace compressed to a
            single space and leading/trailing whitespace removed.
        """
        joined = "".join(self._parts)
        return _WS_RE.sub(" ", joined).strip()


def _strip_html(raw: str, preview_length: int) -> str:
    """Strip HTML tags from *raw*, decode entities, and truncate to *preview_length*.

    Args:
        raw: Raw HTML string (as returned by Apple Notes ``body`` property).
        preview_length: Maximum number of characters in the returned string.

    Returns:
        Plain-text preview, at most *preview_length* characters long.
        Returns an empty string when *raw* is empty or whitespace-only.
        Plain text (no tags) passes through unchanged (up to truncation).
    """
    if not raw or not raw.strip():
        return ""

    stripper = _HTMLStripper()
    stripper.feed(raw)
    text = stripper.get_text()
    # HTMLParser(convert_charrefs=True) decodes numeric refs; apply html.unescape
    # as a safety net for named entities that may survive in edge cases.
    text = html.unescape(text)
    text = text.strip()
    return text[:preview_length]


# ---------------------------------------------------------------------------
# Repository implementation
# ---------------------------------------------------------------------------


class AppleScriptNotesRepository:
    """AppleScript-backed implementation of :class:`NotesRepositoryProtocol`.

    All communication with Apple Notes goes through :meth:`_run_osascript`.
    Folder names and inbox name are sourced exclusively from the injected
    ``BridgeConfig`` — no hardcoded strings, no global state.

    Args:
        config: Frozen bridge configuration supplying inbox folder name, PARA
            root names, and preview length.
    """

    def __init__(self, config: BridgeConfig) -> None:
        """Store the injected configuration.

        Args:
            config: The :class:`~notes_os.sorter.models.BridgeConfig` instance
                driving this repository's behaviour.
        """
        self._config = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_osascript(self, script: str) -> str:
        """Execute *script* via ``osascript`` and return stdout.

        Args:
            script: A complete AppleScript program passed to ``osascript -e``.

        Returns:
            The captured stdout of the subprocess on success (may be empty).

        Raises:
            NotesOSError: If the subprocess exits with a non-zero return code.
                A ``# 02-02: narrow to NotesError`` comment marks the raise site
                for plan 02-02, which introduces the typed ``NotesError`` hierarchy
                and replaces this ``NotesOSError`` with the more specific subclass.
        """
        result = subprocess.run(  # noqa: S603  # fixed trusted macOS binary, list args, no shell=True
            ["osascript", "-e", script],  # noqa: S607  # osascript is a fixed macOS system binary at /usr/bin/osascript
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "osascript exited %d: %s",
                result.returncode,
                result.stderr.strip(),
            )
            # 02-02: narrow to NotesError (AppleScriptError subclass)
            raise NotesOSError(result.stderr.strip() or "osascript failed")
        return result.stdout

    # ------------------------------------------------------------------
    # Read operations (BRDG-01, BRDG-02)
    # ------------------------------------------------------------------

    def get_inbox_notes(self) -> list[Note]:
        """Return all notes in the configured inbox folder.

        Builds an AppleScript that iterates the inbox folder and emits one
        record per note in the format::

            <id> _FIELD_SEP <name> _FIELD_SEP <body>

        Records are joined by ``_RECORD_SEP``.  The output is split and parsed
        into :class:`~notes_os.sorter.models.Note` objects; ``preview`` is
        populated by :func:`_strip_html`.

        Returns:
            A list of :class:`~notes_os.sorter.models.Note` objects.  Returns
            an empty list when the inbox is empty or osascript output is blank.

        Raises:
            NotesOSError: On non-zero osascript exit code.
                (02-02: narrow to NotesError)
        """
        inbox = self._config.inbox_folder.replace('"', '""')  # AppleScript-escape double-quotes
        script = f"""\
tell application "Notes"
    set fs to (ASCII character 31)
    set rs to (ASCII character 30)
    set inbox to folder "{inbox}"
    set noteList to notes of inbox
    set output to ""
    repeat with aNote in noteList
        set noteID to id of aNote
        set noteTitle to name of aNote
        set noteBody to body of aNote
        if output is "" then
            set output to noteID & fs & noteTitle & fs & noteBody
        else
            set output to output & rs & noteID & fs & noteTitle & fs & noteBody
        end if
    end repeat
    return output
end tell"""
        stdout = self._run_osascript(script)
        if not stdout or not stdout.strip():
            return []

        notes: list[Note] = []
        for record in stdout.split(_RECORD_SEP):
            # Do NOT strip the record: trailing _FIELD_SEP marks an empty body field.
            # Only skip records that contain no non-whitespace characters at all.
            if not record or not record.strip():
                continue
            parts = record.split(_FIELD_SEP, 2)
            if len(parts) != 3:
                logger.warning(
                    "Skipping malformed note record (expected 3 fields, got %d)",
                    len(parts),
                )
                continue
            note_id, title, body = parts
            notes.append(
                Note(
                    id=note_id.strip(),
                    title=title.strip(),
                    body=body,
                    preview=_strip_html(body, self._config.preview_length),
                )
            )
        return notes

    def get_para_structure(self) -> ParaStructure:
        """Return a snapshot of the PARA folder hierarchy in Apple Notes.

        Builds an AppleScript that, for each configured PARA root, emits the
        names of its immediate subfolders.  Each record is::

            <rootName> _FIELD_SEP <subfolderName>

        For roots with no subfolders a bare ``<rootName>`` record is emitted so
        the root still appears in the structure.  Records are joined by
        ``_RECORD_SEP``.

        Returns:
            A :class:`~notes_os.sorter.models.ParaStructure` with all
            configured roots present; roots with no children map to ``()``.

        Raises:
            NotesOSError: On non-zero osascript exit code.
                (02-02: narrow to NotesError)
        """
        # Build AppleScript root-list literal from config (names are AppleScript-escaped).
        roots_literal = ", ".join(
            f'"{r.replace(chr(34), chr(34) + chr(34))}"'
            for r in self._config.para_folders
        )
        script = f"""\
tell application "Notes"
    set fs to (ASCII character 31)
    set rs to (ASCII character 30)
    set paraRoots to {{{roots_literal}}}
    set output to ""
    repeat with rootName in paraRoots
        try
            set rootFolder to folder rootName
            set subList to folders of rootFolder
            if (count of subList) is 0 then
                if output is "" then
                    set output to rootName
                else
                    set output to output & rs & rootName
                end if
            else
                repeat with aSub in subList
                    set subName to name of aSub
                    if output is "" then
                        set output to rootName & fs & subName
                    else
                        set output to output & rs & rootName & fs & subName
                    end if
                end repeat
            end if
        on error
            if output is "" then
                set output to rootName
            else
                set output to output & rs & rootName
            end if
        end try
    end repeat
    return output
end tell"""
        stdout = self._run_osascript(script)

        # Preserve config order for roots; use a list to maintain insertion order.
        ordered_roots: list[str] = list(self._config.para_folders)
        subfolders_map: dict[str, list[str]] = {r: [] for r in ordered_roots}
        seen_roots: set[str] = set()

        if stdout and stdout.strip():
            for record in stdout.split(_RECORD_SEP):
                if not record or not record.strip():
                    continue
                parts = record.split(_FIELD_SEP, 1)
                root_name = parts[0].strip()
                seen_roots.add(root_name)
                if len(parts) == 2:
                    sub_name = parts[1].strip()
                    if root_name in subfolders_map:
                        subfolders_map[root_name].append(sub_name)

        return ParaStructure(
            roots=tuple(ordered_roots),
            subfolders={k: tuple(v) for k, v in subfolders_map.items()},
        )

    # ------------------------------------------------------------------
    # Write operation placeholders (implemented in plan 02-02)
    # ------------------------------------------------------------------

    def move_note(self, note_id: str, folder_path: FolderPath) -> None:
        """Move a note to the specified folder path.

        Args:
            note_id: The opaque Apple Notes note identifier.
            folder_path: Ordered tuple of folder names describing the
                destination (e.g. ``("Projects", "NotesOS")``).

        Raises:
            NotImplementedError: This method is implemented in plan 02-02.
        """
        raise NotImplementedError("Implemented in plan 02-02")

    def ensure_folder(self, folder_path: FolderPath) -> None:
        """Create a folder (and any missing ancestors) if it does not exist.

        Args:
            folder_path: Ordered tuple of folder names to create if absent
                (e.g. ``("Archive", "2026")``).

        Raises:
            NotImplementedError: This method is implemented in plan 02-02.
        """
        raise NotImplementedError("Implemented in plan 02-02")
