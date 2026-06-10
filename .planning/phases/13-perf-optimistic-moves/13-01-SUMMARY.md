---
phase: 13-perf-optimistic-moves
plan: 01
subsystem: sorter
tags: [router, session, perf, optimistic-moves, defer-writes]
requires:
  - "Router / RouteResult (router.py)"
  - "SortSession / _NoteEvent (session.py)"
provides:
  - "Router.__init__(..., defer_writes: bool = False) resolve-only seam"
  - "Router._defer_writes instance field gating _do_move I/O"
  - "SortSession.record_move_failure(note_id, message) count-conversion"
affects:
  - "13-02 SortScreen optimistic-advance + off-thread write (consumes both seams)"
tech-stack:
  added: []
  patterns:
    - "Single shared write site (_do_move) gated by one boolean — covers all 3 move entrypoints"
    - "Optimistic-count reconciliation: rewrite most-recent MOVE event to ERROR, guarded decrement"
key-files:
  created: []
  modified:
    - src/notes_os/sorter/router.py
    - src/notes_os/sorter/session.py
    - tests/sorter/test_router_unit.py
    - tests/sorter/test_session_unit.py
decisions:
  - "defer_writes is keyword-only (after year_provider) so positional call sites are unaffected and the CLI default stays False."
  - "record_move_failure scans self._events in reverse to target the most-recent MOVE for the id; falls back to a fresh ERROR (moved untouched) when none exists, so counts never go negative."
metrics:
  duration: ~15m
  completed: 2026-06-09
  requirements: [PERF-04, PERF-05]
---

# Phase 13 Plan 01: Router defer_writes seam + SortSession count-conversion Summary

Added a `Router(defer_writes=True)` resolve-only move seam (skips `ensure_folder`/`move_note`
inside the single shared `_do_move`, returns the identical MOVE `RouteResult`) and a
`SortSession.record_move_failure` that converts an optimistically-counted move into a recorded
error — the two unit-proven primitives Plan 13-02's optimistic-advance SortScreen depends on. The
CLI write path is provably untouched (`defer_writes` defaults `False`, `build_default_controller`
unchanged, controller integration suite green).

## What was built

### Task 1 — Router.defer_writes resolve-only seam (router.py)
- Added keyword-only `defer_writes: bool = False` to `Router.__init__` (after `year_provider`),
  stored as `self._defer_writes`. Documented in both the class and constructor docstrings.
- Gated `_do_move` on `self._defer_writes` BEFORE the two repo calls:
  - `True` → skip `ensure_folder` + `move_note`, log at debug `"Resolved move ... (write deferred)"`.
  - `False` (default) → unchanged: `ensure_folder` → `move_note` → info log.
  - Both branches return the SAME `RouteResult(state=SHOW_NOTE, action=MOVE, folder_path=path,
    display_path=display)` — RouteResult shape and resolved path are identical, so no path drift
    between resolve and deferred write (T-13-01 mitigation).
- Updated the module "Threat mitigations" docstring note: ensure-before-move still holds on the
  write path; on the deferred path the router performs neither (the caller owns the off-thread write).
- Gating once in the single shared `_do_move` covers all three move entrypoints (archive [X],
  leaf folder, subfolder).

### Task 2 — Router defer_writes unit tests (test_router_unit.py)
- New `TestDeferWritesSeam` class. Structure: `Projects -> (General, Web)`, `Projects/Web ->
  (Frontend,)`, `Areas` leaf root.
- Deferred tests assert `action == MOVE`, the exact resolved `folder_path`, a truthy `display_path`,
  AND `repo.moves == [] and repo.created_folders == []`:
  `test_defer_archive_resolves_without_write`, `test_defer_leaf_folder_resolves_without_write`,
  `test_defer_subfolder_resolves_without_write`, `test_defer_navigation_unaffected`.
