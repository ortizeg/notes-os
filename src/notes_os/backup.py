"""NotesOS backup subsystem: BackupManager and BackingUpNotesRepository.

``BackupManager`` copies the three Apple Notes SQLite database files into a
timestamped (and optionally labelled) directory under ``BackupConfig.backup_dir``.
``NoteStore.sqlite`` is mandatory — its absence raises ``BackupError``.  The WAL
and SHM sidecars (``NoteStore.sqlite-wal`` and ``NoteStore.sqlite-shm``) are
optional: Apple Notes does NOT create them on a quiescent (idle) database, so
their absence is normal and must NOT fail the backup.

``BackingUpNotesRepository`` is a decorator that wraps any
``NotesRepositoryProtocol`` implementation.  It fires a backup BEFORE every
write operation (``move_note``, ``ensure_folder``) and propagates ``BackupError``
without delegating to the inner repository — proving BKUP-06 (a failed backup
aborts the pending write) with a simple mock.  Read operations pass straight
through to the inner repository with no backup overhead.

Design note — staging-then-rename:
    ``BackupManager.create()`` copies files into a ``<dest>._staging`` sibling
    directory, then renames it atomically to ``<dest>``.  This ensures that
    ``BackupManager.list()`` never surfaces a partial backup: an incomplete copy
    exists only under the staging name, which is not matched by the
    ``NoteStore_*`` prefix.  Any error during staging removes the staging dir and
    raises ``BackupError``; the destination dir is left absent.

Design note — restore:
    ``BackupManager.restore()`` is a PURE FILE OPERATION.  It copies the backup's
    files back over ``notes_db_dir`` but does NOT quit or relaunch Apple Notes.
    Quitting Notes before restore and reopening after is the USER'S responsibility
    (see :meth:`~BackupManager.restore` docstring).  This design keeps restore
    fully unit-testable against temp directories without spawning any Apple process.

Design note — prune (older_than + retention):
    ``BackupManager.prune()`` applies ``older_than`` first (marking any backup
    whose timestamp predates the cutoff for deletion), then enforces the retention
    count on the *remaining* (not-yet-marked-for-deletion) backups — deleting
    anything beyond the ``keep`` newest among those.  OSError from ``shutil.rmtree``
    is logged as a warning (best-effort delete) so a single stuck directory does
    not abort pruning of other backups.

No Pydantic ``BaseModel`` is defined in this module (models live in
``backup_models.py``) so this file stays under mypy's full
``disallow_any_explicit`` checking.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from typing import TYPE_CHECKING

from notes_os.backup_models import Backup, BackupConfig
from notes_os.exceptions import BackupError


if TYPE_CHECKING:
    import builtins

    from notes_os.sorter.models import FolderPath, Note, NoteRef, ParaStructure
    from notes_os.sorter.notes import NotesRepositoryProtocol


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Notes DB file constants
# ---------------------------------------------------------------------------

NOTE_STORE_DB: str = "NoteStore.sqlite"
"""The primary (mandatory) Apple Notes SQLite database file.

This file MUST be present in ``BackupConfig.notes_db_dir`` for
``BackupManager.create()`` to succeed.  Its absence raises ``BackupError``.
"""

NOTE_STORE_SIDECARS: tuple[str, ...] = (
    "NoteStore.sqlite-wal",
    "NoteStore.sqlite-shm",
)
"""Optional WAL/SHM sidecar files that accompany the Notes SQLite database.

Apple Notes creates these only when the database is actively being written
(write-ahead logging mode).  On a quiescent (idle) database they are absent —
their absence is NOT an error and must NOT fail the backup.  The backup manager
copies them when present and silently skips them when absent.
"""

NOTE_STORE_FILES: tuple[str, ...] = (NOTE_STORE_DB, *NOTE_STORE_SIDECARS)
"""All three Apple Notes database files (mandatory DB + optional sidecars).

