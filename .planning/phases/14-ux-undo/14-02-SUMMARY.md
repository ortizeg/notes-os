---
phase: 14-ux-undo
plan: 02
subsystem: screens/sort
tags: [undo, ux-02, sort-screen, binding, off-thread-write, move-back]
requires:
  - notes_os.sorter.session.UndoEntry  # 14-01 frozen value object
  - notes_os.sorter.session.SortSession.pop_undo  # 14-01 LIFO counter reversal
  - notes_os.sorter.session._KIND_MOVE / _KIND_SKIP  # 14-01 kind discriminators
  - record_move(*, source_path=None, index=0) / record_skip(*, index=0)  # 14-01 kw-only params
  - SortScreen._enqueue_write / _drain_write_queue / _on_write_failed / _failed_moves  # Phase-13 serialized write plumbing
  - notes_os.config.SorterConfig.bridge.inbox_folder  # move-back origin
provides:
  - notes_os.screens.sort.SortScreen.action_undo  # U/u Binding target, state-guarded
  - notes_os.screens.sort.SortScreen._handle_undo  # pop + apply reversal on screen
  - notes_os.screens.sort.SortScreen._inbox_folder_path  # captured move-back origin
  - notes_os.screens.sort._NOTHING_TO_UNDO  # empty-stack notify hint constant
  - MockNotesRepository move-back modeling (_moved_out re-add)  # tests/sorter/conftest.py
affects:
  - Phase 15 (Resume) reuses the same Phase-13 _enqueue_write path
tech-stack:
  added: []
  patterns:
    - Footer Binding + action_* target (NO on_key branch) to avoid double-fire (mirrors escape/b → action_back)
    - action_* state guards (_loading / _inbox_empty / non-AWAIT_CATEGORY) since Textual actions fire regardless of router state
    - Move-back routed through the EXISTING Phase-13 serialized off-thread drainer (never a synchronous on-loop write)
    - Source FolderPath captured on the UndoEntry at move time (not recomputed) so the move-back targets the true origin
    - Mock move_note state machine (inbox → move-out → _moved_out → move-back re-adds) to make the move-undo assertion satisfiable
key-files:
  created: []
  modified:
    - src/notes_os/screens/sort.py
    - tests/sorter/conftest.py
    - tests/screens/test_sort_screen.py
decisions:
  - "U is driven ONLY by the footer Binding + action_undo — NO on_key branch for u/U (would double-fire; mirrors the escape/b → action_back precedent)."
  - "action_undo guards on _loading / _inbox_empty / non-AWAIT_CATEGORY before dispatching; _inbox_empty covers BOTH the empty inbox AND the post-_complete_finish summary state, so U on a finished session is a no-op (T-14-07)."
  - "The move-back is enqueued via _enqueue_write (FIFO, single-writer, backup-latch-safe) — the same path the Phase-13 docstring reserved for Phase 14; failures flow through the existing _on_write_failed with no bespoke handling (T-14-05)."
  - "Skip-undo is index-only (no write) — the skipped note was never removed from _refs, so stepping _index back re-shows it."
  - "The move-back destination is the SOURCE FolderPath captured on the UndoEntry (entry.source_path), falling back to the configured inbox only defensively — move-back targets the true origin (T-14-08)."
  - "MockNotesRepository.move_note gained a move-back model (B1 fix): a tracked moved-out note re-adds to the inbox on re-move, so the move-undo test's 'note back in get_inbox_notes()' assertion is satisfiable. The folder-known check now precedes the inbox-membership check; this only changes the unknown-id+unknown-path corner (no test exercises it) and keeps move-out byte-identical."
metrics:
  duration: ~18m
  completed: 2026-06-09
---

# Phase 14 Plan 02: SortScreen Undo (U) Wiring Summary

Wired the user-facing **Undo (`U`/`u`)** into `SortScreen`, completing UX-02 end-to-end on top
of the 14-01 session-level undo stack. Pressing `U` pops the most-recent `UndoEntry`, reverses it
on screen, and — for a moved note — issues the move-back through the EXISTING Phase-13 serialized
off-thread write queue (never a synchronous on-event-loop write).

## What was built

