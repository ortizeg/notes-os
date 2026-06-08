---
phase: 06-tui-integration
plan: 03
subsystem: ui
tags: [textual, pilot-tests, task-extraction, modal-screen, sort-screen, tui-04, tui-05]

# Dependency graph
requires:
  - phase: 06-02
    provides: SortScreen._after_move no-op seam; app.repo/app.app_config DI seam
  - phase: 05-task-extraction
    provides: extract_tasks(), TaskWriter, ExtractedTask — reused directly, not reimplemented
  - phase: 06-01
    provides: NotesOSApp DI seam, SCREENS registry, tui_config/tui_repo fixtures
provides:
  - "TaskExtractScreen(ModalScreen[list[ExtractedTask]]): post-move task review modal"
  - "SortScreen._after_move filled: gated on task_extraction (SC1/T-06-08); deferred push via app.call_after_refresh"
  - "SC3 Pilot tests: enabled write path + off-by-default + skip — 3 tests all passing"
  - "app.py SCREENS registry: 'task_extract': TaskExtractScreen added"
affects:
  - "06-04 (ConfirmQuit): no changes to _after_move seam needed; session-in-progress seam unchanged"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "app.call_after_refresh for deferred push_screen: avoids key-event collision where routing key propagates to newly-mounted ModalScreen and triggers immediate dismiss — schedule on App message pump, not Screen pump (Screen gets ScreenSuspend before InvokeLater fires)"
    - "ModalScreen[T] with no Header/Footer: Textual Header widget fires async _on_mount that queries HeaderTitle via NoMatches when mounted as modal; modals use Static-only layout"
    - "_after_move returns bool: True = extraction deferred (modal pushed, advance via callback); False = advance immediately"
    - "Dismiss callback _on_tasks_resolved(selected | None) calls _advance() so sort loop continues after task review"

key-files:
  created:
    - "src/notes_os/screens/task_extract.py — TaskExtractScreen(ModalScreen) with A/S/X/Esc/? bindings, SelectionList, TaskWriter.write on confirm"
    - "tests/screens/test_task_extract_screen.py — 3 SC3 Pilot tests proving SC3a/SC3b/SC3c"
  modified:
    - "src/notes_os/screens/sort.py — _after_move filled; _handle_move restructured to conditional advance; _on_tasks_resolved callback added; extract_tasks import added"
    - "src/notes_os/app.py — SCREENS registry: 'task_extract': TaskExtractScreen"
    - "src/notes_os/app.tcss — TaskExtractScreen modal styles (#task-header, #task-list, #task-legend)"

key-decisions:
  - "app.call_after_refresh instead of self.call_after_refresh: SortScreen gets ScreenSuspend when push_screen fires; screen message pump stops processing InvokeLater before it fires. App-level message pump stays running and reliably fires the deferred push."
  - "No Header/Footer in ModalScreen: Textual's Header._on_mount fires an async callback that does query_one(HeaderTitle) which fails with NoMatches in modal context; use Static widgets only for modal layout."
  - "_after_move returns bool instead of None: avoids needing an instance variable to track extraction state; _handle_move can decide advance vs defer inline."
  - "TaskWriter.write() called inside TaskExtractScreen._write_and_dismiss: simpler than passing write responsibility to the callback; dismiss result is the list of selected tasks for test assertion."
  - "Two pilot.pause() calls after routing keystroke: first pause allows call_after_refresh InvokeLater to fire (push_screen); second pause waits for modal to mount and become app.screen."

requirements-completed: [TUI-04, TUI-05]

# Metrics
duration: 10min
completed: 2026-06-08
---

# Phase 06 Plan 03: TaskExtractScreen + SortScreen._after_move Wiring Summary

**TaskExtractScreen modal with A/S/X/Esc selection (mirroring SortUIProtocol.prompt_task_selection), wired into SortScreen._after_move via app.call_after_refresh to avoid key-event collision, gated on config.features.task_extraction — SC3 proven by 3 Pilot tests**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-08T03:48:33Z
- **Completed:** 2026-06-08T03:58:51Z
- **Tasks:** 2 (both complete)
- **Files created/modified:** 5

## Accomplishments

