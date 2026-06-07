"""macOS-only integration tests for the BackupManager full lifecycle.

All tests in this module are marked ``@pytest.mark.integration`` and are excluded
from CI via pytest's ``-m 'not integration'`` addopts setting.  Run them locally
on macOS to validate the create → list → restore → prune lifecycle against a
TEMP fake NoteStore source directory.

These tests NEVER touch the real Apple Notes database.  Every path is scoped to
pytest's ``tmp_path`` fixture, and the integration test explicitly asserts that
``notes_db_dir`` is a subdirectory of ``tmp_path`` as a safety guard (T-03-06).
"""

from __future__ import annotations

import sys

import pytest

from notes_os.backup import NOTE_STORE_DB, NOTE_STORE_FILES, NOTE_STORE_SIDECARS, BackupManager
from notes_os.backup_models import BackupConfig


# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

if sys.platform != "darwin":
    pytest.skip(
        "Backup integration tests require macOS",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Integration lifecycle test
# ---------------------------------------------------------------------------


class TestBackupManagerLifecycle:
    """Integration: create → list → restore → prune against a TEMP fake NoteStore."""

    def test_full_lifecycle(self, tmp_path: object) -> None:
        """Drive the full backup lifecycle against a temp DB — real Notes never touched.

        Steps:
            1. Build a fake NoteStore source dir under ``tmp_path``.
            2. Assert that ``notes_db_dir`` is under ``tmp_path`` (safety guard).
            3. ``create(label)`` — assert backup dir exists and files match.
            4. ``list()`` — assert the created backup appears.
            5. Mutate the source, then ``restore('latest')`` — assert source reverted.
            6. Create two more backups, then ``prune(retention=2)`` — assert exactly
               2 backups remain.

        Args:
            tmp_path: Pytest temporary directory, scoped to this test.
        """
        from pathlib import Path

        assert isinstance(tmp_path, Path)

        # --- 1. Build fake NoteStore source ---
        db_dir = tmp_path / "fake_notes_db"
        db_dir.mkdir()
        (db_dir / NOTE_STORE_DB).write_bytes(b"v1-sqlite")
        for sidecar in NOTE_STORE_SIDECARS:
            (db_dir / sidecar).write_bytes(b"v1-sidecar-" + sidecar.encode())

        backup_dir = tmp_path / "backups"
        cfg = BackupConfig(notes_db_dir=db_dir, backup_dir=backup_dir)
        mgr = BackupManager(cfg)

        # --- 2. Safety guard: notes_db_dir must be under tmp_path ---
        assert str(db_dir).startswith(str(tmp_path)), (
            f"SAFETY: notes_db_dir {db_dir} is NOT under tmp_path {tmp_path} — "
            "real Notes DB may be targeted"
        )
        assert str(backup_dir).startswith(str(tmp_path)), (
            f"SAFETY: backup_dir {backup_dir} is NOT under tmp_path {tmp_path}"
        )

        # --- 3. create() ---
        first_backup = mgr.create(label="integration-test")
        assert first_backup.path.exists(), "backup directory must exist after create()"
        assert first_backup.label == "integration-test"
        for name in NOTE_STORE_FILES:
            assert (first_backup.path / name).exists(), f"file {name} missing from backup"
            assert (first_backup.path / name).read_bytes() == (db_dir / name).read_bytes(), (
                f"{name} content mismatch after create()"
            )

        # --- 4. list() ---
        backups = mgr.list()
        assert len(backups) == 1, f"expected 1 backup, got {len(backups)}"
        assert backups[0].path == first_backup.path

        # --- 5. Mutate source, then restore('latest') ---
        (db_dir / NOTE_STORE_DB).write_bytes(b"v2-sqlite")
        for sidecar in NOTE_STORE_SIDECARS:
            (db_dir / sidecar).write_bytes(b"v2-sidecar")

        restored = mgr.restore("latest")
        assert restored.path == first_backup.path
        # Source must match backup (v1 bytes restored).
        assert (db_dir / NOTE_STORE_DB).read_bytes() == b"v1-sqlite", (
            "restore() did not revert NoteStore.sqlite"
        )
        for sidecar in NOTE_STORE_SIDECARS:
            expected = b"v1-sidecar-" + sidecar.encode()
            assert (db_dir / sidecar).read_bytes() == expected, (
                f"restore() did not revert {sidecar}"
            )

        # --- 6. prune(retention=2) after creating more backups ---
        mgr.create(label="second")
        mgr.create(label="third")

        all_backups = mgr.list()
        assert len(all_backups) == 3, f"expected 3 backups before prune, got {len(all_backups)}"

        deleted = mgr.prune(retention=2)
        remaining = mgr.list()

        assert len(remaining) == 2, f"expected 2 backups after prune, got {len(remaining)}"
        assert len(deleted) == 1, f"expected 1 deleted, got {len(deleted)}"

        # The 2 newest are kept; the oldest (first_backup) is deleted.
        kept_paths = {b.path for b in remaining}
        assert first_backup.path not in kept_paths, (
            "oldest backup should have been pruned but is still present"
        )
