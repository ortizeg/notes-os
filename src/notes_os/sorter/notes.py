"""Apple Notes AppleScript bridge — protocol contract and read/write operations.

Provides the ``NotesRepositoryProtocol`` interface that every caller (router,
UI, session, TUI) uses instead of raw AppleScript, plus the
``AppleScriptNotesRepository`` implementation covering both the read side
(``get_inbox_notes``, ``get_para_structure``) and the write side
(``move_note``, ``ensure_folder``) of the bridge.

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

from notes_os.exceptions import FolderNotFoundError, NotesError, NotesMoveError
from notes_os.sorter.models import BridgeConfig, FolderPath, Note, NoteRef, ParaStructure


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delimiter constants — must match the AppleScript output format exactly.
# ---------------------------------------------------------------------------

_FIELD_SEP: str = chr(31)
"""ASCII Unit Separator (US, 0x1F) — separates fields within one record."""

_RECORD_SEP: str = chr(30)
"""ASCII Record Separator (RS, 0x1E) — separates consecutive records."""

_OSASCRIPT_TIMEOUT_SECONDS: float = 30.0
"""Hard ceiling for any single ``osascript`` call.

Without a timeout a stuck Apple Event — most commonly the first run blocking on
the macOS "control Notes" Automation permission prompt, which can be hidden
behind a full-screen TUI — would block the calling thread (and therefore the
app's shutdown) indefinitely.  On timeout the call is abandoned and surfaced as
a :class:`~notes_os.exceptions.NotesError` so callers degrade gracefully.
"""

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
            NotesError: If the osascript subprocess exits with a non-zero
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
            NotesError: If the osascript subprocess exits with a non-zero
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
            NotesError: If the osascript subprocess exits with a non-zero
                return code.
            FolderNotFoundError: If the destination folder path does not exist.
            NotesMoveError: If the note id cannot be found.
        """
        ...

    def ensure_folder(self, folder_path: FolderPath) -> None:
        """Create a folder (and any missing ancestors) if it does not exist.

        Args:
            folder_path: Ordered tuple of folder names to create if absent
                (e.g. ``("Archive", "2026")``).

        Raises:
            NotesError: If the osascript subprocess exits with a non-zero
                return code.
        """
        ...

    def count_inbox_notes(self) -> int:
        """Return the number of notes in the configured inbox folder.

        Uses ``count notes of folder`` — a single fast AppleScript call that
        does not fetch any note content, making it significantly faster than
        ``len(get_inbox_notes())`` on large inboxes.

        Returns:
            The number of notes currently in the configured inbox folder.
            Returns 0 when the inbox is empty or the osascript output is blank.

        Raises:
            NotesError: If the osascript subprocess exits with a non-zero
                return code or returns non-numeric output.
        """
        ...

    def get_inbox_note_refs(self) -> list[NoteRef]:
        """Return lightweight references (id + title) for all inbox notes.

        Fetches only note identifiers and titles via two bulk AppleScript
        property reads — no HTML bodies are fetched.  This is the fast path
        for large inboxes: two Apple Events total regardless of inbox size.

        Returns:
            A list of :class:`~notes_os.sorter.models.NoteRef` objects, each
            with ``id`` and ``title`` only.  Returns an empty list when the
            inbox is empty or the AppleScript returns no output.

        Raises:
            NotesError: If the osascript subprocess exits with a non-zero
                return code.
        """
        ...

    def get_note(self, note_id: str) -> Note:
        """Fetch a single note's full content (id, title, body, preview) by id.

        Used by the lazy-loading TUI path to fetch each note's HTML body on
        demand after the inbox refs have been loaded.

        Args:
            note_id: The opaque Apple Notes note identifier
                (e.g. ``"x-coredata://..."``).

        Returns:
            A :class:`~notes_os.sorter.models.Note` with all four fields
            populated (``id``, ``title``, ``body``, ``preview``).

        Raises:
            NotesMoveError: If no note with ``note_id`` exists in Apple Notes.
            NotesError: If the osascript subprocess exits with a non-zero
                return code for any other reason.
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
            NotesError: If the subprocess exits with a non-zero return code
                (message contains osascript's stderr, or ``"osascript failed"``
                when stderr is empty), or if it does not return within
                ``_OSASCRIPT_TIMEOUT_SECONDS`` (e.g. blocked on the macOS
                Automation permission prompt).
        """
        try:
            result = subprocess.run(  # noqa: S603  # fixed trusted macOS binary, list args, no shell=True
                ["osascript", "-e", script],  # noqa: S607  # osascript is a fixed macOS system binary at /usr/bin/osascript
                capture_output=True,
                text=True,
                check=False,
                timeout=_OSASCRIPT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            msg = (
                f"osascript timed out after {_OSASCRIPT_TIMEOUT_SECONDS:.0f}s — "
                "Apple Notes may be waiting on an Automation permission prompt. "
                "Grant access in System Settings > Privacy & Security > Automation, "
                "or run `osascript -e 'tell application \"Notes\" to count notes'` "
                "once and click Allow."
            )
            logger.warning(msg)
            raise NotesError(msg) from exc
        if result.returncode != 0:
            logger.warning(
                "osascript exited %d: %s",
                result.returncode,
                result.stderr.strip(),
            )
            raise NotesError(result.stderr.strip() or "osascript failed")
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
            NotesError: On non-zero osascript exit code.
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

    def get_inbox_note_refs(self) -> list[NoteRef]:
        """Return lightweight references (id + title) for all inbox notes.

        Fetches only note identifiers and titles using two bulk AppleScript
        property-list reads — ``id of notes`` and ``name of notes``.  This
        issues two Apple Events total regardless of inbox size, skipping the
        expensive ``body`` property entirely.

        Returns:
            A list of :class:`~notes_os.sorter.models.NoteRef` objects.
            Returns an empty list when the inbox is empty or osascript output
            is blank.

        Raises:
            NotesError: On non-zero osascript exit code.
        """
        inbox = self._config.inbox_folder.replace('"', '""')
        script = f"""\
tell application "Notes"
    set fs to (ASCII character 31)
    set rs to (ASCII character 30)
    set inbox to folder "{inbox}"
    set theIDs to id of notes of inbox
    set theNames to name of notes of inbox
    set output to ""
    repeat with i from 1 to (count of theIDs)
        if output is not "" then set output to output & rs
        set output to output & (item i of theIDs) & fs & (item i of theNames)
    end repeat
    return output
end tell"""
        stdout = self._run_osascript(script)
        if not stdout or not stdout.strip():
            return []

        refs: list[NoteRef] = []
        for record in stdout.split(_RECORD_SEP):
            # Skip empty records (e.g. from a trailing _RECORD_SEP)
            if not record or not record.strip():
                continue
            parts = record.split(_FIELD_SEP, 1)
            if len(parts) != 2:
                logger.warning(
                    "Skipping malformed note-ref record (expected 2 fields, got %d)",
                    len(parts),
                )
                continue
            note_id, title = parts
            refs.append(NoteRef(id=note_id.strip(), title=title.strip()))
        return refs

    def get_note(self, note_id: str) -> Note:
        """Fetch a single note's full content (id, title, body, preview) by id.

        Issues one AppleScript call that reads the ``id``, ``name``, and
        ``body`` of the note addressed by *note_id*.  If the note id does not
        exist, ``osascript`` exits non-zero and the resulting ``NotesError``
        is re-raised as ``NotesMoveError`` to match the not-found convention
        used by :meth:`move_note`.

        Args:
            note_id: The opaque Apple Notes note identifier.

        Returns:
            A :class:`~notes_os.sorter.models.Note` with all four fields
            populated.

        Raises:
            NotesMoveError: If no note with ``note_id`` exists in Apple Notes.
            NotesError: If osascript exits non-zero for any other reason.
        """
        escaped_id = note_id.replace('"', '""')
        script = f"""\
tell application "Notes"
    set fs to (ASCII character 31)
    set aNote to note id "{escaped_id}"
    return (id of aNote) & fs & (name of aNote) & fs & (body of aNote)
end tell"""
        try:
            stdout = self._run_osascript(script)
        except NotesError as exc:
            raise NotesMoveError(f"note not found: {note_id}") from exc

        parts = stdout.split(_FIELD_SEP, 2)
        if len(parts) != 3:
            raise NotesMoveError(f"note not found: {note_id}")
        fetched_id, title, body = parts
        return Note(
            id=fetched_id.strip(),
            title=title.strip(),
            body=body,
            preview=_strip_html(body, self._config.preview_length),
        )

    def count_inbox_notes(self) -> int:
        """Return the number of notes in the configured inbox folder.

        Issues a single ``count notes of folder`` AppleScript call — no note
        content is fetched.  Significantly faster than
        ``len(get_inbox_notes())`` on large inboxes.

        Returns:
            The number of notes in the inbox.  Returns ``0`` when the inbox
            is empty or the osascript output is blank.

        Raises:
            NotesError: If osascript exits with a non-zero return code or
                returns non-numeric output.
        """
        inbox = self._config.inbox_folder.replace('"', '""')
        script = f"""\
tell application "Notes"
    return count notes of folder "{inbox}"
end tell"""
        stdout = self._run_osascript(script)
        stripped = stdout.strip()
        if not stripped:
            return 0
        try:
            return int(stripped)
        except ValueError:
            raise NotesError(f"count_inbox_notes: expected integer, got {stripped!r}") from None

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
            NotesError: On non-zero osascript exit code.
        """
        # Build AppleScript root-list literal from config (names are AppleScript-escaped).
        roots_literal = ", ".join(
            f'"{r.replace(chr(34), chr(34) + chr(34))}"' for r in self._config.para_folders
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
    # Write operations (BRDG-03, BRDG-04)
    # ------------------------------------------------------------------

    def _folder_reference(self, folder_path: FolderPath) -> str:
        """Build an AppleScript folder reference from an ordered path tuple.

        Converts a ``FolderPath`` tuple (root-first) into the nested AppleScript
        ``folder X of folder Y of ...`` expression used to address a folder in
        the Notes application.  Folder names containing double-quotes are escaped
        by doubling them (standard AppleScript string escaping).

        For a 2-level path ``("Projects", "Web")`` the result is::

            folder "Web" of folder "Projects"

        For a 3-level path ``("Projects", "Web", "Research")`` the result is::

            folder "Research" of folder "Web" of folder "Projects"

        Args:
            folder_path: Ordered tuple of folder names, root first.  Must have
                at least one element.

        Returns:
            An AppleScript expression string addressing the target folder.
        """
        # AppleScript-escape double-quotes by doubling them (T-02-04 mitigation).
        escaped = [name.replace('"', '""') for name in folder_path]
        # Build the reference from deepest (last) to shallowest (first).
        parts = [f'folder "{name}"' for name in reversed(escaped)]
        return " of ".join(parts)

    def move_note(self, note_id: str, folder_path: FolderPath) -> None:
        """Move a note to the specified folder path.

        Resolves the destination ``folder_path`` to an AppleScript reference,
        verifies that the folder exists, verifies the note exists by ID, then
        issues the ``move`` command.  Sentinel error tokens in the osascript
        output are mapped to typed exceptions.

        Note:
            Does NOT create the destination folder — caller must call
            ``ensure_folder`` first.  This separation prevents accidental folder
            creation on a typo'd path (T-02-05 mitigation).

        Args:
            note_id: The opaque Apple Notes note identifier
                (e.g. ``"x-coredata://..."``) used to address the note.
            folder_path: Ordered tuple of folder names describing the
                destination (e.g. ``("Projects", "NotesOS")``).

        Returns:
            None on success.

        Raises:
            FolderNotFoundError: If the destination folder path does not exist
                in the Notes folder hierarchy.
            NotesMoveError: If the note with ``note_id`` cannot be found.
            NotesError: If osascript exits with a non-zero return code for any
                other reason.
        """
        folder_ref = self._folder_reference(folder_path)
        # Escape the note_id for AppleScript (opaque CoreData URI — double any quotes).
        escaped_id = note_id.replace('"', '""')
        script = f"""\
tell application "Notes"
    if not (exists {folder_ref}) then
        error "FOLDER_NOT_FOUND"
    end if
    if not (exists note id "{escaped_id}") then
        error "NOTE_NOT_FOUND"
    end if
    move note id "{escaped_id}" to {folder_ref}
    return "OK"
end tell"""
        try:
            self._run_osascript(script)
        except NotesError as exc:
            msg = str(exc)
            if "FOLDER_NOT_FOUND" in msg:
                raise FolderNotFoundError(folder_path) from exc
            if "NOTE_NOT_FOUND" in msg:
                raise NotesMoveError(note_id) from exc
            raise

    def ensure_folder(self, folder_path: FolderPath) -> None:
        """Create a folder (and any missing ancestors) if it does not exist.

        Idempotently ensures each prefix of ``folder_path`` exists in the Notes
        folder hierarchy.  Existing levels are left untouched; missing levels are
        created in order from the shallowest to the deepest.  Calling this method
        on a fully-existing path is a no-op (no duplicate folders created).

        Args:
            folder_path: Ordered tuple of folder names to create if absent
                (e.g. ``("Archive", "2026")``).  Each element represents one
                nesting level starting from a top-level Notes folder.

        Returns:
            None on success.

        Raises:
            NotesError: If osascript exits with a non-zero return code.
        """
        # Build one AppleScript statement per path prefix, guarded by an
        # existence check so existing levels are never duplicated.
        statements: list[str] = []
        for depth in range(1, len(folder_path) + 1):
            prefix = folder_path[:depth]
            folder_ref = self._folder_reference(prefix)
            escaped_name = prefix[-1].replace('"', '""')
            if depth == 1:
                # Top-level folder: create at the application level.
                statements.append(
                    f"    if not (exists {folder_ref}) then\n"
                    f'        make new folder with properties {{name:"{escaped_name}"}}\n'
                    f"    end if"
                )
            else:
                # Nested folder: create inside the parent.
                parent_ref = self._folder_reference(prefix[:-1])
                statements.append(
                    f"    if not (exists {folder_ref}) then\n"
                    f'        make new folder with properties {{name:"{escaped_name}"}} at {parent_ref}\n'
                    f"    end if"
                )
        body = "\n".join(statements)
        script = f'tell application "Notes"\n{body}\nend tell'
        self._run_osascript(script)