- `TaskExtractScreen(ModalScreen[list[ExtractedTask]])` in `src/notes_os/screens/task_extract.py`:
  - Constructor receives pre-extracted `tasks: list[ExtractedTask]` + `writer: TaskWriter`
  - `SelectionList[int]` with numbered task items; keyboard-navigable
  - **A** (Add all): `_write_and_dismiss(all_tasks)` — calls `TaskWriter.write()` + dismiss
  - **S** (Select): activates `_select_mode_active`; Enter in select mode confirms subset
  - **X** / **Esc** (Skip): `dismiss([])` — no write
  - **?** (Help): `action_help()` shows key legend notification (TUI-05)
  - No Pydantic model → no pyproject mypy-override entry needed
  - No Header/Footer (Textual Header._on_mount fails with NoMatches in modal context)

- `SortScreen._after_move(note) -> bool` fills the 06-02 no-op seam:
  - First line: `if not task_extraction: return False` — SC1/T-06-08 gate; byte-identical to 06-02 on disabled path; no extractor/writer/screen access on disabled branch
  - `extract_tasks(note.preview)` — pure fast call
  - If no tasks: `return False` (advance immediately)
  - If tasks found: `app.call_after_refresh(app.push_screen, modal, callback)` — deferred push on App message pump avoids key-event collision; returns `True` so `_handle_move` skips immediate `_advance()`
  - `_on_tasks_resolved(selected | None)`: Textual dismiss callback calls `_advance()` to continue sort flow

- 3 SC3 Pilot tests all passing:
  - **SC3a (enabled write)**: task_extraction=True + action-phrase note → archive 'x' → TaskExtractScreen appears (after 2 pauses) → press 'a' → daily .md file contains `- [ ] ` checkbox with extracted text
  - **SC3b (off-by-default)**: task_extraction=False → archive 'x' → no modal, flow advances, no file written
  - **SC3c (skip)**: task_extraction=True → archive 'x' → modal → press 'x' (Skip) → no file written, advance

- 318 tests passing; 90.71% overall coverage (80% gate: PASSED)
- mypy strict: zero errors; ruff: clean
- extractor.py: UNMODIFIED (verified via git diff)

## Task Commits

1. **Task 1: TaskExtractScreen modal + app.tcss task modal styles** — `6198153` (feat)
2. **Task 2: Wire SortScreen._after_move + SC3 Pilot tests** — `b928707` (feat)

## Files Created/Modified

- `src/notes_os/screens/task_extract.py` — TaskExtractScreen with A/S/X/Esc/? selection and TaskWriter write on confirm
- `src/notes_os/screens/sort.py` — _after_move filled; _handle_move restructured; _on_tasks_resolved callback added; extract_tasks import
- `src/notes_os/app.py` — SCREENS registry: `"task_extract": TaskExtractScreen`
- `src/notes_os/app.tcss` — TaskExtractScreen modal styles
- `tests/screens/test_task_extract_screen.py` — 3 SC3 Pilot tests

## Architecture: TaskExtractScreen Interaction Flow

```
SortScreen.on_key('x') → _handle_category_key('x')
  → router.handle_category → MOVE result
  → _handle_move(note, result)
    → record_move()
    → _after_move(note)
        if not task_extraction: return False   ← SC1/T-06-08 gate
        tasks = extract_tasks(note.preview)
        if not tasks: return False
        writer = TaskWriter(extracted_tasks_dir)
        modal = TaskExtractScreen(tasks, writer)
        app.call_after_refresh(app.push_screen, modal, _on_tasks_resolved)
        return True                            ← advance deferred
    → extraction_deferred=True → skip _advance()

Next event loop cycle (via InvokeLater on App pump):
  push_screen(TaskExtractScreen) → modal mounts → user sees task list

User presses 'a' (Add all):
  TaskExtractScreen.action_add_all()
    → TaskWriter.write(all_tasks) → YYYY-MM-DD.md written
    → self.dismiss(all_tasks)

Textual dismiss callback:
  SortScreen._on_tasks_resolved(selected)
    → self._advance()          ← sort loop continues
```

## Decisions Made

- **app.call_after_refresh vs self.call_after_refresh**: SortScreen (self) gets a ScreenSuspend message when push_screen fires, which stops its message pump from processing InvokeLater before the callback fires. Scheduling on the App's pump is reliable — the App never gets ScreenSuspend.

