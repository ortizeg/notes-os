---
phase: 15-ux-session-resume
plan: 02
subsystem: ui
tags: [textual, pydantic, session-resume, sortscreen, modal, pathlib]

# Dependency graph
requires:
  - phase: 15-ux-session-resume
    provides: "SessionState + ResumeStore (save/load/clear, match-by-id), SortSession.restore_counts, ResumePromptModal(ModalScreen[bool])"
  - phase: 10-perf-lazy-bodies
    provides: "id-keyed _note_cache bulk-body worker (resume render cooperates with it, no race)"
  - phase: 13-optimistic-moves
    provides: "_advance / serialized off-thread write drainer (the per-note save point hangs off _advance)"
provides:
  - "SortScreen ResumeStore + now_provider DI seam (defaults keep all existing call sites unchanged)"
  - "_save_session_state save points wired into _advance (per-note) and action_back (leave-mid-session)"
  - "on-mount always-ask resume decision in _apply_inbox_refs (ResumePromptModal push) + _on_resume_decision dismiss callback"
  - "clear-on-finish in _complete_finish, clear-on-start-over + clear-on-stale in the resume decision/callback"
  - "12 Pilot tests covering every save/resume/clear path"
affects: [milestone-v3.0-close, future-resume-stale-prompt]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inject-the-clock (now_provider) mirroring write_log for a deterministic saved_at"
    - "Always-ask resume: modal-defers-render (resumable path) vs inline-render (not-resumable) are mutually exclusive — render + bulk-load fire exactly once per path"
    - "Best-effort persistence: save/clear wrapped in try/except OSError so a disk error never crashes triage"

key-files:
  created: []
  modified:
    - src/notes_os/screens/sort.py
    - tests/screens/test_sort_screen.py

key-decisions:
  - "ResumePromptModal imported lazily inside _apply_inbox_refs (not module-top) to avoid the app.py↔sort.py circular import; ResumeStore/SessionState/datetime are module-top (resume.py has no back-edge)"
  - "store/now_provider added as keyword-only params with None defaults so the ~dozen existing SortScreen(...) call sites and all test harnesses construct unchanged"
  - "Type-narrowing via an inlined `state is not None and …` if-condition instead of an assert (assert trips Ruff S101 in src/)"

patterns-established:
  - "Save-point guard: _save_session_state no-ops unless 0 < _index < len(_refs) and not _inbox_empty — one guard covers empty/unstarted/finished"
  - "Resumability = state is not None AND state.matches(inbox, current_ids) AND 0 < state.index < len(_refs); evaluated before first render"

requirements-completed: [UX-03]

# Metrics
duration: 18min
completed: 2026-06-09
---

# Phase 15 Plan 02: Wire Session Resume into SortScreen Summary

**End-to-end UX-03: SortScreen now saves lightweight progress after each note and on leave-mid-session, and on relaunch ALWAYS asks "Resume at N / Start over" when a saved state still matches the inbox by exact note-id signature — a changed inbox safely falls back to start-over.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 3 (2 TDD + 1 verification/cleanup)
- **Files modified:** 2

## Accomplishments
- `SortScreen.__init__` gained a `store: ResumeStore | None` DI seam and a `now_provider` clock seam, both keyword-only with `None` defaults — every existing call site (app.py `SCREENS` instantiation + all Pilot harnesses) constructs unchanged.
- `_save_session_state` persists a `SessionState` (inbox folder + exact id signature + next-to-process `_index` + the three running counts + injected `saved_at`) at two save points: the END of `_advance` (per-note) and `action_back` at AWAIT_CATEGORY (leave-mid-session, BEFORE `pop_screen`). The save-point guard (`0 < _index < len(_refs)` and not `_inbox_empty`) suppresses empty/unstarted/finished sessions.
- The on-mount resume decision in `_apply_inbox_refs` (after `_refs` is set, before the first render) ALWAYS pushes `ResumePromptModal` for a resumable state; `_on_resume_decision` applies Resume (jump `_index` + `restore_counts`) or Start over (clear + index 0).
- Clear points: `_complete_finish` (session done), the Start-over branch, and the not-resumable stale/out-of-range branch — a completed/changed inbox leaves no misleading "Resume at N" file.
- 12 new Pilot tests cover advance-saves, leave-mid-session-saves, index-0/empty/finish no-save, matching→Resume-lands-with-restored-counts, Start-over-clears, stale-ids→no-prompt, no-state, out-of-range, resume-to-finish-clears, and previews-load-on-resumed-note.

## Save points, resume rule, and worker cooperation (as built)

**Save points** (`_save_session_state`):
1. End of `_advance` — captures the NEW `_index` (the next note to process), exactly where a resume should land. The guard makes it a no-op when the advance finished the session (`_index >= len(_refs)`), so a finished session never leaves a stale file.
2. `action_back` at AWAIT_CATEGORY, BEFORE `self.app.pop_screen()`. Guard suppresses the save when the user never started (index 0).

Never saves when `_inbox_empty` is True.

**Resumability** (computed in `_apply_inbox_refs` before the first render): `state is not None AND state.matches(inbox_folder, current_ids) AND 0 < state.index < len(_refs)`. The `state is not None` term is first so mypy narrows `state` inside the block (no assert needed). If resumable → stash `_pending_resume_state`, push `ResumePromptModal`, and RETURN without rendering or starting the bulk load. If not resumable → clear any stale file, render at 0, start bulk load inline.

**`_on_resume_decision(resume)`**: consumes/clears `_pending_resume_state`; on `True` jumps `_index = state.index` and calls `restore_counts(moved, skipped, errors)`; otherwise clears the file and resets to index 0. BOTH branches then reset router state and call `_render_current_note()` + `_start_bulk_body_load()`.

