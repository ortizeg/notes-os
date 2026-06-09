---
phase: 12-backup-cadence
plan: 01
subsystem: infra
tags: [backup, decorator, protocol, textual, applescript, performance]

# Dependency graph
requires:
  - phase: 03-backup
    provides: BackingUpNotesRepository decorator + BackupManager (per-write backup cadence)
  - phase: 06-tui-sort
    provides: SortScreen + NotesOSApp DI seam (self.app.repo is the backup-wrapped repo)
  - phase: 10-paged-preview
    provides: SortScreen._apply_inbox_refs session-start seam (current TUI entry point)
provides:
  - "Per-session backup cadence: one BackupManager.create() per triage session instead of one per write"
  - "BackingUpNotesRepository._session_backed_up latch + begin_session() re-arm method"
  - "BackupResettable @runtime_checkable Protocol (backup-decorator session-reset seam)"
  - "begin_session() wired at both session entry points (CLI SortController.run, TUI SortScreen._apply_inbox_refs)"
affects: [phase-13-optimistic-moves, backup, performance]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Once-per-session latch gated by a private helper (_maybe_backup_once) that sets the latch only AFTER a successful create() — preserves BKUP-06 first-write abort with retry"
    - "Narrow @runtime_checkable Protocol (BackupResettable) + isinstance guard at call sites so injected bare mocks are safely skipped (mypy-strict clean, no hasattr)"

key-files:
  created: []
  modified:
    - src/notes_os/backup.py
    - src/notes_os/sorter/controller.py
    - src/notes_os/screens/sort.py
    - tests/test_backup_unit.py
    - tests/screens/test_sort_screen.py
    - tests/screens/test_end_to_end.py
    - CLAUDE.md

key-decisions:
  - "Set the latch True only AFTER a successful create() so a failed first-write backup leaves it False for retry (BKUP-06 preserved)"
  - "Wire begin_session at both session entry points behind an isinstance(repo, BackupResettable) guard so a plain MockNotesRepository (no begin_session) is skipped"
  - "No backup_cadence config hatch — per-session is the sole cadence (BKUP-08); auto_backup_on_write stays the on/off master switch"
  - "Updated the pre-existing test_end_to_end per-write assertion to per-session cadence (a direct consequence of removing before-every-write)"

patterns-established:
  - "Pattern 1: Per-session latch via _maybe_backup_once gate (set-after-success ordering is load-bearing for the abort-and-retry invariant)"
  - "Pattern 2: BackupResettable Protocol as a backup-decorator-only seam, NOT an extension of NotesRepositoryProtocol"

requirements-completed: [BKUP-07, BKUP-08]

# Metrics
duration: 22min
completed: 2026-06-08
---

# Phase 12 Plan 01: Backup Cadence Summary

**Per-session backup cadence — one NoteStore.sqlite copy per triage session instead of up to ~100 per session — via a `_session_backed_up` latch, a `begin_session()` re-arm, and a `BackupResettable` Protocol seam wired into both the CLI and TUI session entry points.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-06-08
- **Completed:** 2026-06-08
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- `BackingUpNotesRepository` now backs up ONCE per session (before the first write only) instead of before every write — removing per-move 92 MB churn while keeping the non-destructive restore guarantee.
- Added the `_session_backed_up` latch, the `_maybe_backup_once` gate, and the public `begin_session()` re-arm method; the latch is set `True` only after a successful `create()` so a failed first-write backup propagates `BackupError`, aborts the write, and leaves the latch unset for retry (BKUP-06).
- Added a narrow `@runtime_checkable` `BackupResettable` Protocol and wired `begin_session()` at both session entry points (CLI `SortController.run`, TUI `SortScreen._apply_inbox_refs`) behind an `isinstance` guard.
- Removed the before-every-write code path entirely with NO `backup_cadence` config hatch (BKUP-08); reworded the T-04-09 / T-06-04 threat-model docs in `backup.py`, `controller.py`, `screens/sort.py`, and `CLAUDE.md` to the per-session language.
- Extended the backup unit suite (per-session cadence, re-arm, first-write-abort-with-retry, disabled-master-switch, Protocol membership) to 99.44% coverage on `backup.py`, and added a TUI Pilot test proving one backup per visit plus per-visit re-arm.

## Task Commits

Changes were left UNSTAGED per the execution context (the orchestrator owns commits; a shared worktree must not be staged by this agent). Logical task breakdown:

1. **Task 1: Per-session latch + begin_session + BackupResettable Protocol** (`src/notes_os/backup.py`) — feat
2. **Task 2: Per-session unit suite (>=95% on backup.py)** (`tests/test_backup_unit.py`) — test
3. **Task 3: Wire begin_session (CLI + TUI) + reword threat docs** (`controller.py`, `screens/sort.py`, `CLAUDE.md`, `tests/screens/test_sort_screen.py`) — feat/docs

**Plan metadata:** SUMMARY + state updates handled by the orchestrator.

## Files Created/Modified
- `src/notes_os/backup.py` — Added `BackupResettable` Protocol, `_session_backed_up` latch, `begin_session()`, `_maybe_backup_once()`; rewrote `move_note`/`ensure_folder` to the once-per-session gate; reworded module + class docstrings to per-session cadence.
- `src/notes_os/sorter/controller.py` — Runtime import of `BackupResettable`; `begin_session()` re-arm at the top of `SortController.run` behind an `isinstance` guard; reworded T-04-09 threat note.
- `src/notes_os/screens/sort.py` — Runtime import of `BackupResettable`; `begin_session()` re-arm in `_apply_inbox_refs` (once per visit, before any move) behind an `isinstance` guard; reworded T-06-04 threat note.
- `tests/test_backup_unit.py` — Added the per-session cadence test group (6 tests) + `_make_multi_inner` helper; imported `BackupResettable`.
- `tests/screens/test_sort_screen.py` — Added `test_tui_one_backup_per_visit_and_rearm` (one backup per multi-move visit; second visit re-arms → second backup).
- `tests/screens/test_end_to_end.py` — Updated a pre-existing per-write backup assertion to the new per-session cadence (deviation, see below).
- `CLAUDE.md` — Reworded the "What this project is" backup sentence to per-session language.

