"""Shared exception hierarchy for NotesOS.

All project-specific exceptions extend ``NotesOSError`` so callers can catch
the entire NotesOS surface with a single ``except NotesOSError`` clause.
Phase 2+ modules add domain-specific subclasses (e.g. ``NotesError``,
``BackupError``) that inherit from this root.
"""

from __future__ import annotations


class NotesOSError(Exception):
    """Root exception for all NotesOS errors.

    Raise this class directly only for generic, uncategorized failures.
    Prefer a domain-specific subclass defined in the relevant module.
    """


class NotesError(NotesOSError):
    """Raised for any AppleScript/osascript failure at the bridge boundary.

    This is the primary exception type for the Apple Notes bridge.  Callers
    that need to handle bridge failures without distinguishing between specific
    error kinds should catch ``NotesError``; callers that want to handle
    specific conditions (missing folder, missing note) should catch the
    appropriate subclass.

    All bridge subclasses (``FolderNotFoundError``, ``NotesMoveError``) inherit
    from this class, so ``except NotesError`` catches all bridge exceptions.
    ``except NotesOSError`` catches all NotesOS-wide exceptions including this
    class.
    """


class FolderNotFoundError(NotesError):
    """Raised when the target folder path does not exist in Apple Notes.

    Raised by ``move_note`` when the destination ``FolderPath`` cannot be
    resolved in the Notes folder hierarchy.  Callers should call
    ``ensure_folder`` to create the path before retrying, or present the error
    to the user so the PARA structure can be corrected.

    Args:
        folder_path: The ``FolderPath`` tuple that could not be resolved.
    """


class NotesMoveError(NotesError):
    """Raised when a note cannot be found or a move operation is rejected.

    Raised by ``move_note`` when the given ``note_id`` is not found in Apple
    Notes, or when osascript rejects the move for any note-specific reason
    (e.g. the note has been deleted since it was fetched).

    Args:
        note_id: The opaque Apple Notes identifier that could not be located.
    """


class BackupError(NotesOSError):
    """Raised when a backup operation fails — creation, restore, or prune.

    A ``BackupError`` raised before a write ABORTS that write (BKUP-06).  The
    full NotesOS exception surface is catchable with a single
    ``except NotesOSError`` clause because this class inherits from
    :class:`NotesOSError`.

    Raised by :class:`~notes_os.backup.BackupManager` when:
    - The mandatory ``NoteStore.sqlite`` is absent from the source directory.
    - A file-copy or directory operation raises an ``OSError``.
    - A restore or prune operation fails (Phase 03-02).
    """