- Default tests prove synchronous write: `test_default_writes_archive` (exactly one move + folder
  created) and `test_default_writes_ensure_before_move_order` (call-order spy → `["ensure_folder",
  "move_note"]`).

### Task 3 — SortSession.record_move_failure (session.py + test_session_unit.py)
- Added `record_move_failure(self, note_id: str, message: str) -> None`: scans `self._events` in
  reverse for the most-recent MOVE matching `note_id`; if found, rewrites the event in place to an
  ERROR carrying `message`, decrements `moved` (guarded `> 0`), increments `errors`. If no prior
  move, appends a fresh ERROR and increments `errors` only (moved untouched — never negative).
  Warning-level log on both paths.
- Added `TestRecordMoveFailure` (6 tests) to the EXISTING `test_session_unit.py` (NOT a new file —
  keeps the session 95% coverage floor intact): count conversion, summary reflection, event-rewrite
  in `write_log` (`[ERROR]` + message, no `[MOVE ]  n1`), no-prior-move fresh error, never-negative,
  mixed sequence (`total == 3`), most-recent-move targeting.

## Verification

All commands run via the absolute pixi binary (`~/.pixi/bin/pixi`) because the local shell shim is broken.

| Check | Command | Result |
|-------|---------|--------|
| mypy strict (whole package) | `~/.pixi/bin/pixi run mypy` | PASS — no issues in 22 source files |
| ruff full ruleset | `~/.pixi/bin/pixi run ruff` | PASS — all checks passed |
| ruff format (modified files) | `python -m ruff format` | reformatted (logging line collapses); now clean |
| router + session tests | `pytest tests/sorter/test_router_unit.py tests/sorter/test_session_unit.py -q` | 87 passed |
| router coverage gate | `pytest tests/sorter/test_router_unit.py --cov=notes_os.sorter.router --cov-fail-under=95 -q` | PASS — **99.07%** (55 passed) |
| session coverage gate | `pytest tests/sorter/test_session_unit.py --cov=notes_os.sorter.session --cov-fail-under=95 -q` | PASS — **98.61%** (32 passed) |
| CLI path unchanged | `pytest tests/sorter/test_controller_integration.py -q` | 6 passed |
| full unit suite | `pytest -m 'not integration' -q` | 394 passed, 6 deselected |

`build_default_controller` (controller.py:414) confirmed still `Router(repo=repo, config=config)` —
no `defer_writes` arg, uses the `False` default → CLI writes synchronously (T-13-02 mitigation).

## Threat model coverage
- T-13-01 (path drift): deferred branch returns the identical resolved path — covered by the three
  `test_defer_*_resolves_without_write` exact-path assertions.
- T-13-02 (CLI silent breakage): default-write tests + unchanged `build_default_controller` +
  green controller integration suite.
- T-13-03 (count loss): `record_move_failure` decrements `moved`, increments `errors`, rewrites the
  event to `[ERROR]` — covered by the count-conversion + log-rewrite tests.
- T-13-04 (negative count): guarded `moved > 0` + fresh-error fallback — covered by
  `test_no_prior_move_records_fresh_error` and `test_count_never_goes_negative`.
- T-13-SC: no new dependencies introduced — package-legitimacy gate not applicable.

## Deviations from Plan
None — plan executed exactly as written. (Ruff auto-format collapsed two multi-line `logger.warning`
calls and one `Router(...)` test call to single lines after line-length allowed it; no semantic change.)

## Known Stubs
None.

## Self-Check: PASSED
- src/notes_os/sorter/router.py — FOUND (contains `defer_writes`, `self._defer_writes`, gated `_do_move`)
- src/notes_os/sorter/session.py — FOUND (contains `def record_move_failure`)
- tests/sorter/test_router_unit.py — FOUND (`TestDeferWritesSeam`)
- tests/sorter/test_session_unit.py — FOUND (`TestRecordMoveFailure`)
- No commits made (per execution_context: orchestrator commits; changes left unstaged).