## Decisions Made
- **Latch set only after a successful `create()`** — load-bearing ordering: a failed first-write backup leaves `_session_backed_up = False` so an immediate retry re-attempts the backup (BKUP-06 abort-and-retry).
- **`BackupResettable` is a decorator-only seam** — deliberately NOT added to `NotesRepositoryProtocol`; call sites narrow via `isinstance` so a plain `MockNotesRepository` (no `begin_session`, no real backup decorator) is safely skipped.
- **No `backup_cadence` config** — per-session is the sole cadence (BKUP-08); `auto_backup_on_write` is unchanged as the on/off master switch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated a pre-existing per-write backup assertion to per-session cadence**
- **Found during:** Phase-level verification (`pytest -m 'not integration'`)
- **Issue:** `tests/screens/test_end_to_end.py::test_end_to_end_home_sort_extract_finish` asserted `spy_manager.create.call_count > backup_calls_after_note1` — i.e. a backup fires AGAIN for note 2 within the same triage session. That is exactly the before-every-write cadence this phase removes (BKUP-08), so the assertion failed once the per-session latch landed.
- **Fix:** Replaced the per-write assertion with a per-session one: exactly one backup is taken before note 1's first write (`backup_calls_after_note1 == 1`) and NO additional `create()` fires for note 2 in the same session (`create.call_count == backup_calls_after_note1`). Added a comment citing BKUP-07 / BKUP-08.
- **Files modified:** tests/screens/test_end_to_end.py
- **Verification:** Full unit suite green (381 passed, 6 deselected).
- **Committed in:** left unstaged (orchestrator commits).

**Note (out-of-scope, NOT fixed):** `src/notes_os/backup_models.py` still has a stale "before every write" phrase in the `auto_backup_on_write` field docstring. That file is outside this plan's `files_modified` set and the flag's on/off semantics are unchanged, so the doc reword was logged to `deferred-items.md` rather than editing an out-of-scope file.

---

**Total deviations:** 1 auto-fixed (1 bug — an assertion broken by the intended behavior change) + 1 deferred doc item logged.
**Impact on plan:** The auto-fix was required to keep the suite green under the new cadence; it tightens (not weakens) the assertion to match BKUP-07. No scope creep.

## Issues Encountered
- The plan's per-file verification commands (e.g. `mypy src/notes_os/backup.py`) append to pixi tasks that already specify targets (`mypy src`, `ruff check src tests`), causing duplicate-module / arg-parse errors. Ran the whole-package pixi tasks instead — they subsume the per-file checks. `ruff format --check` is not a pixi task here, so it was run via `pixi run python -m ruff format --check`.

## Verification Results

All run via the absolute pixi binary (`~/.pixi/bin/pixi`, local shim is broken):

- `pixi run ruff` (ruff check src tests) → **0** (All checks passed)
- `pixi run python -m ruff format --check src tests` → **0** (48 files already formatted)
- `pixi run mypy` (strict, whole package) → **0** (no issues in 22 source files)
- `pixi run pytest -m 'not integration'` → **0** (381 passed, 6 deselected)
- `pixi run pytest tests/test_backup_unit.py --cov=notes_os.backup --cov-fail-under=95` → **0** (backup.py coverage **99.44%**, ≥95% floor; 43 passed)
- `pixi run pytest tests/screens/test_sort_screen.py tests/screens/test_navigation.py tests/sorter/test_controller_integration.py` → **0** (30 passed)
- `grep -RF 'backup_cadence' src/ tests/` → no matches (BKUP-08)
- `grep -RF 'backed up automatically before every write' CLAUDE.md` → no matches (doc reworded)

**BKUP-06** (failed first-write backup aborts write, latch unset for retry): satisfied — `test_first_write_backup_failure_aborts_and_leaves_latch_unset` + surviving `test_decorator_backup_failure_aborts_move` / `_aborts_ensure_folder`.
**BKUP-07** (N moves → one backup; new session → new backup): satisfied — `test_one_backup_per_session_many_moves`, `test_begin_session_rearms_backup`, `test_tui_one_backup_per_visit_and_rearm`.
**BKUP-08** (before-every-write removed, no `backup_cadence`): satisfied — `_maybe_backup_once` gate + empty `backup_cadence` grep.
**Hardened criteria:** disabled-master-switch test asserts `_session_backed_up is False` throughout (`test_auto_backup_disabled_never_backs_up_across_sessions`); the SortScreen test proves per-visit re-arm (`create.call_count == 2` on the second visit).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Per-session cadence is the foundation Phase 13 (Optimistic moves) consumes via `_session_backed_up` / `begin_session()` / `BackupResettable`.
- No blockers. One deferred pure-doc item (`backup_models.py` field docstring) logged in `deferred-items.md`.

## Self-Check: PASSED

- FOUND: `.planning/phases/12-backup-cadence/12-01-SUMMARY.md`
- FOUND: `def begin_session` in `src/notes_os/backup.py`
- FOUND: `class BackupResettable` in `src/notes_os/backup.py`
- FOUND: `def _maybe_backup_once` in `src/notes_os/backup.py`
- Note: per the execution context, code changes are left UNSTAGED (no per-task commits); the orchestrator owns commits for this shared worktree.

---
*Phase: 12-backup-cadence*
*Completed: 2026-06-08*
