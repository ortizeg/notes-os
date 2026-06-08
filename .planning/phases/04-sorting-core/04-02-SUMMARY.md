---
phase: 04-sorting-core
plan: "02"
subsystem: router
tags: [state-machine, pydantic, frozen-models, tdd, para-routing, ui-agnostic]
dependency_graph:
  requires:
    - notes_os.sorter.models.FolderPath
    - notes_os.sorter.models.Note
    - notes_os.sorter.models.ParaStructure
    - notes_os.sorter.notes.NotesRepositoryProtocol
    - notes_os.config.SorterConfig
    - notes_os.config.ArchiveConfig
  provides:
    - notes_os.sorter.router.RouterState
    - notes_os.sorter.router.RouteAction
    - notes_os.sorter.router.RouteResult
    - notes_os.sorter.router.Router
  affects:
    - 04-03-tui
    - 04-04-session
    - 04-05-ui
tech_stack:
  added: []
  patterns:
    - explicit-state-machine-enum
    - frozen-pydantic-v2
    - stateless-transition-functions
    - injectable-clock-callable
    - TYPE_CHECKING-deferred-imports-with-runtime-exception-for-pydantic
key_files:
  created:
    - src/notes_os/sorter/router.py
    - tests/sorter/test_router_unit.py
  modified:
    - pyproject.toml
decisions:
  - "Router is stateless between calls — all context passed explicitly as RouteResult + Note arguments; no shared mutable state (UI-agnostic, ROUT deterministic test floor)"
  - "FolderPath imported at runtime (not in TYPE_CHECKING) with noqa: TC001 — Pydantic V2 model validation requires the type at class definition time"
  - "year_provider: Callable[[], int] | None injected with default lambda: datetime.datetime.now().year — tests use fixed lambda: 2031 for determinism (ROUT-02)"
  - "General-first folder ordering via _sort_general_first() helper — stable, O(n), no alphabet sort side effects (ROUT-05)"
  - "Sub-subfolders encoded as 'root/folder' key in ParaStructure.subfolders dict — 3-level hierarchy without extending the frozen model (M1 PARA depth)"
  - "A/R with no sub-folders auto-move to root path (e.g. ('Areas',)) — skip AWAIT_FOLDER when folder list is empty (ROUT-05)"
  - "notes_os.sorter.router added to mypy override disallow_any_explicit=false — RouteResult BaseModel inherits explicit Any from Pydantic internals"
  - "per-file-ignore N802/RUF001/RUF002/RUF003 in tests — uppercase test names intentional (test_P_upper_, test_X_upper_) and U+203A separator assertions intentional"
metrics:
  duration: "394 seconds"
  completed: "2026-06-07"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 1
---

# Phase 4 Plan 02: PARA Router State Machine Summary

**One-liner:** UI-agnostic PARA routing state machine with `RouterState` enum, frozen `RouteResult` Pydantic model, archive auto-year via injected `year_provider`, [B] back-out, General-first subfolder ordering, and `ensure_folder`-before-`move_note` write protocol — 99% line coverage.

## What Was Built

### router.py — State Machine

**`RouterState`** (enum.Enum — 5 states, per PRD §5.5):
- `SHOW_NOTE` — note displayed; user input pending
- `AWAIT_CATEGORY` — waiting for P/A/R/X/S/? keystroke
- `AWAIT_FOLDER` — root selected; picking folder by 1-based number
- `AWAIT_SUBFOLDER` — folder with sub-subfolders selected; picking sub by number
- `CONFIRM_MOVE` — reserved for M2 confirmation; currently moves are immediate

**`RouteAction`** (enum.Enum):
- `MOVE` — note should be moved to `RouteResult.folder_path`
- `SKIP` — leave note in inbox, advance to next
- `NONE` — navigation-only, no write

**`RouteResult`** (frozen Pydantic V2 BaseModel — `ConfigDict(frozen=True)`):