Provided as a convenience tuple for callers that need to enumerate all filenames.
See ``NOTE_STORE_DB`` and ``NOTE_STORE_SIDECARS`` for the mandatory/optional split.
"""

_DIR_PREFIX: str = "NoteStore_"
"""Directory name prefix for all backup snapshots."""

_TS_FORMAT: str = "%Y-%m-%d_%H-%M-%S"
"""strftime format for the timestamp component of backup directory names."""


# ---------------------------------------------------------------------------
# BackupManager
# ---------------------------------------------------------------------------


class BackupManager:
    """Creates and lists timestamped Apple Notes database backups.

    All I/O paths are sourced from the injected ``BackupConfig`` so tests can
    redirect operations to temporary directories.  No hardcoded home-directory
    paths appear in this class beyond the documented defaults on ``BackupConfig``.

    Restore and prune operations are implemented in plan 03-02.

    Args:
        config: Frozen configuration driving backup-dir location, source DB dir,
            retention limit, and the auto-backup flag.
    """

    def __init__(self, config: BackupConfig) -> None:
        """Store the injected configuration.

        Args:
            config: The :class:`~notes_os.backup_models.BackupConfig` instance
                driving this manager's behaviour.
        """
        self._config = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dir_name(self, ts: datetime, label: str | None) -> str:
        """Build the backup directory name from a timestamp and optional label.

        The label is sanitised before use: it is stripped of leading/trailing
        whitespace, and any forward-slash or OS path separator is rejected to
        prevent directory traversal (T-03-01 mitigation).  An empty string after
        stripping is treated as no label.

        Args:
            ts: The datetime to embed in the directory name.
            label: Optional human-readable label to append after the timestamp.
                Must not contain path separators.  ``None`` or empty → no label.

        Returns:
            A string of the form ``NoteStore_{ts}`` or
            ``NoteStore_{ts}_{label}``.

        Raises:
            BackupError: If *label* contains a path separator (``/`` or
                ``os.sep``), which would allow directory traversal.
        """
        ts_str = ts.strftime(_TS_FORMAT)
        if label is not None:
            clean = label.strip()
            if clean:
                # Reject path separators to prevent traversal (T-03-01).
                if "/" in clean or os.sep in clean:
                    msg = f"Backup label must not contain path separators; got: {label!r}"
                    raise BackupError(msg)
                return f"{_DIR_PREFIX}{ts_str}_{clean}"
        return f"{_DIR_PREFIX}{ts_str}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, label: str | None = None, *, now: datetime | None = None) -> Backup:
        """Copy the live Notes DB files into a new timestamped backup directory.

        The copy is performed into a ``<dest>._staging`` sibling directory first,
        then renamed atomically to ``<dest>`` so that :meth:`list` never surfaces
        a partial backup (T-03-02 mitigation).

        ``NoteStore.sqlite`` is mandatory — its absence raises :class:`BackupError`
        immediately.  The WAL/SHM sidecars (``NoteStore.sqlite-wal``,
        ``NoteStore.sqlite-shm``) are optional; if absent, they are silently
        skipped with a debug log rather than raising an error (Apple Notes omits
        them on a quiescent database).

        Args:
            label: Optional human-readable label appended to the directory name
                (e.g. ``"before-archive"``).  Must not contain path separators.
                Empty strings and strings that are whitespace-only are treated as
                no label.  ``None`` → no label.

        Returns:
            A :class:`~notes_os.backup_models.Backup` record whose ``path``
            points to the completed backup directory.

        Raises:
            BackupError: If ``NoteStore.sqlite`` is absent from
                ``config.notes_db_dir``, if *label* contains a path separator,
                or if any file-copy or directory operation raises an ``OSError``.
                A staging directory left from a failed copy is removed before
                raising; the final destination directory is never created.
        """
        ts = now if now is not None else datetime.now()
        clean_label: str | None = label.strip() or None if label is not None else None

        # Build the dir name — may raise BackupError for bad labels.
        dir_name = self._dir_name(ts, clean_label)
        dest = self._config.backup_dir / dir_name
        staging = self._config.backup_dir / f"{dir_name}._staging"

        # Idempotent within a single second: one logical move triggers TWO backups
        # microseconds apart (ensure_folder then move_note), which collide on the
        # second-precision dir name and would fail the staging->dest rename with
        # ENOTEMPTY. The first backup already captures the pre-operation DB state
        # (the correct rollback point for the whole move), so reuse it.
        if dest.exists():
            logger.debug("Backup for this second already exists, reusing: %s", dest)
            return Backup(timestamp=ts, label=clean_label, path=dest)

        try:
            self._config.backup_dir.mkdir(parents=True, exist_ok=True)

            # Check mandatory file before creating any dirs.
            mandatory_src = self._config.notes_db_dir / NOTE_STORE_DB
            if not mandatory_src.exists():
                msg = f"missing mandatory Notes DB file: {mandatory_src}"
                raise BackupError(msg)

            staging.mkdir(parents=True, exist_ok=True)

            # Copy mandatory file.
            shutil.copy2(mandatory_src, staging / NOTE_STORE_DB)

            # Copy optional sidecars — absent sidecars are silently skipped.
            for sidecar_name in NOTE_STORE_SIDECARS:
                sidecar_src = self._config.notes_db_dir / sidecar_name
                if sidecar_src.exists():
                    shutil.copy2(sidecar_src, staging / sidecar_name)
                else:
                    logger.debug("sidecar absent, skipping: %s", sidecar_src)

            # Atomic rename into place — list() only sees completed backups.
            staging.rename(dest)

        except BackupError:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)
            raise
        except OSError as err:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)
            msg = f"backup failed while copying Notes DB to {dest}: {err}"
            raise BackupError(msg) from err

        logger.info("Backup created: %s (%s)", dest, ts.strftime(_TS_FORMAT))
        return Backup(timestamp=ts, label=clean_label, path=dest)

    def list(self) -> list[Backup]:
        """Return existing backups, newest-first.

        Scans ``config.backup_dir`` for directories whose names match the
        ``NoteStore_*`` prefix.  Each directory name is parsed to extract the
        timestamp (first 19 characters after the prefix) and optional label
        (any remainder after the timestamp and a ``_`` separator).  Directories
        whose names cannot be parsed are skipped with a warning log rather than
        raising an error.

        Returns:
            A list of :class:`~notes_os.backup_models.Backup` records sorted by
            :attr:`~notes_os.backup_models.Backup.timestamp` descending
            (newest first).  Returns an empty list when
            ``config.backup_dir`` does not exist or contains no matching
            directories.
        """
        backup_dir = self._config.backup_dir
        if not backup_dir.exists():
            return []

        backups: list[Backup] = []
        for child in backup_dir.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if not name.startswith(_DIR_PREFIX):
                continue

            remainder = name[len(_DIR_PREFIX) :]
            # Timestamp is exactly 19 characters: "YYYY-MM-DD_HH-MM-SS"
            ts_str = remainder[:19]
            after_ts = remainder[19:]

            try:
                ts = datetime.strptime(ts_str, _TS_FORMAT)
            except ValueError:
                logger.warning(
                    "Skipping unparseable backup directory: %s",
                    child,
                )
                continue

            # Optional label follows a single underscore separator.
            label: str | None = None
            if after_ts.startswith("_") and after_ts[1:]:
                label = after_ts[1:]

            backups.append(Backup(timestamp=ts, label=label, path=child))

        # Secondary sort by directory name makes ordering deterministic when two
        # backups share a second: the dir-name timestamp has second resolution, so
        # same-second backups parse to EQUAL datetimes and a timestamp-only sort
        # leaves their relative order at the mercy of iterdir() (filesystem order).
        # Production backups are unlabelled and reuse within a second (see create()),
        # so same-second collisions only arise with distinct labels — but the
        # tie-break keeps list(), and therefore prune()/restore('latest'), total-
        # ordered and stable regardless.
        backups.sort(key=lambda b: (b.timestamp, b.path.name), reverse=True)
        return backups

    def restore(self, timestamp: str = "latest") -> Backup:
        """Copy a backup's files back over the live Notes database directory.

        **Documented restore procedure (user responsibility):**
            1. Quit Apple Notes completely before calling this method.
            2. Call ``restore()`` to replace the live DB files.
            3. Reopen Apple Notes after the method returns.

        This method is a PURE FILE OPERATION — it does NOT quit or relaunch
        Apple Notes.  Automating the quit/reopen cycle is explicitly out of
        scope for v1 to keep this method unit-testable against temp directories
        without spawning any Apple process.

        Restore copies every file that is present in the chosen backup directory
        back over ``config.notes_db_dir``, mirroring the sidecar-optional logic
        used by :meth:`create`.  A backup that is missing any of the three
        canonical filenames entirely raises :class:`BackupError` so the live
        DB is never left in a torn state (T-03-04 mitigation).

        Args:
            timestamp: Either the string ``"latest"`` (the default) to restore
                the most-recent backup, or a timestamp string in the format
                ``YYYY-MM-DD_HH-MM-SS`` that identifies a specific backup.

        Returns:
            The :class:`~notes_os.backup_models.Backup` record that was restored.

        Raises:
            BackupError: If *timestamp* is ``"latest"`` and no backups exist,
                if no backup matches the given timestamp string, if the resolved
                backup directory is missing any of the three canonical
                ``NOTE_STORE_FILES``, or if any file-copy or directory operation
                raises an ``OSError``.
        """
        backups = self.list()

        if timestamp == "latest":
            if not backups:
                msg = "no backups to restore"
                raise BackupError(msg)
            target = backups[0]
        else:
            match = next(
                (b for b in backups if b.timestamp.strftime(_TS_FORMAT) == timestamp),
                None,
            )
            if match is None:
                msg = f"no backup for timestamp {timestamp}"
                raise BackupError(msg)
            target = match

        try:
            self._config.notes_db_dir.mkdir(parents=True, exist_ok=True)
            for name in NOTE_STORE_FILES:
                src = target.path / name
                if not src.exists():
                    msg = f"incomplete backup, missing {name}"
                    raise BackupError(msg)
                shutil.copy2(src, self._config.notes_db_dir / name)
        except BackupError:
            raise
        except OSError as err:
            msg = f"restore failed while copying from {target.path}: {err}"
            raise BackupError(msg) from err

        logger.info(
            "Restored backup: %s -> %s",
            target.path,
            self._config.notes_db_dir,
        )
        return target

    def prune(
        self,
        retention: int | None = None,
        older_than: datetime | None = None,
    ) -> builtins.list[Backup]:
        """Delete old backups, keeping only the most recent ones.

        Applies ``older_than`` first, then enforces the ``retention`` count on
        the remainder.  Specifically:

        1. **older_than pass** — any backup whose timestamp is strictly earlier
           than *older_than* is marked for deletion, regardless of *retention*.
        2. **retention pass** — from the backups NOT already marked for deletion,
           keep only the *retention* newest; mark anything beyond that for
           deletion too.

        Each backup directory is removed with :func:`shutil.rmtree`.  An
        ``OSError`` from ``rmtree`` is logged as a warning (best-effort delete)
        so a single stuck directory does not abort pruning of the others.

        Args:
            retention: Number of newest backups to keep.  Defaults to
                ``config.max_backups`` when ``None``.  Must be >= 1; values < 1
                raise :class:`BackupError`.
            older_than: Optional cutoff datetime.  Backups with a timestamp
                strictly earlier than this value are deleted regardless of the
                retention count (applied before the retention pass).  ``None``
                disables the cutoff.

        Returns:
            A list of :class:`~notes_os.backup_models.Backup` records that were
            deleted (successfully or with a best-effort warning on ``OSError``).

        Raises:
            BackupError: If *retention* is less than 1.
        """
        keep = retention if retention is not None else self._config.max_backups
        if keep < 1:
            msg = f"retention must be >= 1; got {keep}"
            raise BackupError(msg)

        backups = self.list()  # newest-first

        to_delete: list[Backup] = []
        remaining: list[Backup] = []

        # Pass 1: older_than filter.
        if older_than is not None:
            for b in backups:
                if b.timestamp < older_than:
                    to_delete.append(b)
                else:
                    remaining.append(b)
        else:
            remaining = list(backups)

        # Pass 2: retention on what is left (already newest-first).
        if len(remaining) > keep:
            to_delete.extend(remaining[keep:])

        deleted: list[Backup] = []
        for b in to_delete:
            try:
                shutil.rmtree(b.path)
                deleted.append(b)
            except OSError:
                logger.warning(
                    "prune: failed to remove backup dir %s (best-effort, continuing)",
                    b.path,
                )
                deleted.append(b)  # still tracked as "intended for deletion"

        logger.info("Pruned %d backup(s)", len(deleted))
        return deleted


# ---------------------------------------------------------------------------
# BackingUpNotesRepository decorator
# ---------------------------------------------------------------------------


class BackingUpNotesRepository:
    """Decorator that fires a backup before every write to Apple Notes.

    Implements :class:`~notes_os.sorter.notes.NotesRepositoryProtocol` by
    wrapping an inner ``NotesRepositoryProtocol`` implementation with a
    ``BackupManager``.  On every write (``move_note``, ``ensure_folder``) it
    calls :meth:`BackupManager.create` first and propagates any
    :class:`~notes_os.exceptions.BackupError` WITHOUT delegating to the inner
    repository — so a failed backup ABORTS the write (BKUP-06, proven by SC5).
    Read operations (``get_inbox_notes``, ``get_para_structure``) pass straight
    through with no backup overhead.

    When ``config.auto_backup_on_write`` is ``False``, write operations skip the
    backup and delegate directly to the inner repository.  This flag exists
    primarily for testing and explicit opt-out scenarios; leaving it at the
    default of ``True`` is strongly recommended.

    Args:
        inner: The inner ``NotesRepositoryProtocol`` implementation to wrap.
        backup_manager: The ``BackupManager`` used to create backups.
        config: The ``BackupConfig`` from which ``auto_backup_on_write`` is read.
            Note that ``backup_manager`` already holds its own config; the
            ``config`` parameter here is kept explicit so the decorator's gate
            flag is readable without reaching into the manager's private state.
    """

    def __init__(
        self,
        inner: NotesRepositoryProtocol,
        backup_manager: BackupManager,
        config: BackupConfig,
    ) -> None:
        """Store the injected dependencies.

        Args:
            inner: Inner repository implementation.
            backup_manager: Manager used to create pre-write backups.
            config: Configuration read for the ``auto_backup_on_write`` flag.
        """
        self._inner = inner
        self._backup_manager = backup_manager
        self._config = config

    # ------------------------------------------------------------------
    # Read operations — pass straight through; no backup.
    # ------------------------------------------------------------------

    def get_inbox_notes(self) -> list[Note]:
        """Return inbox notes from the inner repository with no backup.

        Returns:
            The result of the inner repository's ``get_inbox_notes()``.
        """
        return self._inner.get_inbox_notes()

    def get_para_structure(self) -> ParaStructure:
        """Return PARA structure from the inner repository with no backup.

        Returns:
            The result of the inner repository's ``get_para_structure()``.
        """
        return self._inner.get_para_structure()

    def get_inbox_note_refs(self) -> list[NoteRef]:
        """Return inbox note refs from the inner repository with no backup.

        Returns:
            The result of the inner repository's ``get_inbox_note_refs()``.
        """
        return self._inner.get_inbox_note_refs()

    def get_note(self, note_id: str) -> Note:
        """Return a single note's full content from the inner repository with no backup.

        Args:
            note_id: The opaque Apple Notes note identifier.

        Returns:
            The result of the inner repository's ``get_note(note_id)``.
        """
        return self._inner.get_note(note_id)

    def get_inbox_note_bodies(self, offset: int, count: int) -> list[Note]:
        """Return a page of inbox note bodies from the inner repository with no backup.

        This is a pure read operation — it NEVER triggers a backup, mirroring
        the other read pass-throughs in this section.

        Args:
            offset: 0-based start index into the inbox notes in folder order.
            count: Number of notes to fetch starting at *offset*.

        Returns:
            The result of the inner repository's
            ``get_inbox_note_bodies(offset, count)``.
        """
        return self._inner.get_inbox_note_bodies(offset, count)

    def count_inbox_notes(self) -> int:
        """Return inbox note count from the inner repository with no backup.

        Returns:
            The result of the inner repository's ``count_inbox_notes()``.
        """
        return self._inner.count_inbox_notes()

    # ------------------------------------------------------------------
    # Write operations — backup first, then delegate.
    # ------------------------------------------------------------------

    def move_note(self, note_id: str, folder_path: FolderPath) -> None:
        """Back up the Notes DB then move *note_id* to *folder_path*.

        When ``config.auto_backup_on_write`` is ``True`` (the default), calls
        :meth:`BackupManager.create` BEFORE delegating to the inner repository.
        Any :class:`~notes_os.exceptions.BackupError` raised by the backup is
        propagated immediately — the inner ``move_note`` is NEVER reached,
        proving BKUP-06 (backup failure aborts the write).

        Args:
            note_id: The opaque Apple Notes note identifier.
            folder_path: Ordered tuple of folder names describing the
                destination.

        Raises:
            BackupError: If the backup fails and ``auto_backup_on_write`` is
                ``True``.  The inner repository is not called.
            Any exception raised by the inner ``move_note`` (e.g.
                :class:`~notes_os.exceptions.NotesMoveError`,
                :class:`~notes_os.exceptions.FolderNotFoundError`) propagates
                unchanged when the backup succeeds.
        """
        if self._config.auto_backup_on_write:
            self._backup_manager.create()  # BackupError propagates — write aborted
        self._inner.move_note(note_id, folder_path)

    def ensure_folder(self, folder_path: FolderPath) -> None:
        """Back up the Notes DB then ensure *folder_path* exists.

        Same backup-first semantics as :meth:`move_note`.  When the backup
        fails, the inner ``ensure_folder`` is NEVER called.

        Args:
            folder_path: Ordered tuple of folder names to create if absent.

        Raises:
            BackupError: If the backup fails and ``auto_backup_on_write`` is
                ``True``.  The inner repository is not called.
            Any exception raised by the inner ``ensure_folder`` propagates
                unchanged when the backup succeeds.
        """
        if self._config.auto_backup_on_write:
            self._backup_manager.create()  # BackupError propagates — write aborted
        self._inner.ensure_folder(folder_path)