- **No Header/Footer in ModalScreen**: Textual Header._on_mount fires an async `set_title` callback that calls `self.query_one(HeaderTitle)`. In modal context, HeaderTitle isn't mounted yet when the async callback fires, causing `NoMatches`. Modals should use `Static` widgets only.

- **Two pause() calls in Pilot tests**: After pressing the routing key, the first `pilot.pause()` allows the InvokeLater (call_after_refresh) to fire and call push_screen. The second `pilot.pause()` allows the modal to mount and become `app.screen`. Single pause was insufficient because the push happens asynchronously.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed Header/Footer from TaskExtractScreen**
- **Found during:** Task 2 (first SC3a Pilot test run)
- **Issue:** `Header._on_mount` fires an async callback that calls `query_one(HeaderTitle)` which raises `NoMatches` when the Header is inside a ModalScreen (HeaderTitle not yet mounted at callback time). Test teardown failed with this error.
- **Fix:** Removed `Header(show_clock=False)` and `Footer()` from `TaskExtractScreen.compose()`. Modal screens use `Static` widgets for header/footer labels instead.
- **Files modified:** `src/notes_os/screens/task_extract.py`
- **Committed in:** `b928707` (Task 2 commit — fix included with wiring commit)

**2. [Rule 1 - Bug] Deferred push_screen to avoid key-event collision**
- **Found during:** Task 2 (SC3a first test run — TaskExtractScreen never appeared / appeared and immediately dismissed)
- **Issue:** When `_after_move` calls `push_screen(TaskExtractScreen)` inline during `on_key('x')`, Textual propagates the still-in-flight 'x' key event to the newly active ModalScreen. TaskExtractScreen's `x` binding triggers `action_skip`, causing immediate dismiss before the user sees the screen.
- **Fix:** Replaced inline `push_screen()` with `app.call_after_refresh(app.push_screen, ...)` to defer the push until after the current key event cycle finishes. Also switched from `self.call_after_refresh` (SortScreen's pump gets ScreenSuspend) to `app.call_after_refresh` (App pump stays active).
- **Files modified:** `src/notes_os/screens/sort.py`
- **Committed in:** `b928707` (Task 2 commit)

**3. [Rule 1 - Bug] Multiple ruff format fixes**
- **Found during:** Tasks 1 and 2 (ruff format --check)
- **Issue:** Minor whitespace/line-length formatting issues in new files
- **Fix:** `ruff format` reformatted `sort.py` and `test_task_extract_screen.py`
- **Files modified:** `src/notes_os/screens/sort.py`, `tests/screens/test_task_extract_screen.py`
- **Committed in:** `6198153`, `b928707`

---

**Total deviations:** 3 auto-fixed (all Rule 1 bugs)
**Impact on plan:** All fixes necessary for correctness and Textual compatibility. No scope creep. The core design (modal screen, A/S/X bindings, gate, callback advance) is fully intact.

## Threat Model Coverage

| Threat | Status |
|--------|--------|
| T-06-08 (extraction running when disabled) | MITIGATED — first line of _after_move returns False when task_extraction=False; SC3b Pilot test asserts no screen + no file |
| T-06-09 (writing outside configured dir) | MITIGATED — TaskWriter writes only under extracted_tasks_dir; SC3a tests point at tmp_path |
| T-06-10 (extraction blocking event loop) | MITIGATED — extract_tasks is pure/fast; push_screen via call_after_refresh is non-blocking; _advance fires via dismiss callback |

## Known Stubs

None — TaskExtractScreen is fully implemented. All three selection modes (add-all, select, skip) work correctly as proven by Pilot tests.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes beyond those in the plan's threat model.

## Self-Check: PASSED

Files verified:
- `src/notes_os/screens/task_extract.py` — exists, imports cleanly, mypy clean
- `src/notes_os/screens/sort.py` — exists, _after_move filled, mypy clean
- `tests/screens/test_task_extract_screen.py` — exists, 3 tests all pass
- `src/notes_os/app.py` — SCREENS["task_extract"] = TaskExtractScreen confirmed
- `src/notes_os/sorter/extractor.py` — UNMODIFIED (git diff --stat shows no change)

Commits verified:
- `6198153` — Task 1 (TaskExtractScreen + CSS)
- `b928707` — Task 2 (SortScreen wire + SC3 Pilot tests)

Coverage: 90.71% total (>80% gate); 318 tests passing

---
*Phase: 06-tui-integration*
*Completed: 2026-06-08*
