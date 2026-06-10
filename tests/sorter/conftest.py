"""Shared pytest fixtures and the MockNotesRepository test double for the sorter package.

Provides:
- ``MockNotesRepository`` — in-memory implementation of ``NotesRepositoryProtocol``
  for unit testing without any AppleScript or subprocess interaction.
- ``sample_notes`` fixture — a few representative ``Note`` objects covering edge cases
  (HTML body, apostrophes/Unicode in title, empty body).
- ``sample_structure`` fixture — a ``ParaStructure`` with all four PARA roots and one
  root with subfolders.
- ``mock_repo`` fixture — a ``MockNotesRepository`` seeded with the above fixtures.
"""

from __future__ import annotations

import pytest

from notes_os.exceptions import FolderNotFoundError, NotesMoveError
from notes_os.sorter.models import BridgeConfig, FolderPath, Note, NoteRef, ParaStructure
from notes_os.sorter.notes import NotesRepositoryProtocol


# Re-export so plan 02-03 tests can import the Protocol from this module
# instead of duplicating the import.
__all__ = ["MockNotesRepository", "NotesRepositoryProtocol"]

# ---------------------------------------------------------------------------
# MockNotesRepository
# ---------------------------------------------------------------------------


class MockNotesRepository:
    """In-memory implementation of :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`.

    Designed for unit tests.  No AppleScript, no subprocess.  Seed the
    repository with a list of notes and a ``ParaStructure`` at construction
    time; then assert on ``.moves`` and ``.created_folders`` to verify
    behaviour of higher-level callers (router, session, TUI).

    Args:
        notes: Seed list of :class:`~notes_os.sorter.models.Note` objects that
            populate the in-memory inbox at construction time.
        structure: Seed :class:`~notes_os.sorter.models.ParaStructure` that
            defines which folder paths are considered valid destinations.
    """

    def __init__(self, notes: list[Note], structure: ParaStructure) -> None:
        """Initialise the mock repository with seed data.

        Args:
            notes: Initial inbox contents.
            structure: PARA folder hierarchy that defines valid destinations.
        """
        self._inbox: list[Note] = list(notes)
        self._structure: ParaStructure = structure
        self.moves: list[tuple[str, tuple[str, ...]]] = []
        self.created_folders: list[tuple[str, ...]] = []
        # Notes moved OUT of the inbox (id → Note).  Tracked so a subsequent
        # move of the same id models an undo move-back: the note is RE-ADDED to
        # the inbox (UX-02 / B1).  See ``move_note`` for the full state machine.
        self._moved_out: dict[str, Note] = {}
        # Derive the set of known folder paths from the seed structure.
        # Both root-only paths and (root, subfolder) paths are valid destinations.
        self._known_paths: set[tuple[str, ...]] = set()
        for root in structure.roots:
            self._known_paths.add((root,))
            for sub in structure.subfolders_for(root):
                self._known_paths.add((root, sub))

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_inbox_notes(self) -> list[Note]:
        """Return a copy of the current in-memory inbox.

        Returns:
            A new list containing all notes currently in the inbox.  Mutations
            to the returned list do not affect internal state.
        """
        return list(self._inbox)

    def get_inbox_note_refs(self) -> list[NoteRef]:
        """Return lightweight refs (id + title) for the current in-memory inbox.

        Returns:
            A new list of :class:`~notes_os.sorter.models.NoteRef` objects
            derived from the seeded inbox notes.
        """
        return [NoteRef(id=n.id, title=n.title) for n in self._inbox]

    def get_note(self, note_id: str) -> Note:
        """Return the seeded note with the given id, or raise NotesMoveError.

        Args:
            note_id: The opaque note identifier to look up.

        Returns:
            The :class:`~notes_os.sorter.models.Note` from the seeded inbox.

        Raises:
            NotesMoveError: If ``note_id`` is not found in the seeded inbox.
        """
        for note in self._inbox:
            if note.id == note_id:
                return note
        raise NotesMoveError(note_id)

    def get_inbox_note_bodies(self, offset: int, count: int) -> list[Note]:
        """Return a folder-ordered slice of the seeded inbox notes.

        Mirrors :meth:`get_inbox_note_refs` ordering (both derive from
        ``self._inbox``) so the returned page is id-aligned to it.  Python
        slicing already clamps out-of-range offsets/counts: a *count* of 0, an
        *offset* past the end, or an empty inbox all yield ``[]``.

        Args:
            offset: 0-based start index into the in-memory inbox.
            count: Number of notes to return starting at *offset*.

        Returns:
            A new list with the requested folder-ordered slice of inbox notes.
        """
        return list(self._inbox[offset : offset + count])

    def count_inbox_notes(self) -> int:
        """Return the count of notes currently in the in-memory inbox.

        Returns:
            The number of notes in the inbox.
        """
        return len(self._inbox)

    def get_para_structure(self) -> ParaStructure:
        """Return the seed PARA structure.

        Returns:
            The :class:`~notes_os.sorter.models.ParaStructure` provided at
            construction time.
        """
        return self._structure

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def move_note(self, note_id: str, folder_path: FolderPath) -> None:
        """Record a move; remove from OR (on a re-move) restore to the inbox.

        Models a triage move and its undo move-back (UX-02 / B1) as a small
        state machine keyed on whether *note_id* is currently in the inbox:

        - In the inbox → MOVE-OUT: record the move, remove the note from the
          inbox, and track it in ``_moved_out``.  (Unchanged behaviour for the
          existing single-move tests: removal + recorded move.)
        - Tracked in ``_moved_out`` (already moved out) → MOVE-BACK: record the
          move, pop the note from ``_moved_out``, and RE-ADD it to the inbox so
          the undo move-back restores inbox membership.
        - Otherwise (truly unknown id) → ``raise NotesMoveError`` (unchanged).

        Limitation: a re-move always restores the note to the inbox view
        regardless of *folder_path* — sufficient for undo's move-back semantics
        (the destination is the captured source/inbox path) and the existing
        tests, which only ever move a note out once before moving it back.

        Args:
            note_id: The opaque note identifier to move.
            folder_path: Ordered tuple of folder names describing the destination.

        Raises:
            NotesMoveError: If ``note_id`` is neither in the inbox nor previously
                moved out (truly unknown id).
            FolderNotFoundError: If ``folder_path`` is not among the known
                valid destinations derived from the seed structure (or added
                via ``ensure_folder``).
        """
        if folder_path not in self._known_paths:
            raise FolderNotFoundError(folder_path)

        ids = {note.id for note in self._inbox}
        if note_id in ids:
            # Move-OUT: record, remove from inbox, track for a later move-back.
            moved = next(note for note in self._inbox if note.id == note_id)
            self.moves.append((note_id, folder_path))
            self._inbox = [note for note in self._inbox if note.id != note_id]
            self._moved_out[note_id] = moved
            return

        if note_id in self._moved_out:
            # Move-BACK (undo): record, restore inbox membership.
            restored = self._moved_out.pop(note_id)
            self.moves.append((note_id, folder_path))
            self._inbox.append(restored)
            return

        raise NotesMoveError(note_id)

    def ensure_folder(self, folder_path: FolderPath) -> None:
        """Register a folder path as known and record it — idempotently.

        Does not raise.  Calling this method twice with the same path produces
        a single entry in ``created_folders`` (idempotent, matching
        ``AppleScriptNotesRepository.ensure_folder`` semantics).

        Args:
            folder_path: Ordered tuple of folder names to register.
        """
        if folder_path not in self._known_paths:
            self._known_paths.add(folder_path)
            self.created_folders.append(folder_path)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_notes() -> list[Note]:
    """Return a representative list of Note objects for unit tests.

    Covers three edge cases:
    - An HTML body with tags and entities.
    - A title with apostrophes and Unicode characters.
    - An empty body (preview should be empty string).

    Returns:
        A list of three :class:`~notes_os.sorter.models.Note` objects.
    """
    cfg = BridgeConfig()
    return [
        Note(
            id="id1",
            title="My Project Note",
            body="<div>Buy <b>groceries</b> &amp; milk</div>",
            preview="Buy groceries & milk"[: cfg.preview_length],
        ),
        Note(
            id="id2",
            # Title uses Unicode curly apostrophe (U+2019) and accented chars — intentional test data.
            title="It’s Café Day — Notes",  # intentional: tests Unicode-title handling
            body="<p>Agenda for Monday&rsquo;s meeting</p>",
            preview="Agenda for Monday’s meeting"[
                : cfg.preview_length
            ],  # intentional: Unicode preview
        ),
        Note(
            id="id3",
            title="Empty Body Note",
            body="",
            preview="",
        ),
    ]


@pytest.fixture()
def sample_structure() -> ParaStructure:
    """Return a ParaStructure with all four PARA roots for unit tests.

    ``Projects`` has two subfolders (``Web``, ``Research``); the other roots
    have none.  Mirrors the canonical PARA order so router logic is exercised
    under realistic conditions.

    Returns:
        A :class:`~notes_os.sorter.models.ParaStructure` instance.
    """
    return ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": ("General", "Web"),
            "Areas": (),
            "Resources": (),
            "Archive": (),
        },
    )


@pytest.fixture()
def mock_repo(
    sample_notes: list[Note],
    sample_structure: ParaStructure,
) -> MockNotesRepository:
    """Return a MockNotesRepository seeded with sample notes and structure.

    Args:
        sample_notes: The ``sample_notes`` fixture.
        sample_structure: The ``sample_structure`` fixture.

    Returns:
        A :class:`MockNotesRepository` ready for use in unit tests.
    """
    return MockNotesRepository(notes=sample_notes, structure=sample_structure)
