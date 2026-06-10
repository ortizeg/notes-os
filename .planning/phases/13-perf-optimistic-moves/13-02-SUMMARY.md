---
phase: 13-perf-optimistic-moves
plan: 02
subsystem: ui
tags: [textual, threading, deque, optimistic-ui, off-thread-write, backup-latch, applescript]

# Dependency graph
requires:
  - phase: 13-perf-optimistic-moves (13-01)
    provides: "Router.defer_writes seam (resolve-only _do_move) + SortSession.record_move_failure (move→error reconciliation)"
  - phase: 12-backup-cadence
    provides: "Per-session backup latch (_session_backed_up / begin_session, not thread-safe) re-armed in _apply_inbox_refs"
  - phase: 10-perf-paged-preview
    provides: "@work(thread=True) worker + call_from_thread marshalling pattern mirrored by the write drainer"
provides:
  - "Optimistic move advance in SortScreen — instant 'moved ✓ → {display}' confirmation, no AppleScript/backup on the event loop (PERF-04)"
  - "Serialized single-writer off-thread drainer (_write_queue deque + _drain_write_queue worker + _writer_active guard) reusable by Phase 14 Undo / Phase 15 Resume"
  - "Failure surfacing path (_on_write_failed) — record_move_failure + non-blocking notify + _failed_moves; note retained in inbox (PERF-05 / T-06-05)"
  - "Lost-wakeup re-check (_on_writer_drained: clear flag → re-check queue → re-arm) (T-13-09)"
  - "Drain-before-summary finish reconciliation (_finish_pending → _complete_finish) so counts reflect landed failures (T-13-08)"
affects: [14-undo-move-back, 15-resume-session]

# Tech tracking
tech-stack:
  added: []  # collections.deque is stdlib; no new dependencies
  patterns:
    - "Optimistic UI advance: capture (note_id, folder_path, display) into locals → record optimistically → enqueue → advance; reconcile on async failure"
    - "Serialized single-consumer FIFO drainer guarded by a main-thread-only boolean; lost-wakeup re-check after clearing the guard"
    - "Drain-before-finalize: defer terminal summary until the off-thread write queue empties"

key-files:
  created: []
  modified:
    - src/notes_os/screens/sort.py
    - tests/screens/test_sort_screen.py

key-decisions:
  - "Router constructed with defer_writes=True only in SortScreen.on_mount; the CLI SortController is untouched (defer_writes default False) so its synchronous write path and integration tests stay green."
  - "_writer_active is read/written ONLY on the main thread (in _enqueue_write and _on_writer_drained); the worker thread never touches it — this keeps the non-thread-safe Phase-12 backup latch touched by exactly one thread."
  - "FIFO collections.deque drained by a SINGLE @work(thread=True) worker — deque.append/popleft are individually atomic under the GIL, producer-only-appends + single-consumer-only-pops needs no lock."
  - "Failure handling marshals back to the main thread via call_from_thread, reconciles via record_move_failure (move→error), and retains the note (move_note raises before removal)."
  - "_finish defers via _finish_pending while writes are in flight; _on_writer_drained completes it once drained; app.sort_in_progress stays True meanwhile so the ConfirmQuitModal guard still fires."

patterns-established:
  - "Optimistic-advance + serialized off-thread write: enqueue-before-advance avoids the advance/worker race; one writer at a time preserves backup-latch + move ordering."
  - "Lost-wakeup guard: clear the active flag THEN re-check the queue on the main thread, re-arming the drainer if an item arrived in the gap."

requirements-completed: [PERF-04, PERF-05]

# Metrics
duration: 35min
completed: 2026-06-09
---

# Phase 13 Plan 02: Optimistic Moves with Serialized Off-Thread Write Summary

