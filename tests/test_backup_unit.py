"""Unit tests for the NotesOS backup subsystem (plan 03-01).

Covers :class:`~notes_os.backup.BackupManager` (create + list) and
:class:`~notes_os.backup.BackingUpNotesRepository` (decorator backup-before-write
and fail-aborts-write) using ``tmp_path`` fixtures and local mocks.  No
AppleScript, no real Notes database, no network.  All tests run under the
default ``-m 'not integration'`` CI gate.

Test helpers defined here for reuse by plan 03-02:
- ``make_db_dir(tmp_path, include_sidecars=True)`` — writes the three Notes DB
  files (or just the mandatory sqlite) into a tmp source directory.
- ``make_config(tmp_path, **overrides)`` — builds a ``BackupConfig`` pointing at
  tmp dirs.
- ``SpyBackupManager`` — a fake ``BackupManager`` whose ``create()`` records calls
  and can be configured to raise ``BackupError``.
- ``make_inner(notes, structure)`` — constructs a ``MockNotesRepository`` with
  minimal seed data.
"""

from __future__ import annotations

import datetime
from pathlib import Path  # noqa: TC003  # used at runtime in function bodies
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from notes_os.backup import (
    NOTE_STORE_DB,
    NOTE_STORE_FILES,
    NOTE_STORE_SIDECARS,
    BackingUpNotesRepository,
    BackupManager,
)
from notes_os.backup_models import Backup, BackupConfig
from notes_os.exceptions import BackupError
from notes_os.sorter.models import FolderPath, Note, ParaStructure
from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def make_db_dir(tmp_path: Path, *, include_sidecars: bool = True) -> Path:
    """Create a fake Notes DB directory under *tmp_path*.

    Writes ``NoteStore.sqlite`` (always) and the WAL/SHM sidecars (when
    *include_sidecars* is ``True``) with distinct byte content so copy
    verification can detect mismatches.

    Args:
        tmp_path: Pytest temporary directory fixture value.
        include_sidecars: When ``True`` (default), write the WAL and SHM sidecar
            files in addition to the mandatory sqlite file.  Set to ``False`` to
            simulate a quiescent Notes database.

    Returns:
        The ``Path`` to the newly-created source DB directory.
    """
    db_dir = tmp_path / "notes_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / NOTE_STORE_DB).write_bytes(b"sqlite-data-" + NOTE_STORE_DB.encode())
    if include_sidecars:
        for name in NOTE_STORE_SIDECARS:
            (db_dir / name).write_bytes(b"sidecar-data-" + name.encode())
    return db_dir


def make_config(tmp_path: Path, **overrides: Any) -> BackupConfig:
    """Build a ``BackupConfig`` pointing at temporary directories.

    Default ``notes_db_dir`` and ``backup_dir`` are sub-dirs of *tmp_path* so
    tests never touch the real Notes database or the user's home directory.
    Pass keyword arguments to override specific fields.

    Args:
        tmp_path: Pytest temporary directory fixture value.
        **overrides: Keyword arguments forwarded to ``BackupConfig`` constructor,
            overriding the defaults set here.

    Returns:
        A frozen :class:`~notes_os.backup_models.BackupConfig` instance.
    """
    defaults: dict[str, Any] = {
        "notes_db_dir": tmp_path / "notes_db",
        "backup_dir": tmp_path / "backups",
    }
    defaults.update(overrides)
    return BackupConfig(**defaults)


