---
phase: 03-backup
plan: 02
subsystem: backup
tags: [backup, restore, prune, shutil, pathlib, sqlite, apple-notes]

# Dependency graph
requires:
  - phase: 03-01
    provides: BackupManager constructor/create/list, NOTE_STORE_FILES constants, BackupConfig/Backup models, BackupError, test helpers (make_db_dir/make_config/SpyBackupManager/make_inner)
provides:
  - BackupManager.restore(timestamp_or_'latest') — pure file-copy back over notes_db_dir
  - BackupManager.prune(retention, older_than) — keeps N newest, deletes rest via shutil.rmtree
  - 13 unit tests covering all restore/prune branches; make_backup_dirs() deterministic test helper
  - tests/test_backup_integration.py — full lifecycle integration test against tmp_path only
affects: [04-tui, 05-cli, any phase that wires BackupManager into the write path]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "restore() is a pure file operation with quit-Notes/reopen-Notes as user responsibility (documented in docstring)"
    - "prune() applies older_than filter first, then retention count on the remainder (documented combination rule)"
    - "prune() uses best-effort rmtree: OSError is logged as warning but does not abort remaining deletions"
    - "builtins imported in TYPE_CHECKING block to disambiguate list[] return type from self.list() method name under mypy strict"
    - "make_backup_dirs() helper builds deterministic backup dirs without real-time sleeps for fast CI"

key-files:
  created:
    - tests/test_backup_integration.py
  modified:
    - src/notes_os/backup.py
    - tests/test_backup_unit.py

key-decisions:
  - "restore() is a pure file operation; quitting and reopening Notes is the user's documented responsibility — keeps restore() unit-testable without spawning any Apple process"
  - "prune() older_than+retention combination: older_than applied first (marks backups before cutoff for deletion), then retention enforced on the remainder — older_than acts as a floor removal, retention as a ceiling on the survivors"
  - "prune() rmtree failure mode: best-effort (OSError logged as warning, prune continues) so a single stuck directory does not abort pruning of others"
  - "prune(retention<1) raises BackupError — negative or zero retention is an explicit error rather than a silent clamp"
  - "import builtins inside TYPE_CHECKING block to fix mypy false positive where self.list() method shadowed builtin list[] in return type annotation under strict disallow_any_explicit"

patterns-established:
  - "Deterministic test ordering via make_backup_dirs() — craft timestamped dirs directly instead of sleeping between create() calls"
  - "Integration test safety guard: assert notes_db_dir.startswith(str(tmp_path)) at test start to prevent accidental real-DB access"

requirements-completed: [BKUP-04, BKUP-05]

# Metrics
duration: 35min
completed: 2026-06-07
---

# Phase 03 Plan 02: Backup restore + prune Summary

**BackupManager.restore() + prune() implemented as pure stdlib file operations, backup.py at 100% coverage (33 unit tests), with a macOS integration lifecycle test against tmp_path that never touches the real Notes database.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-07T00:00:00Z
- **Completed:** 2026-06-07T00:35:00Z
- **Tasks:** 3
- **Files modified:** 3 (backup.py, test_backup_unit.py, test_backup_integration.py [new])

## Accomplishments

- `BackupManager.restore(timestamp_or_'latest')` copies the backup's three files back over `notes_db_dir`; raises `BackupError` for unknown timestamp, empty dir, or incomplete backup (any of the three canonical files missing)
- `BackupManager.prune(retention, older_than)` keeps the N newest backups and deletes the rest with `shutil.rmtree`; `older_than` applied first then retention enforced on remaining; rmtree failures best-effort logged; `retention<1` raises `BackupError`
- 13 new unit tests close `backup.py` to 100% branch coverage (up from 100% on 03-01, maintaining it); overall suite 99.71%, well above the 80% gate
- `tests/test_backup_integration.py` drives full create → list → restore → prune lifecycle against a `tmp_path`-scoped fake NoteStore with an explicit safety assertion that `notes_db_dir` is under `tmp_path`

## Task Commits

1. **Tasks 1 + 2: BackupManager.restore + prune** - `27e9fb0` (feat)
2. **Task 3: restore/prune unit tests + integration** - `4c1e25c` (test)

## Files Created/Modified

- `src/notes_os/backup.py` — added `restore()` and `prune()` methods; `import builtins` under `TYPE_CHECKING` to resolve mypy name-collision with self.list()
- `tests/test_backup_unit.py` — appended 13 restore/prune unit tests + `make_backup_dirs()` helper; updated module docstring and imports
- `tests/test_backup_integration.py` — new file; `@pytest.mark.integration` full-lifecycle test, Darwin-only, tmp_path-scoped, real Notes DB never touched