**Bulk-load-once invariant (reviewer concern #2):** render + `_start_bulk_body_load()` fire EXACTLY ONCE per launch — either in `_on_resume_decision` (resumable, both branches) OR inline in `_apply_inbox_refs` (not resumable). The resumable path early-returns before the inline render/start, so they are mutually exclusive. The bulk load fills the id-keyed `_note_cache` independently of `_index`; the resumed render is an id-keyed lookup, so a page landing before/after the modal resolves the correct note by id — Phase-10's self-correcting guard, no race (verified by `test_previews_load_on_resumed_note`).

## Task Commits

Atomic commits are created by the orchestrator (this executor left changes unstaged per the worktree protocol). Logical units:

1. **Task 1 (TDD): ResumeStore DI seam + save points** — `src/notes_os/screens/sort.py`, `tests/screens/test_sort_screen.py`
2. **Task 2 (TDD): on-mount always-ask resume decision + clear-on-finish** — same two files
3. **Task 3: full-suite green + CI-parity gates** — formatting fix only

## Files Created/Modified
- `src/notes_os/screens/sort.py` — `store`/`now_provider` params, `_now`/`_save_session_state` helpers, `_advance`/`action_back` save points, `_apply_inbox_refs` resume decision, `_on_resume_decision` callback, `_complete_finish` clear.
- `tests/screens/test_sort_screen.py` — `Path` TYPE_CHECKING import, `ResumeStore`/`SessionState`/`ResumePromptModal` imports, `_resume_notes` helper, `_RESUME_SAVED_AT` fixed clock, 12 resume Pilot tests.

## Verification

All run via the REAL pixi binary (the repo `pixi` shim is broken locally):

- `~/.pixi/bin/pixi run pytest tests/screens/test_sort_screen.py -q -k "<resume tests>"` → **12 passed**
- `~/.pixi/bin/pixi run mypy` → **Success: no issues found in 23 source files**
- `~/.pixi/bin/pixi run ruff` → **All checks passed!**
- `.pixi/envs/default/bin/ruff format --check src tests` → **50 files already formatted**
- `~/.pixi/bin/pixi run pytest -m 'not integration' -q --cov-fail-under=80` → **459 passed, 6 deselected** (overall coverage ≥80%; `sort.py` at 83%)

## Decisions Made
- Lazy-import `ResumePromptModal` inside `_apply_inbox_refs` to avoid the `app.py` → `sort.py` → `app.py` circular import (app.py imports SortScreen at module top, before `ResumePromptModal` is defined). `ResumeStore`/`SessionState`/`datetime` are safe at module top since `resume.py` has no back-edge to `sort.py`/`app.py`.
- Keyword-only `store`/`now_provider` with `None` defaults keep all existing construction sites unchanged (reviewer concern #5).
- Inlined `state is not None` into the resumability `if` for mypy narrowing rather than an `assert` (assert trips Ruff S101 in `src/`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ResumePromptModal import moved from module-top to a lazy in-method import**
- **Found during:** Task 1/2 (wiring the modal push)
- **Issue:** The plan's Task-3 note implied a runtime module-top `ResumePromptModal` import, but `app.py` imports `sort.py` at module load (line 47) and defines `ResumePromptModal` later (line 137), so a module-top `from notes_os.app import ResumePromptModal` in `sort.py` would raise `ImportError` (partially-initialized module / circular import).
- **Fix:** Import `ResumePromptModal` lazily inside `_apply_inbox_refs`, mirroring the existing `_after_move` lazy import of `TaskExtractScreen`. `ResumeStore`/`SessionState`/`datetime` remain module-top (no circular edge).
- **Files modified:** src/notes_os/screens/sort.py
- **Verification:** mypy clean, ruff clean (TC/import-order), full suite green.
- **Committed in:** part of the Task 1/2 changes.

**2. [Rule 3 - Blocking] Type-narrowing via if-condition instead of assert**
- **Found during:** Task 3 (ruff gate)
- **Issue:** An `assert state is not None` used to narrow for mypy tripped Ruff `S101` (assert in `src/`).
- **Fix:** Folded `state is not None` as the first term of the resumability `if`, so mypy narrows `state` inside the block without an assert.
- **Files modified:** src/notes_os/screens/sort.py
- **Verification:** mypy + ruff both clean.
- **Committed in:** part of the Task 2/3 changes.

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking). **Impact:** Both necessary to compile/lint cleanly given the real `app.py`↔`sort.py` import topology and the repo's S101 rule. No scope creep — behavior is exactly as the plan specifies.

## Issues Encountered
- One test line (an assert message in `test_previews_load_on_resumed_note`) exceeded the line length; `ruff format` reformatted it. Re-verified format-check clean.

## Next Phase Readiness
- UX-03 is delivered end-to-end and is the final wave of Phase 15 (milestone v3.0). No blockers. The `now_provider`/`saved_at` plumbing is in place should a future "resume a stale session from N minutes ago?" prompt want to consult `saved_at` (currently persisted-but-not-consulted by `matches`).

## Self-Check: PASSED
- `src/notes_os/screens/sort.py` — FOUND (modified: `_save_session_state`, `_on_resume_decision`, `restore_counts` call, `_store.clear()` present)
- `tests/screens/test_sort_screen.py` — FOUND (12 resume tests present, all passing)
- No commits created by this executor (worktree protocol: orchestrator commits) — N/A for hash verification.

---
*Phase: 15-ux-session-resume*
*Completed: 2026-06-09*
