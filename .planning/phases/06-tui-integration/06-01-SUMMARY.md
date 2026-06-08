---
phase: 06-tui-integration
plan: 01
subsystem: ui
tags: [textual, pytest-asyncio, tui, di-seam, homescreen, pilot-tests]

# Dependency graph
requires:
  - phase: 05-task-extraction
    provides: SortController DI pattern (build_default_controller), BackupManager, BackingUpNotesRepository, MockNotesRepository
  - phase: 03-backup
    provides: BackupManager.list() newest-first, BackupConfig, Backup model with timestamp
  - phase: 02-bridge
    provides: NotesRepositoryProtocol, AppleScriptNotesRepository, BridgeConfig
provides:
  - "NotesOSApp(App[None]) with DI seam: config/repo/backup_manager injectable"
  - "HomeScreen: ASCII splash + keyboard OptionList menu + live status panel"
  - "app.tcss: Textual CSS for home layout (splash, menu, status)"
  - "screens/ package: __init__.py + home.py"
  - "pytest-asyncio async harness: asyncio_mode=auto in pixi+pyproject+CI"
  - "tests/conftest.py: tui_config + tui_repo fixtures for all TUI tests"
  - "SC1 Pilot tests: 4 tests proving live inbox count / backup / honest backend"
affects:
  - "06-02 (SortScreen: push_screen('sort') seam in HomeScreen.action_sort)"
  - "06-03 (HelpOverlay: action_help() dispatches to screen)"
  - "06-04 (ConfirmQuit: action_noop on HomeScreen Esc, global Q binding)"

# Tech tracking
tech-stack:
  added:
    - "pytest-asyncio (pixi.toml, pyproject asyncio_mode=auto, CI pip line)"
    - "textual 8.2.7 (already installed; now actually used)"
  patterns:
    - "DI seam: NotesOSApp(config=None, repo=None, backup_manager=None) — production built via deferred local imports"
    - "Deferred imports: AppleScriptNotesRepository, BackingUpNotesRepository, BackupManager, load_config imported inside __init__ only when repo/backup_manager is None"
    - "self.app_config (NOT self.config — avoids Textual App.config collision)"
    - "Screen queries in Pilot tests: app.screen.query_one('#id', WidgetType)"
    - "SCREENS registry class attribute; BINDINGS with ClassVar annotation"

key-files:
  created:
    - "src/notes_os/app.py — NotesOSApp(App[None]) with DI seam, main() launcher"
    - "src/notes_os/app.tcss — Textual CSS (splash, menu, status)"
    - "src/notes_os/screens/__init__.py — screens package"
    - "src/notes_os/screens/home.py — HomeScreen: splash, OptionList menu, status panel"
    - "tests/conftest.py — tui_config + tui_repo fixtures"
    - "tests/screens/__init__.py — screens test package"
    - "tests/screens/test_async_harness.py — async smoke test"
    - "tests/screens/test_home_screen.py — SC1 Pilot tests (4 tests)"
  modified:
    - "pyproject.toml — asyncio_mode = 'auto'"
    - "pixi.toml — pytest-asyncio = '*'"
    - ".github/workflows/test.yml — CI pip install includes pytest-asyncio"
    - "tests/test_app.py — updated for real Textual App (monkeypatched run)"

key-decisions:
  - "self.app_config stores SorterConfig to avoid collision with Textual's App.config attribute"
  - "Deferred local imports (lazy AppleScript) mirrors build_default_controller() pattern from sorter/controller.py"
  - "SCREENS and BINDINGS annotated ClassVar to satisfy ruff RUF012"
  - "Query widgets from app.screen.query_one() not app.query_one() — HomeScreen lives on top of default base screen in stack"
  - "Quit menu action uses self.app.exit() (synchronous) instead of async action_quit()"
  - "Backend label is exactly 'sort-only (M1)' — T-06-02 mitigation; no fabricated LLM"
  - "pixi.lock legitimately updated to reflect new pytest-asyncio dep (not discarded)"

patterns-established:
  - "TUI-05 nav convention: global Q/? on NotesOSApp; per-screen ↑↓/Enter/Esc on screen class"
  - "Pilot test pattern: async with app.run_test() as pilot: await pilot.pause(); query from app.screen"
  - "Status panel: on_mount reads live data from self.app.repo and self.app.backup_manager"

requirements-completed: [TUI-01, TUI-02, TUI-05]

# Metrics
duration: 10min
completed: 2026-06-08
---

# Phase 06 Plan 01: NotesOS App Shell + HomeScreen + Async Test Harness Summary

