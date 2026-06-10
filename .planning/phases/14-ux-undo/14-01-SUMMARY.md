---
phase: 14-ux-undo
plan: 01
subsystem: sorter/session
tags: [undo, session, ux-02, value-object, lifo]
requires:
  - notes_os.sorter.session.SortSession (existing counters + event history + record_move_failure)
  - notes_os.sorter.models.FolderPath
provides:
  - notes_os.sorter.session.UndoEntry  # frozen Pydantic V2 value object
  - notes_os.sorter.session.SortSession._undo_stack  # LIFO list[UndoEntry]
  - notes_os.sorter.session.SortSession.pop_undo  # -> UndoEntry | None, reverses counters
  - record_move(*, source_path=None, index=0)  # keyword-only, backward compatible
  - record_skip(*, index=0)  # keyword-only, backward compatible
affects:
  - Plan 14-02 (SortScreen wiring) consumes UndoEntry + pop_undo
tech-stack:
  added: []
  patterns:
    - Frozen Pydantic V2 model as undo value object (model_config = ConfigDict(frozen=True))
    - Runtime FolderPath import (out of TYPE_CHECKING) for Pydantic model build
    - Keyword-only params with defaults to preserve ~30 positional call sites
key-files:
  created: []
  modified:
    - src/notes_os/sorter/session.py
    - tests/sorter/test_session_unit.py
decisions:
  - "Errored-event rule: only successful record_move/record_skip push an UndoEntry; record_error pushes nothing; record_move_failure pushes nothing AND removes the reconciled move's UndoEntry."
  - "pop_undo does NO I/O — it only reverses the session counter LIFO and returns the entry; the Wave-2 screen performs the actual move-back write."
  - "errors is never reversed by pop_undo (errored/failed moves are not undoable)."
  - "Audit log kept append-only — the original MOVE/SKIP _NoteEvent line is preserved; pop_undo does not rewrite/remove events."
metrics:
  duration: ~12m
  completed: 2026-06-09
---

# Phase 14 Plan 01: SortSession Undo Stack Summary

Added a session-owned, UI-agnostic LIFO undo stack to `SortSession` so the most-recent
skip or move can be reversed repeatably and unbounded within a session (UX-02), with a
frozen `UndoEntry` value object and a pure `pop_undo()` contract for the Wave-2 screen.

## What Was Built

**`UndoEntry` (frozen Pydantic V2 model)** — fields:
`note_id: str`, `kind: str` (the `_KIND_MOVE="move"` / `_KIND_SKIP="skip"` module
constants — no magic strings), `source_path: FolderPath | None = None`,
`dest_path: FolderPath | None = None`, `index: int`. The `source_path` is captured at
move time so a later undo can move the note back; `index` is the inbox position the
screen steps back to and is stored verbatim (the session never interprets it).

**`SortSession._undo_stack: list[UndoEntry]`** — initialised empty in `__init__`.

**`pop_undo(self) -> UndoEntry | None`** — pops the top entry LIFO and reverses its
counter (`move` → `moved`, `skip` → `skipped`), each decrement guarded with `> 0` so a
stray/duplicate call can never go negative. Empty stack → returns `None`, counters
untouched. Performs NO I/O. `errors` is intentionally never reversed.

**Push wiring** — `record_move` and `record_skip` push exactly one `UndoEntry` on
success. The new params are keyword-only with defaults
(`record_move(..., *, source_path=None, index=0)`, `record_skip(..., *, index=0)`) so
the ~30 existing positional call sites and the CLI `SortController` keep compiling
unchanged.

**Errored-event rule** — `record_error` pushes nothing (unchanged). `record_move_failure`
pushes nothing AND removes the most-recent matching move `UndoEntry`
(`note_id` + `kind == _KIND_MOVE`) via the new private helper `_remove_move_undo_entry`,
so a move that never actually landed can never be undone (no-op if already popped). The
existing event-reconciliation behaviour (rewrite MOVE→ERROR, decrement `moved`, increment
`errors`) is preserved byte-for-byte.

**Import change** — `FolderPath` moved out of the `TYPE_CHECKING` block to a runtime
import (with `# noqa: TC001` matching `router.py`) because Pydantic must resolve the
annotation at model-build time. The now-empty `TYPE_CHECKING` block and its `typing`
import were removed.

## The pop_undo Contract (for Plan 14-02)

```
entry = session.pop_undo()   # None when nothing to undo (screen shows "nothing to undo")
# entry.kind == "move" -> move note back from entry.dest_path to entry.source_path
# entry.kind == "skip" -> just step the inbox index back
# entry.index          -> the inbox position to step to
# pop_undo already reversed the session counter; the screen does the write + index step.
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed unused `# noqa: SLF001` directives in tests**
- **Found during:** Task 2 (ruff check)
- **Issue:** The plan's behavior cases needed two tests that inject directly into
  `session._undo_stack` to exercise the defensive `> 0` guard. I initially annotated the
  private-access lines with `# noqa: SLF001`, but `SLF001` is not in this repo's enabled
  ruleset, so ruff flagged them as `RUF100` unused-noqa errors.
- **Fix:** Removed the `# noqa` comments (private access in tests is not flagged here).
- **Files modified:** tests/sorter/test_session_unit.py
- **Commit:** unstaged (orchestrator commits)

**2. [Rule 3 - Blocking] Ran `ruff format` to satisfy the CI format-check gate**
- **Found during:** Task 2 (`.pixi/envs/default/bin/ruff format --check`)
- **Issue:** New test code triggered a format diff (the CI-only format gate the plan
  explicitly guards against).
- **Fix:** `.pixi/envs/default/bin/ruff format src tests`; re-verified `--check` clean.
- **Files modified:** tests/sorter/test_session_unit.py
- **Commit:** unstaged

No behavioural deviations — the session contract matches the plan exactly.

## Verification

| Gate | Command | Result |
|------|---------|--------|
| Session tests + coverage | `~/.pixi/bin/pixi run pytest tests/sorter/test_session_unit.py --cov=notes_os.sorter.session --cov-fail-under=95 -q` | 44 passed, **99%** coverage (gate 95%) |
| mypy strict | `~/.pixi/bin/pixi run mypy` | Success: no issues found in 22 source files |
| ruff check | `~/.pixi/bin/pixi run ruff` | All checks passed |
| ruff format (CI parity) | `.pixi/envs/default/bin/ruff format --check src tests` | 48 files already formatted |
| Backward-compat (full non-integration) | `~/.pixi/bin/pixi run pytest -m 'not integration' -q` | **415 passed**, 6 deselected |

Session module coverage: **99%** (the single uncovered line, 397, is the pre-existing
`now = datetime.now()` default branch in `write_log`, unrelated to this plan). The
keyword-only params did not break any existing call site — the controller and session
suites are green in the full 415-test run.

## Self-Check: PASSED

- `src/notes_os/sorter/session.py` — FOUND, contains `def pop_undo`, `class UndoEntry`,
  `_undo_stack`, `_remove_move_undo_entry`.
- `tests/sorter/test_session_unit.py` — FOUND, contains the undo push/pop/LIFO/guard/
  errored-event/empty-pop tests.
- No commits made (orchestrator owns commits per execution context).
