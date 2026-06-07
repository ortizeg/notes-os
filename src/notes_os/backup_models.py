"""Frozen Pydantic V2 data models for the NotesOS backup subsystem.

Defines ``BackupConfig`` (runtime configuration for the backup manager) and
``Backup`` (an immutable record describing a single completed backup).  Both
models are frozen ``BaseModel`` subclasses — immutable after construction —
mirroring the frozen-model pattern used throughout NotesOS.

Separation from ``backup.py`` is intentional: Pydantic ``BaseModel`` subclasses
inherit explicit ``Any`` from the BaseModel API (``__init__(**data: Any)``,
``model_validate(obj: Any)``), which trips mypy's ``disallow_any_explicit`` rule.
Keeping models in this dedicated module means ONLY this module needs the
``disallow_any_explicit = false`` mypy override; ``backup.py`` itself stays
under full explicit-Any checking.
"""

from __future__ import annotations

from datetime import (
    datetime,  # noqa: TC003  # Pydantic V2 resolves field types at runtime via get_type_hints
)
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


_DEFAULT_NOTES_DB_DIR: Path = Path.home() / "Library" / "Group Containers" / "group.com.apple.notes"
"""Default source directory for the Apple Notes SQLite database files.

Resolves to ``~/Library/Group Containers/group.com.apple.notes/``.  Overridden
in tests by injecting a ``BackupConfig`` with a ``notes_db_dir`` pointing at a
temporary directory.
"""

_DEFAULT_BACKUP_DIR: Path = Path.home() / ".notes-os" / "backups"
"""Default destination directory for all backup snapshots.

Resolves to ``~/.notes-os/backups/``.  Created on first backup if absent.
Overridden in tests by injecting a ``BackupConfig`` with a ``backup_dir``
pointing at a temporary directory.
"""


class BackupConfig(BaseModel):
    """Runtime configuration for :class:`~notes_os.backup.BackupManager`.

    All paths are config-driven so tests can redirect I/O to temporary
    directories without touching the real Notes database or the user's home
    directory.

    Attributes:
        backup_dir: Directory where timestamped backup snapshots are stored.
            Created on first backup if it does not exist.
            Defaults to ``~/.notes-os/backups/``.
        notes_db_dir: Directory containing the live Apple Notes SQLite files
            (``NoteStore.sqlite`` and optional ``-wal``/``-shm`` sidecars).
            Defaults to
            ``~/Library/Group Containers/group.com.apple.notes/``.
        max_backups: Maximum number of backup snapshots to retain.  Oldest
            backups are pruned when this limit is exceeded (pruning implemented
            in plan 03-02).  Must be at least 1.  Defaults to ``10``.
        auto_backup_on_write: When ``True`` (the default), the
            :class:`~notes_os.backup.BackingUpNotesRepository` decorator fires
            a backup before every write operation (``move_note``,
            ``ensure_folder``).  Set to ``False`` to disable auto-backup (not
            recommended for production use).
    """

    model_config = ConfigDict(frozen=True)

    backup_dir: Path = Field(default_factory=lambda: _DEFAULT_BACKUP_DIR)
    notes_db_dir: Path = Field(default_factory=lambda: _DEFAULT_NOTES_DB_DIR)
    max_backups: int = Field(default=10, ge=1)
    auto_backup_on_write: bool = True


class Backup(BaseModel):
    """An existing backup directory returned by ``create()`` or discovered by ``list()``.

    Each ``Backup`` record is an immutable snapshot of a single timestamped
    backup created by :class:`~notes_os.backup.BackupManager`.

    Attributes:
        timestamp: The ``datetime`` at which the backup was created, parsed
            from (or used to generate) the backup directory name.
        label: An optional human-readable label appended to the directory name
            (e.g. ``"before-archive"``).  ``None`` when no label was given.
        path: Absolute path to the backup directory on the filesystem.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    label: str | None = None
    path: Path

    @property
    def dir_name(self) -> str:
        """The name of the backup directory (last path component).

        Returns:
            The directory name, e.g. ``"NoteStore_2026-06-07_12-00-00"`` or
            ``"NoteStore_2026-06-07_12-00-00_before-archive"``.
        """
        return self.path.name
