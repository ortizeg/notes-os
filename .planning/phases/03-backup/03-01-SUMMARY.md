# 03-01 SUMMARY — Backup foundation: models, manager (create/list), decorator

**Plan:** 03-01 (phase 03-backup) · **Status:** Complete · **Tasks:** 3/3

> Note: this SUMMARY was written by the orchestrator after the executor completed
> all three task commits but hit a session limit before writing it. All code is
> committed and verified green (see Verification below).

## What was built

**Commits:**
- `59193f9` feat(03-01): add BackupError, BackupConfig/Backup models, mypy override
- `f2a37b8` feat(03-01): add BackupManager.create + list (BKUP-02, BKUP-03)
- `3f4a26e` feat(03-01): add BackingUpNotesRepository decorator + unit tests (SC1, SC5)

**Files:**
- `src/notes_os/exceptions.py` — added `BackupError(NotesOSError)` (no competing root).
- `src/notes_os/backup_models.py` — **new model module.** Frozen `BaseModel`s:
  - `BackupConfig`: `backup_dir: Path` (default `~/.notes-os/backups`), `notes_db_dir: Path`
    (default `~/Library/Group Containers/group.com.apple.notes`), `max_backups: int = Field(10, ge=1)`,
    `auto_backup_on_write: bool = True`.
  - `Backup`: `timestamp: datetime`, `label: str | None = None`, `path: Path`.
- `pyproject.toml` — appended `notes_os.backup_models` to the `[[tool.mypy.overrides]]`
  `disallow_any_explicit=false` list (alongside `notes_os.sorter.models`). `backup.py` itself
  defines NO BaseModel and stays under full explicit-Any checking.
- `src/notes_os/backup.py` — `BackupManager` (create + list) and the `BackingUpNotesRepository`
  decorator. **No restore/prune yet — those are 03-02.**
- `tests/test_backup_unit.py` — 20 tests, backup.py at **100% coverage**.

## Seam for 03-02 (restore + prune)

`03-02` appends `restore()` and `prune()` to the SAME `backup.py` and SAME `tests/test_backup_unit.py`
(serialized — wave 2). Contracts already in place:

- **Constants** (module-level in `backup.py`): `NOTE_STORE_DB = "NoteStore.sqlite"` (mandatory),
  `NOTE_STORE_SIDECARS = ("NoteStore.sqlite-wal", "NoteStore.sqlite-shm")` (optional/copy-if-present),
  `NOTE_STORE_FILES = (NOTE_STORE_DB, *NOTE_STORE_SIDECARS)`, `_DIR_PREFIX = "NoteStore_"`,
  `_TS_FORMAT = "%Y-%m-%d_%H-%M-%S"`. Reuse these in restore/prune.
- **`BackupManager.__init__(self, config: BackupConfig)`** stores `self._config`. `restore`/`prune`
  read `self._config.notes_db_dir`, `self._config.backup_dir`, `self._config.max_backups`.
- **`create()`** stages into a temp sibling dir then renames into place; sidecars copied only if
  present (quiescent-DB fix — absent `-wal`/`-shm` do NOT raise). `restore()` should mirror this:
  copy each file present in the backup dir back over `notes_db_dir` (pure file op, no Notes quit).
- **`list()`** returns `list[Backup]` newest-first, label parsed from dir name. `prune()` builds on
  `list()`: keep the newest `retention` (default `max_backups`), delete the rest; support `older_than`.
- **Test helpers (reuse, do NOT redefine):** `make_db_dir(tmp_path, *, include_sidecars=True)`,
  `make_config(tmp_path, **overrides)`, `SpyBackupManager`, `make_inner(...)`.

## Verification (orchestrator-run, env binaries)

- `ruff check src tests` ✓ · `ruff format --check` ✓ (20 files) · `mypy src` ✓ (12 files)
- `pytest -m 'not integration' tests/test_backup_unit.py --cov=notes_os.backup` → **100%** (20 passed)
- Overall: `pytest -m 'not integration' --cov=notes_os` → **99.66%** (90 passed, 4 deselected), ≥80% gate green.

## Requirements

- BKUP-02 (create, labelled) ✓ · BKUP-03 (list) ✓ · BKUP-06 (BackupError aborts write) ✓ ·
  BKUP-01 (auto-backup-before-write via decorator) ✓ (SC1 + SC5 proven in unit tests).
- BKUP-04 (restore), BKUP-05 (prune) → **03-02**.