**Textual NotesOSApp(App) with injectable repo/config/backup_manager DI seam, HomeScreen showing live inbox count + honest sort-only (M1) backend + real last-backup timestamp, and pytest-asyncio Pilot harness proven by SC1 tests**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-08T03:22:02Z
- **Completed:** 2026-06-08T03:32:00Z
- **Tasks:** 3 (all complete)
- **Files created/modified:** 11

## Accomplishments

- `NotesOSApp(App[None])` with full DI seam: production `BackingUpNotesRepository` built via deferred imports when `repo=None`; injected repo used as-is in tests; no AppleScript at `import notes_os.app` time
- `HomeScreen` delivers TUI-01/TUI-02/TUI-05: ASCII splash + version + keyboard OptionList menu (Sort Inbox/Quit) + status panel with live inbox count, real last-backup timestamp (or "never"), and honest `sort-only (M1)` backend label
- `pytest-asyncio` wired in all three required places (pixi.toml, pyproject `asyncio_mode=auto`, CI pip line); async smoke test + 4 SC1 Pilot tests all green
- 310 tests pass, 93.66% overall coverage (80% gate satisfied)

## Task Commits

Each task was committed atomically:

1. **Task 1: pytest-asyncio + async harness smoke test** - `66ceea2` (chore)
2. **Task 2: NotesOSApp(App) DI seam + HomeScreen + main() TUI launch** - `5595282` (feat)
3. **Task 3: HomeScreen SC1 Pilot tests** - `75dd4e8` (test)

## Files Created/Modified

- `src/notes_os/app.py` — NotesOSApp(App[None]) with DI seam; SCREENS/BINDINGS; deferred imports; main() launches TUI
- `src/notes_os/app.tcss` — Minimal Textual CSS for splash/menu/status layout
- `src/notes_os/screens/__init__.py` — Screens package marker
- `src/notes_os/screens/home.py` — HomeScreen: compose() + on_mount() live status + OptionList menu + action_sort seam + action_help notify
- `tests/conftest.py` — tui_config (tmp_path SorterConfig) + tui_repo (MockNotesRepository × 2 notes)
- `tests/screens/__init__.py` — Test package marker
- `tests/screens/test_async_harness.py` — Minimal async smoke test proving run_test() harness
- `tests/screens/test_home_screen.py` — 4 SC1 Pilot tests (inbox count, backend label, last-backup never/timestamp, version, menu items)
- `tests/test_app.py` — Updated: DI-seam test + async Pilot HomeScreen assertion + monkeypatched main() tests
- `pyproject.toml` — asyncio_mode = "auto"
- `pixi.toml` — pytest-asyncio = "*"
- `.github/workflows/test.yml` — pip install includes pytest-asyncio

## Decisions Made

- **`self.app_config` naming**: Stores `SorterConfig` as `app_config` (not `config`) to avoid shadowing Textual's `App.config` attribute — critical for Textual to function correctly
- **Deferred imports pattern**: `AppleScriptNotesRepository`, `BackingUpNotesRepository`, `BackupManager`, `load_config` are all imported inside `__init__` only when the corresponding parameter is `None` — mirrors `build_default_controller()` style exactly so `import notes_os.app` never triggers AppleScript
- **`app.screen.query_one()` in Pilot tests**: Textual pushes HomeScreen on top of a base default screen; widget queries must target `app.screen` (the active HomeScreen), not `app` (which walks from the base Screen)
- **`self.app.exit()` for Quit**: `App.action_quit()` is an async coroutine; using synchronous `self.app.exit()` avoids the mypy `unused-coroutine` error in the message handler
- **`pixi.lock` kept**: pixi.lock legitimately changed to reflect new pytest-asyncio dependency; retained (not discarded) per plan note about real dep additions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created `screens/home.py` and `tests/conftest.py` during Task 2**
- **Found during:** Task 2 (NotesOSApp shell)
- **Issue:** `app.py` imports `HomeScreen` from `screens.home` which didn't exist yet; mypy/ruff couldn't validate; Task 2's `tests/test_app.py` needed `tui_config`/`tui_repo` fixtures from `tests/conftest.py` which was Task 3's deliverable
- **Fix:** Created `src/notes_os/screens/home.py` (full implementation) and `tests/conftest.py` (fixtures) during Task 2 to unblock Task 2 verification. Task 3's scope narrowed to adding `tests/screens/test_home_screen.py` only.
- **Files modified:** `src/notes_os/screens/home.py`, `tests/conftest.py`
- **Committed in:** `5595282` (Task 2 commit)