## Decisions Made

- **restore() design:** Pure file operation. The user must quit Notes before and reopen after — documented explicitly in the docstring. No osascript/process management in v1 (keeps the method fully unit-testable against temp dirs).
- **prune() older_than + retention combination rule:** `older_than` is applied as Pass 1 (remove anything before the cutoff from the candidate pool), then `retention` is enforced as Pass 2 on the survivors (drop everything beyond the N newest from what remains). Documented in the method docstring and module-level design note.
- **prune() rmtree failure mode:** Best-effort. `OSError` from `shutil.rmtree` is logged at `WARNING` level; the failed entry is still included in the returned deleted list and pruning continues. This ensures a single locked/busy directory does not abort pruning of other backups.
- **prune(retention=0) handling:** Raises `BackupError("retention must be >= 1")`. An explicit error is clearer than a silent clamp and matches the `BackupConfig.max_backups ge=1` field constraint.
- **mypy name-collision fix:** `builtins` imported inside the `TYPE_CHECKING` block (ruff TC003-compliant) to let `prune() -> builtins.list[Backup]` resolve correctly when `self.list()` shadows the `list` builtin in mypy's class-scope name lookup.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mypy error from `list` method shadowing builtin `list` type**
- **Found during:** Task 1 verification (mypy src run)
- **Issue:** `prune() -> list[Backup]` caused `error: Function "notes_os.backup.BackupManager.list" is not valid as a type [valid-type]` because mypy resolved `list` in the return annotation to the `self.list` method rather than the builtin. The `from __future__ import annotations` defers runtime evaluation but mypy still performs semantic analysis in class scope.
- **Fix:** Added `import builtins` inside the `TYPE_CHECKING` block (satisfying ruff TC003) and changed the return type to `builtins.list[Backup]`.
- **Files modified:** `src/notes_os/backup.py`
- **Verification:** `mypy src` reports zero errors
- **Committed in:** `27e9fb0` (Task 1+2 feat commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — Bug: mypy name-collision)
**Impact on plan:** Required fix; no scope creep. The method name `list` is part of the public contract from 03-01 and cannot be renamed.

## Issues Encountered

None — all planned behavior implemented on first attempt after the mypy name-collision fix.

## Threat Mitigations Applied

| Threat | Mitigation |
|--------|-----------|
| T-03-04: restore() overwriting live DB while Notes is running | restore() documented as pure file op; user must quit Notes before and reopen after (docstring). Raises BackupError for any missing file so live DB is never left torn. |
| T-03-05: prune() deleting wrong backups | Operates on list() (newest-first), keeps N newest; retention<1 raises explicitly; SC4 test pins retention=3-of-5 → exactly 3 remain. |
| T-03-06: integration test touching real Notes DB | Test asserts notes_db_dir.startswith(str(tmp_path)); skips on non-Darwin; backup_dir also under tmp_path. |

## Coverage Results

```
Name                     Stmts   Miss  Cover   Missing
------------------------------------------------------
src/notes_os/backup.py     158      0   100%
------------------------------------------------------
backup.py (unit-only gate, --cov-fail-under=95): 100% PASSED

Overall (--cov-fail-under=80):  99.71% PASSED  (103 tests, 5 deselected)
```

## Known Stubs

None — all data flows are wired; no placeholder values, TODO comments, or disconnected components in the files touched by this plan.

## Next Phase Readiness

- Phase 03 (both plans) is complete: BackupManager API is fully implemented (create/list/restore/prune) with decorator, models, and ≥95% test coverage.
- The BackupManager is ready to be wired into the TUI (Phase 04) and CLI (Phase 05) via the `BackingUpNotesRepository` decorator.
- No blockers.

---
*Phase: 03-backup*
*Completed: 2026-06-07*

## Self-Check: PASSED

- `src/notes_os/backup.py` — FOUND (modified)
- `tests/test_backup_unit.py` — FOUND (modified)
- `tests/test_backup_integration.py` — FOUND (created)
- Commit `27e9fb0` — FOUND (feat: restore + prune)
- Commit `4c1e25c` — FOUND (test: unit + integration)
- `mypy src` → zero errors
- `ruff check src tests` → all checks passed
- `pytest --cov=notes_os.backup --cov-fail-under=95` → 100%, PASSED
- `pytest --cov=notes_os --cov-fail-under=80` → 99.71%, PASSED