| Field | Type | Purpose |
|-------|------|---------|
| `state` | `RouterState` | Next machine state |
| `action` | `RouteAction \| None` | Write action to perform |
| `folder_path` | `FolderPath \| None` | Resolved destination path (populated on MOVE) |
| `display_path` | `str \| None` | Human-readable path with " › " separator (ROUT-08) |
| `options` | `tuple[str, ...]` | Folder/subfolder names for next selection UI |
| `selected_root` | `str \| None` | PARA root chosen at AWAIT_CATEGORY; carried forward |
| `selected_folder` | `str \| None` | Folder chosen at AWAIT_FOLDER; carried forward |
| `help_requested` | `bool` | True when '?' pressed; state unchanged |

**`Router`** class — stateless between calls:

```python
Router(
    repo: NotesRepositoryProtocol,
    config: SorterConfig,
    year_provider: Callable[[], int] | None = None,  # default: datetime.now().year
)
```

**Transition entrypoints:**

| Method | State | Input | Key behaviors |
|--------|-------|-------|---------------|
| `handle_category(key, note)` | AWAIT_CATEGORY | str keystroke | P/A/R→AWAIT_FOLDER or MOVE (if no subs), X→archive MOVE, S→SKIP, ?→help, other→no-op |
| `handle_folder(index, prev, note)` | AWAIT_FOLDER | 1-based int | sub-subfolders→AWAIT_SUBFOLDER, no-children→MOVE, invalid index→no-op |
| `handle_subfolder(index, prev, note)` | AWAIT_SUBFOLDER | 1-based int | MOVE to (root, folder, sub), invalid→no-op |
| `handle_back(current_state, prev)` | any | — | AWAIT_SUBFOLDER→AWAIT_FOLDER, AWAIT_FOLDER→AWAIT_CATEGORY |

**Write protocol (T-04-04 mitigation):**
Every MOVE action calls `repo.ensure_folder(path)` then `repo.move_note(note_id, path)` in that order. `BackingUpNotesRepository` fires a backup before each call in production, but the router sees only the protocol.

**Archive auto-year (ROUT-02):**
- Key: `x` / `X` at AWAIT_CATEGORY
- Resolves path: `(cfg.archive.base_folder, str(year_provider()))`
- Default year_provider: `lambda: datetime.datetime.now().year`
- Tests inject `lambda: 2031` for determinism
- Display: `"Archive › 2031"` (U+203A separator)

**General-first ordering:**
`_sort_general_first(names)` — stable sort placing "General" first, leaving all other names in their original relative order (ROUT-05).

**Sub-subfolder detection:**
The router checks `structure.subfolders.get("root/folder", ())` to find 3-level children. If the key exists and is non-empty, transitions to AWAIT_SUBFOLDER with General-first options. Otherwise moves immediately.

### pyproject.toml Changes

1. Added `"notes_os.sorter.router"` to `[[tool.mypy.overrides]]` module list:
   ```toml
   module = ["notes_os.sorter.models", "notes_os.backup_models", "notes_os.config", "notes_os.sorter.router"]
   disallow_any_explicit = false
   ```

2. Added per-file-ignores for test file and router source:
   ```toml
   "tests/**/*.py" = ["S101", "S105", "S106", "N802", "RUF001", "RUF002", "RUF003"]
   "src/notes_os/sorter/router.py" = ["RUF001", "RUF002"]
   ```

### tests/sorter/test_router_unit.py

49 tests across 8 test classes:

| Class | Tests | Requirements |
|-------|-------|-------------|
| `TestRouterStateEnum` | 2 | State enum completeness |
| `TestRouteActionEnum` | 1 | Action enum completeness |
| `TestRouteResultModel` | 2 | Frozen model construction + immutability |
| `TestAwaitCategoryTransition` | 18 | ROUT-01/07: P/A/R/X/S/?/invalid, case-insensitive |
| `TestArchiveAutoYear` | 8 | ROUT-02/08: X→archive, ensure_folder ordering, year injection |
| `TestAwaitFolderTransition` | 8 | ROUT-03/04/05/06/07: folder selection, [B] back, invalid index |
| `TestGeneralFirstOrdering` | 2 | ROUT-05: General first in options |
| `TestAwaitSubfolderTransition` | 8 | ROUT-05/06/07/08: subfolder selection, [B] back, 3-level path |

## Router API for 04-05 Controller

The TUI controller (04-05) wires the router as follows:

