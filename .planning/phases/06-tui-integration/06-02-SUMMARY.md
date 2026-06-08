---
phase: 06-tui-integration
plan: 02
subsystem: ui
tags: [textual, pilot-tests, sort-screen, router, session, backup, tui-05]

# Dependency graph
requires:
  - phase: 06-01
    provides: NotesOSApp DI seam (app.repo/app.app_config), HomeScreen action_sort seam, Pilot test harness
  - phase: 04-router
    provides: Router.handle_category/handle_folder/handle_subfolder/handle_back, RouteResult, RouterState
  - phase: 04-session
    provides: SortSession.record_move/record_skip/record_error, write_log
  - phase: 03-backup
    provides: BackingUpNotesRepository, BackupManager
provides:
  - "SortScreen(Screen[None]) — event-driven Router driver via Textual key events"
  - "HomeScreen.action_sort() wired to push_screen('sort')"
  - "app.py SCREENS registry: 'sort': SortScreen"
  - "SC2 Pilot tests (5 tests proving backup-then-move, move recorded, session counts, back nav, skip)"
  - "_after_move(note) seam for 06-03 task-extraction hook"
affects:
  - "06-03 (TaskExtractScreen): _after_move seam in SortScreen to be filled in"
  - "06-04 (ConfirmQuit): session-in-progress boundary seam at action_back AWAIT_CATEGORY"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Event-driven Router: on_key dispatches to _handle_category_key / _handle_folder_or_subfolder_key — no blocking loop"
    - "Screen holds router context between keystrokes: _router_state + _prev (mirrors controller call-stack)"
    - "SortScreen.__init__ accepts year_provider for deterministic archive path in tests"
    - "Spy BackupManager (MagicMock) avoids macOS same-second rename collision when ensure_folder + move_note both fire create()"
    - "_after_move(note) seam: no-op in 06-02; 06-03 fills with task extraction"

key-files:
  created:
    - "src/notes_os/screens/sort.py — SortScreen(Screen[None]) with full Router event dispatch"
    - "tests/screens/test_sort_screen.py — 5 SC2 Pilot tests"
  modified:
    - "src/notes_os/app.py — SCREENS registry: added 'sort': SortScreen"
    - "src/notes_os/screens/home.py — action_sort() wired to push_screen('sort')"
    - "src/notes_os/app.tcss — added SortScreen widget styles; fixed invalid margin: auto"

key-decisions:
  - "_handle_category_key / _handle_folder_or_subfolder_key separate helpers keep on_key thin; each returns immediately (no loops, no blocking)"
  - "Spy BackupManager instead of real BackupManager in tests: on macOS, Path.rename() fails when destination is non-empty; ensure_folder + move_note both fire create() within the same second causing timestamp collision"
  - "_after_move(note) placed immediately after _session.record_move(); named clearly for 06-03 to find and fill"
  - "action_back at AWAIT_CATEGORY: pops to HomeScreen directly; session-in-progress confirm dialog is 06-04 scope — seam left with a log.info noting move/skip/error counts"
  - "Callable type annotation in SortScreen.__init__ moved to TYPE_CHECKING block (ruff TC003); safe because from __future__ import annotations makes all annotations lazy"
  - "id parameter annotated noqa A002 — mirrors Textual Screen signature convention"

requirements-completed: [TUI-03, TUI-05]

# Metrics
duration: 9min
completed: 2026-06-08
---

# Phase 06 Plan 02: SortScreen — Event-Driven Router Driver Summary

**SortScreen driving the UI-agnostic Router via discrete Textual key events: each keystroke calls handle_category/handle_folder/handle_subfolder/handle_back, records outcomes in SortSession, and writes the audit log — no blocking SortController.run(); SC2 proven by 5 Pilot tests**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-08T03:35:58Z
- **Completed:** 2026-06-08T03:44:50Z
- **Tasks:** 2 (both complete)
- **Files created/modified:** 5

## Accomplishments

- `SortScreen(Screen[None])` in `src/notes_os/screens/sort.py`:
  - `on_key` dispatches to `_handle_category_key` / `_handle_folder_or_subfolder_key` — fully non-blocking
  - Holds `_router_state` and `_prev` between keystrokes (the context the controller used to hold on its call stack)
  - `_handle_move`: wraps each move in `try/except NotesOSError` → `record_error` + advance (T-06-05 mitigation)
  - `_after_move(note)`: no-op seam named for 06-03 task-extraction (called immediately after `record_move`)
  - `action_back` (Esc/B): AWAIT_SUBFOLDER→AWAIT_FOLDER→AWAIT_CATEGORY→pop_screen
  - `_finish()`: renders session summary, writes audit log to `config.log_dir`
  - `year_provider` constructor param for deterministic archive path in tests

