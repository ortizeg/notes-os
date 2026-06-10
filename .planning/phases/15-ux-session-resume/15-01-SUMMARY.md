---
phase: 15-ux-session-resume
plan: 01
subsystem: ui
tags: [session-resume, persistence, pydantic, textual, atomic-write, staleness]

# Dependency graph
requires:
  - phase: 12-13-14
    provides: "SortSession (moved/skipped/errors counters, _undo_stack, _events) and ConfirmQuitModal — the templates this plan extends"
provides:
  - "notes_os.sorter.resume.SessionState — frozen Pydantic V2 session-position snapshot with injected saved_at and exact-equality matches()"
  - "notes_os.sorter.resume.ResumeStore — atomic save, None-safe load, idempotent clear; injectable path defaulting to ~/.notes-os/session-state.json"
  - "notes_os.sorter.resume._DEFAULT_STATE_PATH — module-level default path constant"
  - "SortSession.restore_counts(moved, skipped, errors) — re-seeds the running tally on resume without touching the undo stack or event log"
  - "notes_os.app.ResumePromptModal — ModalScreen[bool], Resume->True / Start over->False"
affects: [15-02, sortscreen-wiring, session-resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomic on-disk write: temp file in the same dir + Path.replace (same-fs rename) so a crash never leaves a torn JSON"
    - "None-safe load: catch OSError + ValueError (Pydantic ValidationError is a ValueError subclass) -> degrade to None, never raise"
    - "Injected timestamp on a frozen model (no datetime.now() default_factory) — mirrors the write_log injected clock"
    - "Staleness by exact id-tuple + inbox equality"

key-files:
  created:
    - src/notes_os/sorter/resume.py
    - tests/sorter/test_resume_unit.py
  modified:
    - src/notes_os/sorter/session.py
    - src/notes_os/app.py
    - tests/sorter/test_session_unit.py
    - tests/screens/test_navigation.py
    - pyproject.toml

key-decisions:
  - "Staleness = EXACT note_ids tuple equality + inbox_folder equality; saved_at is NOT part of matches()"
  - "saved_at is a required INJECTED field (no default_factory) for test determinism and round-trip equality"
  - "save() is atomic (temp + Path.replace); load() degrades a missing OR corrupt file to None, never raises"
  - "restore_counts clamps each counter with max(0, n) and leaves _undo_stack/_events untouched"
  - "ResumePromptModal is pushed by instance (NOT registered in NotesOSApp.SCREENS), mirroring ConfirmQuitModal"

patterns-established:
  - "Atomic state persistence: write temp sibling + Path.replace; never partial-write the real file"
  - "UI-agnostic persistence layer unit-tested without a Textual harness (design directive 1)"

requirements-completed: [UX-03]

# Metrics
duration: ~35min
completed: 2026-06-09
---

# Phase 15 Plan 01: Session-Resume Persistence Layer Summary

**Frozen `SessionState` + atomic, None-safe `ResumeStore` (exact-id-tuple staleness), `SortSession.restore_counts`, and the `ResumePromptModal` — the UI-agnostic resume contract Wave 2 (15-02) wires into SortScreen.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-09T22:19Z
- **Tasks:** 3
- **Files modified:** 6 (2 created, 4 modified) + pyproject.toml override

## Accomplishments

- `notes_os.sorter.resume.SessionState` — frozen Pydantic V2 model carrying `inbox_folder: str`, `note_ids: tuple[str, ...]`, `index/moved/skipped/errors: int` (`ge=0`), and an INJECTED `saved_at: datetime`. `matches(inbox_folder, note_ids)` is True only on exact id-tuple + inbox equality (any reorder/add/remove/different-inbox is stale).
- `notes_os.sorter.resume.ResumeStore` — `save(state)` writes atomically (temp sibling file + `Path.replace`, creating parent dirs); `load() -> SessionState | None` returns the state on a good file, `None` on a missing file, and `None` on a corrupt/schema-invalid file (catches `OSError`/`ValueError`, never raises); `clear()` is idempotent (`unlink(missing_ok=True)`). Path injectable, default `~/.notes-os/session-state.json` (`_DEFAULT_STATE_PATH`).
- `SortSession.restore_counts(moved, skipped, errors)` — re-seeds the three running counters with `max(0, n)` clamping; leaves `_undo_stack` and `_events` untouched so a resumed session keeps its own fresh undo stack/audit log while the final summary reflects the whole session.
- `notes_os.app.ResumePromptModal(ModalScreen[bool])` — mirrors `ConfirmQuitModal`: `y`/Resume button -> dismiss `True`, `n`/`escape`/Start-over button -> dismiss `False`; shows "Resume at note {index+1} of {total}".

## Task Commits

Left UNSTAGED per execution-context instruction (orchestrator commits). Tasks were executed TDD:

1. **Task 1: resume.py — SessionState + ResumeStore** (test -> feat): `tests/sorter/test_resume_unit.py` (RED, then GREEN), `src/notes_os/sorter/resume.py`
2. **Task 2: restore_counts + ResumePromptModal** (test -> feat): session/navigation tests (RED, then GREEN), `src/notes_os/sorter/session.py`, `src/notes_os/app.py`
3. **Task 3: lint + type-check** (chore): pyproject.toml mypy override added; mypy/ruff/ruff-format all clean

## Files Created/Modified

- `src/notes_os/sorter/resume.py` (created) — `SessionState`, `ResumeStore`, `_DEFAULT_STATE_PATH`, `_TEMP_SUFFIX`.
- `tests/sorter/test_resume_unit.py` (created) — 20 tests: round-trip, load-None-on-missing/corrupt/schema-invalid, atomic-no-leftover-tmp, parent-dir creation, clear idempotency, all five `matches` mismatch shapes, default-path (no real-home I/O).
- `src/notes_os/sorter/session.py` (modified) — added `restore_counts`.
- `src/notes_os/app.py` (modified) — added `ResumePromptModal` + named id/label constants.
- `tests/sorter/test_session_unit.py` (modified) — added `TestRestoreCounts` (4 tests).
- `tests/screens/test_navigation.py` (modified) — added 3 ResumePromptModal Pilot tests (Y/N/Esc).
- `pyproject.toml` (modified) — added `notes_os.sorter.resume` to the documented `disallow_any_explicit=false` mypy override (Pydantic-model module exemption).

## ResumePromptModal API (for Plan 15-02)

- Constructor: `ResumePromptModal(index: int, total: int)` — `index` is the 0-based resume position; the prompt shows the 1-based `index + 1`.
- Push BY INSTANCE with a result callback: `app.push_screen(ResumePromptModal(index, total), callback)`. It is NOT in `NotesOSApp.SCREENS`.
- Dismiss semantics: `True` = Resume, `False` = Start over (`y`/button, `n`/`escape`/button).

## restore_counts contract (for Plan 15-02)

- Call ONCE on resume, BEFORE any new `record_*` in the resumed run.
- Clamps each arg to `>= 0`; does NOT touch the undo stack or the event log.
- A subsequent `record_move`/`record_skip` continues counting from the restored base; the final `summary()` reflects the whole (pre + post relaunch) session.

## Decisions Made

- Followed the plan's settled design decisions verbatim (exact-id-tuple staleness; injected `saved_at`; atomic write; load-never-raises).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added `notes_os.sorter.resume` to the pyproject.toml mypy `disallow_any_explicit=false` override**
- **Found during:** Task 3 (lint/type-check gate)
- **Issue:** `mypy --strict` reports `explicit-any` on every Pydantic `BaseModel` subclass line (inherited `Any` from `BaseModel.__init__(**data: Any)` / `model_validate(obj: Any)`). This is a known, documented project condition — `resume.py` defines a Pydantic model (`SessionState`) so it tripped the global rule.
- **Fix:** Appended `"notes_os.sorter.resume"` to the existing module-list override at `pyproject.toml` line 73. The override block's own comment explicitly instructs: "Add a model module here when a new phase introduces one." This is the project's sanctioned extension point — non-model code keeps full explicit-Any checking.
- **Files modified:** pyproject.toml
- **Verification:** `~/.pixi/bin/pixi run mypy` -> "Success: no issues found in 23 source files".
- **Committed in:** (unstaged — orchestrator commits)

**2. [housekeeping] Reverted incidental pixi.lock churn**
- **Found during:** Task 3 verification runs
- **Issue:** Running `~/.pixi/bin/pixi run ...` regenerated the self-package setuptools-scm dev-version string + sha256 in `pixi.lock` (no real dependency change).
- **Fix:** `git checkout -- pixi.lock` to keep the working tree clean. No dependencies were added (only stdlib `datetime`/`pathlib` + already-present Pydantic/Textual — consistent with threat T-15-SC: zero installs).
- **Files modified:** none (reverted)

---

**Total deviations:** 1 blocking auto-fix (the mypy override, via the project's own documented mechanism) + 1 housekeeping revert.
**Impact on plan:** No scope creep. The pyproject.toml override is the documented way to register a new Pydantic-model module; it does not weaken checking for any non-model code. No new third-party packages.

## Issues Encountered

- A stray `assert session.errors == 1` line appeared at the tail of the `restore_then_record_continues_tally` test (a one-line residue beyond my intended append). Caught immediately by the first Task-2 run (GREEN failed), removed, re-run green. No source code was affected.

## Verification

All commands run with the REAL pixi binary (the repo shim is broken locally):

- `~/.pixi/bin/pixi run pytest tests/sorter/test_resume_unit.py -x -q --cov=notes_os.sorter.resume --cov-fail-under=95` -> **20 passed; resume.py 100%**.
- `~/.pixi/bin/pixi run pytest tests/sorter/test_session_unit.py tests/screens/test_navigation.py -x -q --cov=notes_os.sorter.session --cov-fail-under=95` -> **61 passed; session.py 99%** (the single uncovered line 435 is the pre-existing `write_log` `datetime.now()` fallback, untouched by this plan).
- `~/.pixi/bin/pixi run mypy` -> **Success: no issues found in 23 source files**.
- `~/.pixi/bin/pixi run ruff` -> **All checks passed!**
- `.pixi/envs/default/bin/ruff format --check src tests` -> **50 files already formatted**.
- `~/.pixi/bin/pixi run pytest -m 'not integration' -q` -> **447 passed, 6 deselected** (no existing call site broke).

## Known Stubs

None — this plan delivers complete, tested logic. The SortScreen wiring (save points, the resume decision, `restore_counts`/`ResumePromptModal` call sites) is intentionally deferred to Plan 15-02 per the objective, not a stub.

## User Setup Required

None — no external service configuration; no network; no new dependencies.

## Next Phase Readiness

- Plan 15-02 (Wave 2) can now wire `ResumeStore.save`/`load`/`clear`, `SessionState.matches`, `SortSession.restore_counts`, and push `ResumePromptModal` into `SortScreen` for the locked "ALWAYS ASK" resume behavior.
- No blockers. The persistence contract is frozen and fully unit-tested.

## Self-Check: PASSED

- FOUND: src/notes_os/sorter/resume.py
- FOUND: tests/sorter/test_resume_unit.py
- FOUND: .planning/phases/15-ux-session-resume/15-01-SUMMARY.md
- FOUND: SortSession.restore_counts (session.py)
- FOUND: ResumePromptModal (app.py)

_Commits intentionally not made — per the execution context, this Wave-1 plan leaves all changes UNSTAGED for the orchestrator to commit._

---
*Phase: 15-ux-session-resume*
*Completed: 2026-06-09*