class SpyBackupManager:
    """Fake ``BackupManager`` that records ``create()`` calls.

    Not a real ``BackupManager`` — does not touch the filesystem.  Intended for
    decorator tests that need to assert call order or simulate backup failures.

    Args:
        config: The ``BackupConfig`` to store (required by the real API).
        raise_on_create: When not ``None``, ``create()`` raises this
            ``BackupError`` instead of recording a call.
    """

    def __init__(
        self,
        config: BackupConfig,
        *,
        raise_on_create: BackupError | None = None,
    ) -> None:
        """Initialise the spy.

        Args:
            config: Stored as ``self._config`` (mirrors real ``BackupManager``).
            raise_on_create: If given, ``create()`` raises this error.
        """
        self._config = config
        self._raise = raise_on_create
        self.create_calls: list[str | None] = []

    def create(self, label: str | None = None) -> Backup:
        """Record the call; optionally raise.

        Args:
            label: Forwarded label (recorded in ``create_calls``).

        Returns:
            A minimal :class:`~notes_os.backup_models.Backup` stub.

        Raises:
            BackupError: If ``raise_on_create`` was set at construction.
        """
        if self._raise is not None:
            raise self._raise
        self.create_calls.append(label)
        return Backup(
            timestamp=datetime.datetime(2026, 6, 7, 12, 0, 0),
            label=label,
            path=self._config.backup_dir / "NoteStore_2026-06-07_12-00-00",
        )


def make_inner(
    *,
    notes: list[Note] | None = None,
    structure: ParaStructure | None = None,
) -> MockNotesRepository:
    """Build a minimal ``MockNotesRepository`` for decorator tests.

    Args:
        notes: Inbox notes.  Defaults to a single minimal note.
        structure: PARA structure.  Defaults to a single Projects root.

    Returns:
        A seeded :class:`~tests.sorter.conftest.MockNotesRepository`.
    """
    if notes is None:
        notes = [Note(id="n1", title="T", body="", preview="")]
    if structure is None:
        structure = ParaStructure(
            roots=("Projects",),
            subfolders={"Projects": ()},
        )
    return MockNotesRepository(notes=notes, structure=structure)


# ---------------------------------------------------------------------------
# Test 1: create copies all three files
# ---------------------------------------------------------------------------


def test_create_copies_three_files(tmp_path: Path) -> None:
    """BackupManager.create() copies all three DB files; dir name matches format."""
    db_dir = make_db_dir(tmp_path, include_sidecars=True)
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    backup = mgr.create()

    assert backup.path.exists(), "backup dir must exist"
    assert backup.label is None

    # All three files present and byte-identical.
    for name in NOTE_STORE_FILES:
        src = db_dir / name
        dst = backup.path / name
        assert dst.exists(), f"expected {name} in backup"
        assert dst.read_bytes() == src.read_bytes(), f"{name} content mismatch"

    # Dir name matches NoteStore_{YYYY-MM-DD_HH-MM-SS} pattern.
    dir_name = backup.path.name
    assert dir_name.startswith("NoteStore_"), f"unexpected prefix: {dir_name}"
    ts_str = dir_name[len("NoteStore_") :]
    assert len(ts_str) == 19, f"timestamp width wrong: {ts_str!r}"
    # Parseable.
    datetime.datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")


# ---------------------------------------------------------------------------
# Test 2: create with label
# ---------------------------------------------------------------------------


def test_create_with_label(tmp_path: Path) -> None:
    """create(label=...) embeds the label in the dir name and Backup.label."""
    db_dir = make_db_dir(tmp_path, include_sidecars=True)
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    backup = mgr.create(label="before-archive")

    assert backup.label == "before-archive"
    assert "before-archive" in backup.path.name
    assert backup.path.name.startswith("NoteStore_")


# ---------------------------------------------------------------------------
# Test 3: create with missing mandatory file raises BackupError; no partial dir
# ---------------------------------------------------------------------------


def test_create_missing_source_raises_backuperror(tmp_path: Path) -> None:
    """Missing NoteStore.sqlite raises BackupError; no partial backup dir survives."""
    db_dir = tmp_path / "empty_db"
    db_dir.mkdir()
    # Do NOT create NoteStore.sqlite.
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    with pytest.raises(BackupError, match="missing mandatory"):
        mgr.create()

    # No partial backup directory should remain visible to list().
    assert mgr.list() == [], "list() must return empty after failed create"
    # Ensure backup_dir has no NoteStore_* dirs (staging cleanup verified).
    backup_dir = cfg.backup_dir
    if backup_dir.exists():
        assert not list(backup_dir.glob("NoteStore_*")), "no partial dir should remain"