**SortScreen now advances a move instantly (optimistic UI + `moved ✓ → {display}` toast) while a single serialized background drainer performs `ensure_folder` + `move_note` + the per-session backup off the event loop — failures are surfaced, reconciled (move→error), and the note is retained, never dropped.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-09
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Eliminated the per-move ~1 s UI freeze (PERF-04): the terminal write is deferred (`Router(defer_writes=True)`) and runs on a single serialized `@work(thread=True)` drainer; a skip/keystroke is honored while a prior move's write is in flight.
- Single-writer safety: a FIFO `collections.deque` drained by exactly one worker (guarded by a main-thread-only `_writer_active`) keeps the non-thread-safe Phase-12 backup latch and move ordering uncorrupted — proven by `test_serialized_writes_one_backup_fifo_order` (FIFO order + exactly one backup `create()`).
- Failure surfacing (PERF-05 / T-06-05): a failed off-thread write marshals to the main thread, calls `record_move_failure` (move→error), appends to `_failed_moves`, posts a non-blocking warning `notify`, and the note stays in the inbox — the session continues.
- Lost-wakeup guard (T-13-09): `_on_writer_drained` clears `_writer_active`, THEN re-checks the queue and re-arms the drainer — locked by `test_drained_requeue_rearms_writer`.
- Drain-before-summary (T-13-08): `_finish` defers via `_finish_pending` until the queue empties, then `_complete_finish` builds the summary (with a "Needs attention" section) so landed failures are reflected; `app.sort_in_progress` stays True while pending.

## Task Commits

Not committed by the executor (per execution context: a shared worktree; the orchestrator commits). All changes left unstaged with full verification run and green.

1. **Task 1: Defer the Router write + optimistic advance + serialized off-thread write drainer** — `src/notes_os/screens/sort.py` (feat)
2. **Task 2: Pilot tests — never-freeze, serialized writes, failure surfaced+recorded+retained, counts, drain-on-finish** — `tests/screens/test_sort_screen.py` (test)

## Files Created/Modified
- `src/notes_os/screens/sort.py` — Added `_write_queue` / `_writer_active` / `_failed_moves` / `_finish_pending` instance state; `Router(defer_writes=True)` in `on_mount`; rewrote `_handle_move` for optimistic advance (capture-before-advance, optimistic `record_move`, toast, enqueue); added `_enqueue_write`, `@work(thread=True) _drain_write_queue`, `_on_writer_drained` (lost-wakeup re-check), `_on_write_failed`; split `_finish` into a drain-deferral check + `_complete_finish` (with "Needs attention" section). `_after_move`/`begin_session`/extraction-disabled paths unchanged.
- `tests/screens/test_sort_screen.py` — Added 6 new Pilot tests (`test_move_advances_optimistically_before_write`, `test_router_runs_in_defer_writes_mode`, `test_rapid_moves_never_freeze`, `test_serialized_writes_one_backup_fifo_order`, `test_failed_write_surfaced_recorded_and_note_retained`, `test_finish_drains_before_summary`, `test_drained_requeue_rearms_writer`). Gated worker writes with `threading.Event` so pending/optimistic states are observed deterministically. Updated the pre-existing `test_archive_move_backup_failure_does_not_crash` to the new off-thread failure path.

## Decisions Made
- See `key-decisions` in the frontmatter. Headline: `defer_writes=True` scoped to SortScreen only; `_writer_active` is a main-thread-only guard; FIFO single-consumer deque needs no lock under the GIL.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated pre-existing `test_archive_move_backup_failure_does_not_crash` to the new off-thread failure path**
- **Found during:** Task 2 (Pilot tests)
- **Issue:** With `defer_writes=True`, the archive backup failure no longer raises synchronously inside `router.handle_category` (the old `_router_call` → `_show_move_error` path). The test asserted old behavior: note stays at `AWAIT_CATEGORY` with a "Could not move" prompt and no advance. The plan's Task 2 `read_first` explicitly says to "adapt this for the NEW failure path which surfaces via `_on_write_failed`."
- **Fix:** Rewrote the test to drain the failing worker write, then assert the new contract: optimistic move reconciled to an error (`errors == 1` / `moved == 0`), `_failed_moves` tracks the note, no inner move recorded, TUI still alive.
- **Files modified:** `tests/screens/test_sort_screen.py`
- **Verification:** `pytest tests/screens/test_sort_screen.py -q` → 21 passed.

**2. [Rule 1 - Test correctness] Gated worker writes with `threading.Event` instead of relying on "pending after one pause"**
- **Found during:** Task 2 (Pilot tests)
- **Issue:** The plan's never-freeze/optimistic/failure tests asserted "write still pending after a single `pilot.pause()`" or "`moved == 1` before reconcile." In the Textual Pilot harness the `@work(thread=True)` drainer completes during that pause, making the assertions flaky/false (race: queue already drained / move already reconciled).
- **Fix:** Mirrored the existing `test_large_inbox_paged_indicator_and_never_blocks` pattern — gate `move_note` with a `threading.Event` so the in-flight (`_writer_active is True`) / optimistic (`moved == 1`) / `_finish_pending is True` states are observed deterministically, then release the gate and drain. The never-freeze test still proves a skip is honored while the gated move's write is in flight (event loop not blocked).
- **Files modified:** `tests/screens/test_sort_screen.py`
- **Verification:** All 6 new tests + the lost-wakeup test pass deterministically across repeated runs.