- **`U`/`u` binding (W1 fix):** `Binding("u", "undo", "Undo", show=True)` added to `BINDINGS`
  with an `action_undo` target. NO `on_key` branch for `u`/`U` — that would fire undo twice (once
  via the binding's `action_undo`, once via the on_key branch). This mirrors the existing
  `escape`/`b` → `action_back` precedent exactly.
- **`action_undo` state guards:** because Textual `action_*` methods fire regardless of router
  state, `action_undo` returns a no-op when `_loading`, when `_inbox_empty` (covers the empty
  inbox AND the post-`_complete_finish` summary state), or at any router state other than
  `AWAIT_CATEGORY`. Only when every guard passes does it delegate to `_handle_undo`.
- **`_handle_undo`:** pops `_session.pop_undo()` (which already reversed the counter LIFO with
  `> 0` guards). On `None` (empty stack) it surfaces the `_NOTHING_TO_UNDO` hint and returns with
  zero index/counter change. Otherwise it branches on `entry.kind`:
  - **MOVE:** resolves the destination from `entry.source_path` (defensive fallback to the
    configured inbox), enqueues the move-back via `_enqueue_write(note_id, dest, display)`, then
    steps `_index` back, resets router state, and re-renders.
  - **SKIP:** index-only — steps `_index` back, resets router state, re-renders. No write.
- **Source/index capture at move/skip time:** `_handle_move` now passes
  `record_move(note_id, folder_path, source_path=<inbox FolderPath>, index=<moved note's index>)`
  and the skip path passes `record_skip(note.id, index=<skipped note's index>)`, captured BEFORE
  `_advance` changes `_index`.
- **`_inbox_folder_path` helper:** returns `(app.app_config.bridge.inbox_folder,)` — the captured
  move-back origin (carried on the entry, not hardcoded into the move-back).
- **`_NOTHING_TO_UNDO` constant + `_HELP_TEXT` legend line** (`U  Undo last action`).
- **`MockNotesRepository` move-back model (B1 fix):** a `_moved_out` dict tracks notes moved out
  of the inbox; a re-move of a tracked note re-adds it to the inbox so the undo move-back restores
  inbox membership.

## How the move-back reuses the Phase-13 queue

The move-back goes through `_enqueue_write` → `_drain_write_queue` — the SAME single-writer,
FIFO, backup-latch-safe drainer used by ordinary moves. `ensure_folder` is issued before
`move_note`, so the inbox destination is registered/exists. A move-back that fails off-thread is
caught per-item by the drainer and marshalled to the EXISTING `_on_write_failed` (records the
error via `record_move_failure`, tracks it in `_failed_moves`, notifies) — no bespoke failure
path. Since `pop_undo` already decremented `moved`, the net on undo-failure is non-negative,
consistent counts and a live TUI.

## Five Pilot tests → UX-02 success criteria

| Test | UX-02 criterion |
|------|-----------------|
| `test_move_then_undo_restores_note_count_and_position` | SC1 — undo of a move returns the note to the inbox and back into sort position; `moved` decrements; move-back to `("Notes",)` recorded (via the Phase-13 queue) |
| `test_skip_then_undo_steps_back_no_write` | SC2 — undo of a skip steps back (no write); `skipped` decrements |
| `test_undo_repeatable_to_session_start` | SC3 — `U` repeatable LIFO to session start; third press is a no-op |
| `test_undo_empty_stack_is_noop_with_hint` | SC4 — empty-stack `U` is a no-op with the `_NOTHING_TO_UNDO` hint |
| `test_undo_move_back_failure_surfaced_without_corruption` | T-14-05 — failed move-back surfaced via `_on_write_failed` without crash or count corruption |

SC5 (source captured at move time) is proven by the move-undo test asserting the move-back target
is the captured `("Notes",)` path.

The move-undo / skip-undo / repeatable / failure tests seed a trailing note so the session stays
OPEN after the first action — a single-note inbox finishes the session and sets
`_inbox_empty=True`, where `U` is correctly a no-op (T-14-07). This is the intended interaction,
verified by the guard.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reordered the mock's folder-known check before the inbox-membership check**
- **Found during:** Task 2, STEP 0 (mock move-back extension)
- **Issue:** The move-back branch needs the destination path to be known; keeping the original
  inbox-first / folder-second order was fine, but the cleanest move-back state machine checks the
  folder first so an unknown-path move-back fails as `FolderNotFoundError` consistently.
- **Fix:** `move_note` now validates `folder_path in _known_paths` first, then branches on inbox
  membership (move-out) / `_moved_out` membership (move-back) / unknown id (`NotesMoveError`).
- **Impact:** Only changes the unknown-id + unknown-path corner (no test exercises it). The
  controller-integration test (in-inbox note + unknown folder) still raises `FolderNotFoundError`;
  move-out behaviour is byte-identical. Verified by re-running the sorter + full suite.
- **Files modified:** tests/sorter/conftest.py

**2. [Test design] Seeded a trailing note in four undo tests**
- **Found during:** Task 2 (move-undo test initially failed — `moved` stayed 1)
- **Issue:** A single-note inbox finishes the session on the first move/skip, setting
  `_inbox_empty=True`, where `action_undo` is (correctly) a no-op.
- **Fix:** the move/skip/repeatable/failure tests seed a trailing note so the session stays open
  and `U` is dispatched. The empty-stack test keeps its single note (it never advances).
- **Files modified:** tests/screens/test_sort_screen.py

## Verification

All commands run via the absolute pixi binary (local shim broken):

- `~/.pixi/bin/pixi run pytest tests/screens/test_sort_screen.py -x -q` → **28 passed**
- `~/.pixi/bin/pixi run pytest -m 'not integration' -q` → **420 passed, 6 deselected**
- `~/.pixi/bin/pixi run mypy` → **Success: no issues found in 22 source files**
- `~/.pixi/bin/pixi run ruff` → **All checks passed!**
- `.pixi/envs/default/bin/ruff format --check src tests` → **48 files already formatted**

`sort.py` undo paths (`action_undo`, `_handle_undo`, `_inbox_folder_path`) are exercised by the
five Pilot tests; overall coverage gate (`--cov-fail-under=80`) passes.

## Self-Check: PASSED

- `src/notes_os/screens/sort.py` — FOUND (`action_undo`, `_handle_undo`, `_inbox_folder_path`, `_NOTHING_TO_UNDO`, `U` binding)
- `tests/sorter/conftest.py` — FOUND (move-back model: `_moved_out`)
- `tests/screens/test_sort_screen.py` — FOUND (five Phase-14 undo Pilot tests)
- All verification gates green (see above).