# ---------------------------------------------------------------------------
# Test 3b: create succeeds with only NoteStore.sqlite (quiescent DB — no sidecars)
# ---------------------------------------------------------------------------


def test_create_succeeds_without_sidecars(tmp_path: Path) -> None:
    """create() succeeds when only NoteStore.sqlite is present (no WAL/SHM)."""
    db_dir = make_db_dir(tmp_path, include_sidecars=False)
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    backup = mgr.create()

    assert backup.path.exists()
    assert (backup.path / NOTE_STORE_DB).exists(), "sqlite must be backed up"
    # Sidecar files should NOT be present (they were absent in source).
    for name in NOTE_STORE_SIDECARS:
        assert not (backup.path / name).exists(), f"absent sidecar {name} must not appear"


# ---------------------------------------------------------------------------
# Test 4: create raises BackupError on OSError during copy
# ---------------------------------------------------------------------------


def test_create_copy_error_raises_backuperror(tmp_path: Path) -> None:
    """OSError during file copy raises BackupError (chained) and leaves no partial dir."""
    db_dir = make_db_dir(tmp_path, include_sidecars=True)
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    with (
        patch("shutil.copy2", side_effect=OSError("disk full")),
        pytest.raises(BackupError) as exc_info,
    ):
        mgr.create()

    # BackupError must chain the original OSError.
    assert exc_info.value.__cause__ is not None
    assert "disk full" in str(exc_info.value.__cause__)

    # No partial dir visible to list().
    assert mgr.list() == []


# ---------------------------------------------------------------------------
# Test 5: list returns backups newest-first with correct labels
# ---------------------------------------------------------------------------


def test_list_newest_first_and_labels(tmp_path: Path) -> None:
    """list() returns Backup records newest-first with parsed timestamps + labels."""
    db_dir = make_db_dir(tmp_path, include_sidecars=False)
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    b1 = mgr.create()
    b2 = mgr.create(label="release")
    b3 = mgr.create(label="hotfix")

    lst = mgr.list()
    assert len(lst) == 3

    # Sorted newest-first.
    assert lst[0].timestamp >= lst[1].timestamp >= lst[2].timestamp

    # Labels present where set.
    labels = {b.label for b in lst}
    assert "release" in labels
    assert "hotfix" in labels
    assert None in labels

    # Paths match the actual dirs on disk.
    paths = {b.path for b in lst}
    assert b1.path in paths
    assert b2.path in paths
    assert b3.path in paths


# ---------------------------------------------------------------------------
# Test 6a: list on missing/empty backup_dir returns []
# ---------------------------------------------------------------------------


def test_list_empty_dir_returns_empty(tmp_path: Path) -> None:
    """list() returns [] when backup_dir does not exist."""
    cfg = BackupConfig(
        notes_db_dir=tmp_path / "db",
        backup_dir=tmp_path / "nonexistent",
    )
    mgr = BackupManager(cfg)
    assert mgr.list() == []


# ---------------------------------------------------------------------------
# Test 6b: list skips unparseable stray directories
# ---------------------------------------------------------------------------