---

**Total deviations:** 2 auto-fixed (both Rule 1 — test correctness for the new design; the plan anticipated #1).
**Impact on plan:** No scope creep. Source `sort.py` matches the plan's `<action>` exactly. The test adaptations are required for deterministic, correct assertions under the asynchronous worker harness.

## Issues Encountered
- Worker-timing nondeterminism in the Pilot harness (the thread drainer finishes inside `pilot.pause()`). Resolved by gating the worker write with `threading.Event` (deviation #2), the same discipline already used by the Phase-10 streaming tests.

## Concurrency Invariants — Implemented and Tested
- **Single writer (T-13-05):** one `@work(thread=True)` drainer; `_writer_active` read/written only on the main thread; worker never touches it → backup latch touched by one thread. Proven: `test_serialized_writes_one_backup_fifo_order` (exactly one `create()`).
- **FIFO ordering (T-13-06):** `popleft` in enqueue order. Proven: same test asserts `["fifo-1", "fifo-2"]` order.
- **No advance/worker race (T-13-10):** `_handle_move` captures `note_id`/`folder_path`/`display` into locals and enqueues BEFORE `_advance`. Proven: `test_move_advances_optimistically_before_write` (queued item carries the right id and lands).
- **Failure never drops a note (PERF-05 / T-06-05):** `_on_write_failed` → `record_move_failure` + `notify` + `_failed_moves`; note retained. Proven: `test_failed_write_surfaced_recorded_and_note_retained` (note still in inner inbox; `errors == 1`).
- **Lost-wakeup re-check (T-13-09):** `_on_writer_drained` clears flag THEN re-checks/re-arms. Proven: `test_drained_requeue_rearms_writer`.
- **Drain before summary (T-13-08):** `_finish` defers via `_finish_pending`; `_complete_finish` after drain; `sort_in_progress` stays True meanwhile. Proven: `test_finish_drains_before_summary`.

## Verification

Run via the absolute pixi binary (the pixi shell shim is broken locally):

- `~/.pixi/bin/pixi run mypy` → **Success: no issues found in 22 source files** (strict, no new `type: ignore`).
- `~/.pixi/bin/pixi run ruff` → **All checks passed!** (`ruff check src tests`, full ruleset). `~/.pixi/bin/pixi run format` → clean (`ruff format`).
- `~/.pixi/bin/pixi run pytest tests/screens/test_sort_screen.py -q` → **21 passed** (all 6 new Pilot tests + lost-wakeup + FIFO + existing screen tests).
- `~/.pixi/bin/pixi run pytest tests/screens/ tests/sorter/test_controller_integration.py -q` → **46 passed** (CLI controller path untouched).
- `~/.pixi/bin/pixi run pytest -m 'not integration'` → **401 passed, 6 deselected**.
- Coverage gate: `pytest -m 'not integration' --cov=notes_os --cov-fail-under=80` → **Required test coverage of 80% reached. Total coverage: 91.61%** (sort.py 85%; write-path modules notes.py/backup.py/router.py at 100%/100%/99%, above their 95% floor).

## Known Stubs
None — all new code paths are wired and exercised by tests; no placeholder/empty-data stubs introduced.

## Next Phase Readiness
- The off-thread write plumbing (`_enqueue_write` / `_drain_write_queue` / `_writer_active` / `_failed_moves`) is named and structured for reuse by **Phase 14 (Undo / move-back)** and **Phase 15 (Resume)** — a move-back write can enqueue through the same single-writer path.
- No blockers. The CLI `SortController` synchronous write path remains intact (`defer_writes` default False), so any CLI-facing work is unaffected.

## Self-Check: PASSED
- `src/notes_os/screens/sort.py` exists and contains `_write_queue`, `_drain_write_queue`, `_on_writer_drained`, `_on_write_failed`, `_failed_moves`, `_finish_pending`, `defer_writes=True`.
- `tests/screens/test_sort_screen.py` exists and contains all 6 new test names + `test_drained_requeue_rearms_writer`.
- All verification commands above re-run green.

---
*Phase: 13-perf-optimistic-moves*
*Completed: 2026-06-09*