**2. [Rule 1 - Bug] Fixed 4 ruff lint issues in new files**
- **Found during:** Tasks 2 and 3 (ruff format/check passes)
- **Issues:** `RUF012` (SCREENS/BINDINGS need `ClassVar`); `TC002` (pytest moved to TYPE_CHECKING in test_app.py); `TC003` (Path moved to TYPE_CHECKING in conftest.py); `TC001/TC002/TC005` (various imports in home.py)
- **Fix:** Added `ClassVar[dict[str, type]]` and `ClassVar[list[BindingType]]` annotations; moved stdlib/third-party type-only imports to `TYPE_CHECKING` blocks
- **Files modified:** `src/notes_os/app.py`, `src/notes_os/screens/home.py`, `tests/test_app.py`, `tests/conftest.py`
- **Committed in:** `5595282` (part of Task 2 commit)

**3. [Rule 1 - Bug] Fixed async action_quit in HomeScreen menu handler**
- **Found during:** Task 2 (mypy strict check)
- **Issue:** `self.app.action_quit()` is a coroutine; calling without `await` in a sync handler caused `unused-coroutine` mypy error
- **Fix:** Changed to `self.app.exit()` (synchronous) which achieves the same result
- **Files modified:** `src/notes_os/screens/home.py`
- **Committed in:** `5595282` (part of Task 2 commit)

**4. [Rule 1 - Bug] Fixed Pilot test widget query scope**
- **Found during:** Task 3 (test_home_screen.py — first run all 4 failed with NoMatches)
- **Issue:** `app.query_one("#status-inbox")` searched from the base default screen (not HomeScreen); HomeScreen widgets live on `app.screen` (the active top-of-stack screen)
- **Fix:** Changed all queries to `app.screen.query_one(...)` throughout test_home_screen.py
- **Files modified:** `tests/screens/test_home_screen.py`
- **Committed in:** `75dd4e8` (Task 3 commit)

---

**Total deviations:** 4 auto-fixed (2 Rule 1 bugs, 1 Rule 1 lint, 1 Rule 3 blocking)
**Impact on plan:** All fixes necessary for correctness; no scope creep. Task 3 narrowed to test file only since home.py+conftest.py were created during Task 2.

## Issues Encountered

- Textual's `App.run_test()` with a custom `on_mount` that uses `push_screen(SCREENS_registry_key)` results in a two-level screen stack (`[Screen, HomeScreen]`). Pilot tests must target `app.screen` (the active top screen) for widget queries — this pattern must be followed in all future screen tests (06-02/03/04).

## DI Seam Documentation (for 06-02/03/04)

```python
class NotesOSApp(App[None]):
    # Constructor signature (DI seam):
    def __init__(
        self,
        config: SorterConfig | None = None,
        repo: NotesRepositoryProtocol | None = None,
        backup_manager: BackupManager | None = None,
    ) -> None: ...

    # Public attributes set in __init__:
    self.app_config: SorterConfig       # NOT self.config (Textual collision)
    self.repo: NotesRepositoryProtocol  # production or injected mock
    self.backup_manager: BackupManager  # production or injected

    # Screen registry and nav bindings:
    SCREENS = {"home": HomeScreen}      # add "sort": SortScreen in 06-02
    BINDINGS = [Binding("q", "quit"), Binding("question_mark", "help")]

    # Screens access app deps via:
    #   self.app.repo
    #   self.app.backup_manager
    #   self.app.app_config
    #   self.app.push_screen("sort")   # 06-02 wires this in action_sort
```

Nav convention (TUI-05):
- Global (on NotesOSApp): `Q` quit, `?` help
- Per-screen: `↑`/`↓` move selection, `Enter` select/confirm, `Esc`/`B` back one level
- HomeScreen: `Esc` → action_noop (no-op; root screen)
- SortScreen (06-02): `Esc` → pop_screen() back to HomeScreen

## Known Stubs

- `HomeScreen.action_sort()`: logs "SortScreen wired in Phase 06-02" — placeholder; 06-02 replaces with `self.app.push_screen("sort")`

## Threat Flags

None — all threat model items (T-06-01, T-06-02, T-06-03, T-06-SC) are mitigated as planned.

## Self-Check: PASSED

## Next Phase Readiness

- **06-02 (SortScreen)**: DI seam complete; `app.repo` / `app.app_config` accessible on any screen; `action_sort` seam in HomeScreen ready; add `SCREENS["sort"] = SortScreen` to NotesOSApp and implement SortScreen
- **06-03 (HelpOverlay)**: `action_help()` on NotesOSApp dispatches to active screen's `action_help`; HomeScreen's `action_help` shows notify overlay — pattern established for per-screen help
- **06-04 (ConfirmQuit)**: Global `Q` binding in place; `Esc` on HomeScreen is no-op (action_noop); replace with confirm dialog here

---
*Phase: 06-tui-integration*
*Completed: 2026-06-08*