def test_list_skips_unparseable_dir(tmp_path: Path) -> None:
    """list() skips directories with unparseable names and does not crash."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # Create a stray NoteStore_* directory with a bad timestamp.
    (backup_dir / "NoteStore_not-a-timestamp").mkdir()
    # Also a non-NoteStore dir (should be ignored entirely).
    (backup_dir / "some-other-dir").mkdir()

    db_dir = make_db_dir(tmp_path, include_sidecars=False)
    cfg = BackupConfig(notes_db_dir=db_dir, backup_dir=backup_dir)
    mgr = BackupManager(cfg)

    # Should complete without raising; stray dirs produce warnings but no crash.
    result = mgr.list()
    # The unparseable "NoteStore_not-a-timestamp" dir has no parseable ts → skipped.
    assert result == []


# ---------------------------------------------------------------------------
# Test 7: decorator backs up before move (SC1)
# ---------------------------------------------------------------------------


def test_decorator_backs_up_before_move(tmp_path: Path) -> None:
    """BackingUpNotesRepository.move_note() calls create() BEFORE inner.move_note (SC1)."""
    cfg = make_config(tmp_path)
    inner = make_inner()
    # The note id "n1" is in the inner repo; move to known folder.
    spy = SpyBackupManager(cfg)
    call_order: list[str] = []

    # Patch spy.create to record ordering
    original_create = spy.create

    def recording_create(label: str | None = None) -> Backup:
        call_order.append("backup")
        return original_create(label)

    spy.create = recording_create  # type: ignore[method-assign]

    # Patch inner.move_note to record ordering.
    original_move = inner.move_note

    def recording_move(note_id: str, folder_path: FolderPath) -> None:
        call_order.append("move")
        original_move(note_id, folder_path)

    inner.move_note = recording_move  # type: ignore[method-assign]

    repo = BackingUpNotesRepository(inner, spy, cfg)
    repo.move_note("n1", ("Projects",))

    assert call_order == ["backup", "move"], f"expected backup-before-move, got {call_order}"
    assert len(spy.create_calls) == 1


# ---------------------------------------------------------------------------
# Test 8: read methods trigger zero create() calls
# ---------------------------------------------------------------------------


def test_decorator_read_methods_no_backup(tmp_path: Path) -> None:
    """get_inbox_notes() and get_para_structure() trigger zero create() calls."""
    cfg = make_config(tmp_path)
    inner = make_inner()
    spy = SpyBackupManager(cfg)
    repo = BackingUpNotesRepository(inner, spy, cfg)

    _ = repo.get_inbox_notes()
    _ = repo.get_para_structure()

    assert spy.create_calls == [], "read methods must not trigger backup"


# ---------------------------------------------------------------------------
# Test 9: backup failure aborts move (SC5)
# ---------------------------------------------------------------------------


def test_decorator_backup_failure_aborts_move(tmp_path: Path) -> None:
    """BackupError from create() propagates; inner.move_note is NEVER called (SC5)."""
    cfg = make_config(tmp_path)
    inner = make_inner()
    err = BackupError("disk full")
    spy = SpyBackupManager(cfg, raise_on_create=err)
    repo = BackingUpNotesRepository(inner, spy, cfg)

    with pytest.raises(BackupError):
        repo.move_note("n1", ("Projects",))

    # Inner repository must NOT have been called.
    assert inner.moves == [], f"inner.moves must be empty after backup failure, got {inner.moves}"


def test_decorator_backup_failure_aborts_ensure_folder(tmp_path: Path) -> None:
    """BackupError from create() propagates; inner.ensure_folder is NEVER called."""
    cfg = make_config(tmp_path)
    inner = make_inner()
    err = BackupError("disk full")
    spy = SpyBackupManager(cfg, raise_on_create=err)
    repo = BackingUpNotesRepository(inner, spy, cfg)

    with pytest.raises(BackupError):
        repo.ensure_folder(("Projects", "New"))

    assert inner.created_folders == [], "inner must not be called after backup failure"


# ---------------------------------------------------------------------------
# Test 10: auto_backup_on_write=False skips backup but still delegates
# ---------------------------------------------------------------------------


def test_decorator_auto_backup_disabled(tmp_path: Path) -> None:
    """auto_backup_on_write=False: no create() call but inner write still happens."""
    cfg = make_config(tmp_path, auto_backup_on_write=False)
    inner = make_inner()
    spy = SpyBackupManager(cfg)
    repo = BackingUpNotesRepository(inner, spy, cfg)

    repo.move_note("n1", ("Projects",))

    assert spy.create_calls == [], "no backup when auto_backup_on_write=False"
    assert len(inner.moves) == 1, "inner.move_note must still be called"


# ---------------------------------------------------------------------------
# Test: isinstance check against NotesRepositoryProtocol
# ---------------------------------------------------------------------------


def test_backing_up_repo_is_protocol(tmp_path: Path) -> None:
    """BackingUpNotesRepository is structural-subtype of NotesRepositoryProtocol."""
    from notes_os.sorter.notes import NotesRepositoryProtocol

    cfg = make_config(tmp_path)
    inner = make_inner()
    spy = SpyBackupManager(cfg)
    repo = BackingUpNotesRepository(inner, spy, cfg)

    assert isinstance(repo, NotesRepositoryProtocol)


# ---------------------------------------------------------------------------
# Test: BackupConfig frozen (no mutation)
# ---------------------------------------------------------------------------


def test_backup_config_is_frozen() -> None:
    """BackupConfig raises ValidationError on attribute mutation."""
    from pydantic import ValidationError

    cfg = BackupConfig()
    with pytest.raises((ValidationError, TypeError)):
        cfg.max_backups = 99  # type: ignore[misc]


def test_backup_config_max_backups_ge_1() -> None:
    """max_backups must be >= 1; 0 raises ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        BackupConfig(max_backups=0)


