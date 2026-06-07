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
from notes_os.sorter.models import BridgeConfig, FolderPath, Note, ParaStructure
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
        """Record a move and remove the note from the in-memory inbox.

        Validates the note id and destination path before recording the move.

        Args:
            note_id: The opaque note identifier to move.
            folder_path: Ordered tuple of folder names describing the destination.

        Raises:
            NotesMoveError: If ``note_id`` is not found in the current inbox.
            FolderNotFoundError: If ``folder_path`` is not among the known
                valid destinations derived from the seed structure (or added
                via ``ensure_folder``).
        """
        ids = {note.id for note in self._inbox}
        if note_id not in ids:
            raise NotesMoveError(note_id)
        if folder_path not in self._known_paths:
            raise FolderNotFoundError(folder_path)
        self.moves.append((note_id, folder_path))
        self._inbox = [note for note in self._inbox if note.id != note_id]

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
            title="It’s Café Day — Notes",  # noqa: RUF001  # intentional: tests Unicode-title handling
            body="<p>Agenda for Monday&rsquo;s meeting</p>",
            preview="Agenda for Monday’s meeting"[: cfg.preview_length],  # noqa: RUF001  # intentional: Unicode preview
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