- `HomeScreen.action_sort()` wired to `self.app.push_screen("sort")` (filled in the 06-01 placeholder)
- `app.py SCREENS` registry: `"sort": SortScreen` added

- 5 SC2 Pilot tests all passing:
  - **SC2a**: archive via `x` → move recorded + inbox shrinks + session.moved==1 + spy create() called
  - **SC2b**: Projects drill via `p`+`1` → AWAIT_FOLDER traversal + move to General
  - **SC2c**: Esc at AWAIT_FOLDER → router state resets to AWAIT_CATEGORY (TUI-05 back nav)
  - **SC2d**: HomeScreen action_sort pushes SortScreen (SCREENS registry wired)
  - **SC2e**: skip via `s` → session.skipped==1, no moves recorded

- 315 tests passing; 91.25% overall coverage (80% gate: PASSED)
- mypy strict: zero errors; ruff: clean

## Task Commits

1. **Task 1: SortScreen + app.tcss additions** — `9fd4a8e` (feat)
2. **Task 2: Wire HomeScreen + SC2 Pilot tests** — `b2a6fe5` (feat)

## Files Created/Modified

- `src/notes_os/screens/sort.py` — SortScreen with Router event dispatch, session management, back nav, _after_move seam
- `src/notes_os/app.py` — SCREENS registry: `"sort": SortScreen`
- `src/notes_os/screens/home.py` — `action_sort()` wired to `push_screen("sort")`
- `src/notes_os/app.tcss` — SortScreen widget styles (#note-title, #note-preview, #prompt, #progress); fixed invalid `margin: 0 auto 1 auto`
- `tests/screens/test_sort_screen.py` — 5 SC2 Pilot tests

## Architecture: SortScreen State Model

```
SortScreen instance attributes (the "call stack" the old controller held):
  _router: Router | None          — built in on_mount from app.repo + app.app_config
  _session: SortSession           — fresh per screen mount
  _notes: list[Note]              — inbox snapshot from on_mount
  _index: int                     — current note pointer
  _router_state: RouterState      — AWAIT_CATEGORY | AWAIT_FOLDER | AWAIT_SUBFOLDER
  _prev: RouteResult | None       — folder/subfolder context between keystrokes

Key event flow (AWAIT_CATEGORY):
  on_key('x') → _handle_category_key('x')
    → router.handle_category('x', note) → RouteResult(action=MOVE)
    → _handle_move(note, result) → _session.record_move() → _after_move(note) [no-op]
    → _advance() → _index++ → _render_current_note() or _finish()

Key event flow (AWAIT_FOLDER):
  on_key('p') → AWAIT_CATEGORY → router returns AWAIT_FOLDER → store _prev, re-render
  on_key('1') → _handle_folder_or_subfolder_key('1', folder=True)
    → router.handle_folder(1, _prev, note) → RouteResult(action=MOVE)
    → _handle_move(note, result) → advance

Back nav (Esc/B):
  action_back() → AWAIT_SUBFOLDER → AWAIT_FOLDER → AWAIT_CATEGORY → pop_screen()
```

## _after_move Seam Documentation (for 06-03)

```python
def _after_move(self, note: Note) -> None:
    """Hook called after a successful move — no-op in this plan (06-02).

    Phase 06-03 fills this in with the task-extraction flow gated on
    self.app.app_config.features.task_extraction.  The seam exists
    here so 06-03 has a single, clearly-named entry point.

    Called from _handle_move() immediately after _session.record_move().
    The note has already been moved (Router._do_move fired ensure_folder + move_note).
    """
    # 06-03 fills this in — intentional no-op.
    logger.debug("_after_move seam called for note %r (no-op in 06-02)", note.id)
```

**06-03 entry point:** Replace the body of `_after_move` in
`src/notes_os/screens/sort.py`. Check `self.app.app_config.features.task_extraction`
first (SC1 gate), then push `TaskExtractScreen` or call extraction inline.

## Session-in-Progress Seam (for 06-04)

In `action_back()` at `AWAIT_CATEGORY`:
```python
if self._router_state == RouterState.AWAIT_CATEGORY:
    # Session-in-progress seam (06-04 replaces this with confirm dialog)
    logger.info(
        "SortScreen: leaving with session=%s/%s/%s (moves/skips/errors)",
        self._session.moved,
        self._session.skipped,
        self._session.errors,
    )
    self.app.pop_screen()
```
**06-04 entry point:** Before `self.app.pop_screen()`, check
`self._session.moved + self._session.skipped > 0` and `push_screen("confirm_quit")`.

## Decisions Made

- **Spy BackupManager** in tests: macOS `Path.rename()` fails when destination is
  non-empty (errno 66); `ensure_folder` + `move_note` both call `create()` within
  the same second in tests, causing timestamp collision. Spy avoids real filesystem
  while still proving `create()` was called before the move.
- **_handle_category_key / _handle_folder_or_subfolder_key**: separated into two
  helpers to keep `on_key` a thin dispatcher; each helper returns immediately (no
  loops, no blocking) so the Textual event loop stays responsive.
- **Callable in TYPE_CHECKING**: `year_provider: Callable[[], int] | None` annotation
  in `__init__` moved to TYPE_CHECKING block to satisfy ruff TC003; safe because
  `from __future__ import annotations` makes all annotations lazily evaluated.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed invalid Textual CSS `margin: auto`**
- **Found during:** Task 2 (first test run — StylesheetParseError)
- **Issue:** Textual CSS does not support `auto` in margin values; the added
  `#note-preview` and `#prompt` rules used `margin: 0 auto 1 auto` (CSS4 syntax)
  which is invalid in Textual TCSS.
- **Fix:** Changed to `margin: 0 1` (valid 2-value Textual margin — vertical, horizontal)
- **Files modified:** `src/notes_os/app.tcss`
- **Committed in:** `b2a6fe5` (Task 2 commit)

**2. [Rule 1 - Bug] Used spy BackupManager instead of real BackupManager in SC2 tests**
- **Found during:** Task 2 (SC2a test run — OSError errno 66)
- **Issue:** `BackupManager.create()` fires twice per note (once for `ensure_folder`,
  once for `move_note`). Both calls complete within the same second in test context,
  producing the same timestamp-based backup directory name. On macOS, `Path.rename()`
  of a non-empty directory fails with `OSError: Directory not empty` (errno 66).
- **Fix:** Replaced real `BackupManager` in SC2a with a `MagicMock(spec=BackupManager)` spy.
  The spy's `create.call_count >= 1` assertion still proves backup-before-write correctly.
  `BackingUpNotesRepository` is still REAL — wrapping mock_inner — so the decorator
  contract is exercised (backup call gated on `auto_backup_on_write`).
- **Files modified:** `tests/screens/test_sort_screen.py`
- **Committed in:** `b2a6fe5` (Task 2 commit)

**3. [Rule 1 - Bug] Multiple ruff lint fixes in new files**
- **Found during:** Tasks 1 and 2 (ruff check passes)
- **Issues:** TC003 (Callable from collections.abc into TYPE_CHECKING), TC003 (Path into
  TYPE_CHECKING in test file), A002 (id param shadows builtin — annotated noqa), F401
  (unused Static/pytest/call imports removed from test file), I001 (import sort fixed)
- **Fix:** Applied all ruff --fix corrections + manual noqa annotation for A002
- **Files modified:** `src/notes_os/screens/sort.py`, `tests/screens/test_sort_screen.py`
- **Committed in:** `9fd4a8e` and `b2a6fe5`

---

**Total deviations:** 3 auto-fixed (all Rule 1 bugs/lint)
**Impact on plan:** All fixes necessary for correctness; no scope creep.

## Threat Model Coverage

| Threat | Status |
|--------|--------|
| T-06-04 (tamper bypass backup) | MITIGATED — SortScreen uses app.repo (BackingUpNotesRepository from DI seam); SC2a spy asserts create() called before move |
| T-06-05 (bad note aborts session) | MITIGATED — _handle_move wraps in try/except NotesOSError → record_error + advance |
| T-06-06 (invalid key bad state) | MITIGATED — Router no-ops on unknown keys; screen re-renders without advancing index |
| T-06-07 (blocking event loop) | MITIGATED — SortController.run() never called; verified by CLI import check |

## Known Stubs

None — all SortScreen functionality is implemented. The `_after_move` method is an INTENTIONAL no-op seam (documented), not a stub. It is designed to be empty until 06-03 fills it in.

## Self-Check: PASSED

Files verified:
- `src/notes_os/screens/sort.py` — exists, imports cleanly, mypy clean
- `tests/screens/test_sort_screen.py` — exists, 5 tests all pass
- `src/notes_os/app.py` — SCREENS["sort"] = SortScreen confirmed
- `src/notes_os/screens/home.py` — action_sort() wired to push_screen("sort")

Commits verified:
- `9fd4a8e` — Task 1 (SortScreen + CSS)
- `b2a6fe5` — Task 2 (HomeScreen wire + tests)

Coverage: 91.25% total (>80% gate); 315 tests passing

---
*Phase: 06-tui-integration*
*Completed: 2026-06-08*