# ---------------------------------------------------------------------------
# Test: SpyBackupManager create_calls cleared (sanity check for test isolation)
# ---------------------------------------------------------------------------


def test_spy_backup_manager_records_labels(tmp_path: Path) -> None:
    """SpyBackupManager records the label passed to create()."""
    cfg = make_config(tmp_path)
    spy = SpyBackupManager(cfg)
    spy.create(label="test-label")
    spy.create()
    assert spy.create_calls == ["test-label", None]


# ---------------------------------------------------------------------------
# Test: MagicMock usage (alternative spy for backup ordering)
# ---------------------------------------------------------------------------


def test_decorator_ensure_folder_backs_up_first(tmp_path: Path) -> None:
    """ensure_folder() calls backup BEFORE inner.ensure_folder."""
    cfg = make_config(tmp_path)
    inner = make_inner()
    call_order: list[str] = []

    mock_mgr = MagicMock(spec=BackupManager)
    mock_mgr._config = cfg

    def recording_backup_create(label: str | None = None) -> Backup:
        call_order.append("backup")
        return Backup(
            timestamp=datetime.datetime(2026, 6, 7, 0, 0, 0),
            path=tmp_path / "NoteStore_2026-06-07_00-00-00",
        )

    mock_mgr.create.side_effect = recording_backup_create

    original_ensure = inner.ensure_folder

    def recording_ensure(folder_path: FolderPath) -> None:
        call_order.append("ensure")
        original_ensure(folder_path)

    inner.ensure_folder = recording_ensure  # type: ignore[method-assign]

    repo = BackingUpNotesRepository(inner, mock_mgr, cfg)
    repo.ensure_folder(("Projects", "NewSub"))

    assert call_order == ["backup", "ensure"]


# ---------------------------------------------------------------------------
# Coverage gap-fillers
# ---------------------------------------------------------------------------


def test_create_label_with_path_separator_raises(tmp_path: Path) -> None:
    """_dir_name rejects labels containing '/' (T-03-01 path-traversal mitigation)."""
    db_dir = make_db_dir(tmp_path, include_sidecars=False)
    cfg = make_config(tmp_path, notes_db_dir=db_dir)
    mgr = BackupManager(cfg)

    with pytest.raises(BackupError, match="path separators"):
        mgr.create(label="../../etc/evil")


def test_list_skips_non_directory_entries(tmp_path: Path) -> None:
    """list() skips non-directory entries in backup_dir without crashing."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # A file (not a dir) starting with NoteStore_ — should be skipped (is_dir check).
    (backup_dir / "NoteStore_not-a-dir.txt").write_bytes(b"")

    db_dir = make_db_dir(tmp_path, include_sidecars=False)
    cfg = BackupConfig(notes_db_dir=db_dir, backup_dir=backup_dir)
    mgr = BackupManager(cfg)

    result = mgr.list()
    assert result == []