```python
from notes_os.sorter.router import Router, RouterState, RouteAction, RouteResult

router = Router(repo=repo, config=cfg)  # year_provider defaults to current year

# Category keystroke:
result = router.handle_category(key, note)
if result.action == RouteAction.MOVE:
    # note already moved; advance to next note
elif result.action == RouteAction.SKIP:
    # advance to next note
elif result.state == RouterState.AWAIT_FOLDER:
    # show result.options numbered list; wait for numeric input

# Folder selection:
result = router.handle_folder(numeric_choice, prev_result, note)

# Subfolder selection:
result = router.handle_subfolder(numeric_choice, prev_result, note)

# Back:
result = router.handle_back(current_state, prev_result)
```

`result.display_path` carries the human-readable path (e.g. `"Projects › Web"`) for the TUI to display after a MOVE.

## Verification Results

| Check | Result |
|-------|--------|
| `pytest tests/sorter/test_router_unit.py -q -m 'not integration'` | 49 passed |
| `--cov=notes_os.sorter.router --cov-fail-under=95` | 99% coverage (104 stmts, 1 miss) |
| `pytest -q -m 'not integration'` (full suite) | 178 passed |
| `ruff check src/notes_os/sorter/router.py tests/sorter/test_router_unit.py` | Clean |
| `ruff format` | Clean |
| `mypy src/` | Success: 13 source files, zero errors |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Test Accuracy] Revised A/R category test expectations to match correct behavior**
- **Found during:** Task 1 GREEN phase
- **Issue:** Initial tests asserted `AWAIT_FOLDER` for Areas/Resources even when they had no sub-folders. The router correctly auto-moves to the root when there are no folders (ROUT-05 "folders WITHOUT [subfolders] move immediately"). The test fixture had Areas/Resources with empty sub-folder lists.
- **Fix:** Updated tests to assert `SHOW_NOTE + MOVE` when root has no sub-folders; added separate tests with sub-folder fixtures to assert `AWAIT_FOLDER` path.
- **Files modified:** `tests/sorter/test_router_unit.py`

**2. [Rule 1 - Bug] Pydantic V2 requires FolderPath at runtime for model field validation**
- **Found during:** Task 1 GREEN phase — `PydanticUserError: RouteResult is not fully defined; you should define FolderPath`
- **Issue:** Moving `FolderPath` into `TYPE_CHECKING` per ruff TC001 broke Pydantic's runtime model construction. With `from __future__ import annotations`, annotations are stored as strings and Pydantic V2 resolves them at class definition time; if `FolderPath` is absent from the runtime namespace at that point, model construction fails.
- **Fix:** Kept `FolderPath` as a runtime import with `# noqa: TC001` explaining why.
- **Files modified:** `src/notes_os/sorter/router.py`

**3. [Rule 2 - Correctness] Added per-file-ignore for N802/RUF001/RUF002/RUF003**
- **Found during:** Task 3 ruff check
- **Issue:** Ruff N802 flagged test method names like `test_P_upper_moves_to_await_folder_projects` (uppercase letter in name). Ruff RUF001/002/003 flagged the intentional U+203A `›` separator in test assertions per ROUT-08.
- **Fix:** Added `"N802", "RUF001", "RUF002", "RUF003"` to `tests/**/*.py` per-file-ignore in pyproject.toml. Added `"RUF001", "RUF002"` to router source ignore. The uppercase names and `›` character are intentional.
- **Files modified:** `pyproject.toml`

## Known Stubs

None — router is fully wired. `ensure_folder` and `move_note` are called through the injected `NotesRepositoryProtocol`; in production the `BackingUpNotesRepository` decorator supplies backup behavior.

## Threat Surface Scan

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-04-03: invalid/out-of-range input | Router treats unrecognised keys and out-of-range indices as no-ops; state unchanged; no writes issued | Implemented |
| T-04-04: writing to unintended folder | FolderPath resolved only from ParaStructure + configured archive.base_folder; ensure_folder precedes move_note | Implemented |
| T-04-SC: pip installs | No new packages (stdlib datetime/enum; pydantic already declared) | N/A |

## Commits

- `50dadb8` — `test(04-02): add failing tests for PARA router state machine (RED)`
- `6c7b4c7` — `feat(04-02): PARA router state machine — RouterState, RouteResult, all transitions (GREEN)`

## Self-Check: PASSED
