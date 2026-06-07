---
phase: 04-sorting-core
plan: "03"
subsystem: ui
tags: [rich, readchar, protocol, injectable-io, terminal-ui, tui]
dependency_graph:
  requires:
    - notes_os.sorter.models.Note
    - rich.console.Console
    - rich.markdown.Markdown
    - rich.panel.Panel
    - readchar.readkey
  provides:
    - notes_os.sorter.ui.SortUIProtocol
    - notes_os.sorter.ui.RichSortUI
  affects:
    - 04-04-session
    - 04-05-controller
tech_stack:
  added: []
  patterns:
    - injectable-io-for-testability
    - protocol-interface-for-fake-injection
    - duck-typed-forward-compat-seam
key_files:
  created:
    - src/notes_os/sorter/ui.py
    - tests/sorter/test_ui_unit.py
  modified:
    - pyproject.toml
key_decisions:
  - "Console, key_reader, and line_reader are constructor-injected on RichSortUI so tests never block on real terminal I/O"
  - "SortUIProtocol uses Any for note/summary params — forward-compat duck-typing; notes_os.sorter.ui added to mypy disallow_any_explicit=false override"
  - "show_summary accepts Any and attempts duck-typed attribute access (.moved/.skipped/.total) before falling back to str() — forward-compat seam for 04-04 SessionSummary"
  - "prompt_choice defensively returns None for non-numeric, out-of-range, and back input — T-04-05 mitigation at the UI boundary"
  - "render_note does NOT re-strip or re-truncate note.preview; bridge already delivers HTML-stripped + truncated plain text"
patterns-established:
  - "Injectable-IO Pattern: all I/O dependencies (Console, key_reader, line_reader) are constructor-injected with sane defaults; tests substitute fakes without monkey-patching"
  - "Protocol-Seam Pattern: SortUIProtocol is @runtime_checkable so controllers import only the protocol; FakeUI can be injected in integration tests (04-05)"
  - "Duck-typed Forward-Compat Seam: show_summary(summary: Any) uses hasattr-style try/except to render known attributes, avoids coupling UI to 04-04 SessionSummary at definition time"
requirements-completed: [UI-01, UI-02, UI-03, UI-04]
duration: "218 seconds (approx 3 min)"
completed: "2026-06-07"
---

# Phase 4 Plan 03: Rich/readchar Terminal UI Summary

**One-liner:** Injectable Rich/readchar terminal UI with `SortUIProtocol` (6 methods), `RichSortUI` rendering note title+Markdown preview, single-key category capture, numbered-list choice reader, inline `?` PARA help overlay, inbox count display — 100% unit coverage via fake I/O seams; 40 tests, 218 passed overall.

## Performance

- **Duration:** approx 3 min (218 seconds)
- **Started:** 2026-06-07T22:11:06Z
- **Completed:** 2026-06-07T22:14:44Z
- **Tasks:** 2
- **Files modified:** 3 (2 created + 1 modified)

## Accomplishments

- `SortUIProtocol` — `@runtime_checkable` Protocol with 6 methods enabling FakeUI injection in 04-05 controller tests
- `RichSortUI` — full implementation with injectable `Console`, `key_reader`, `line_reader`; zero `print()`, all output via Rich
- 40 unit tests passing; no test blocks on real terminal; `ui.py` at 100% coverage; overall suite 99.65%

## SortUIProtocol Method Signatures

```python
class SortUIProtocol(Protocol):
    def show_inbox_count(self, count: int) -> None: ...
    def render_note(self, note: Any) -> None: ...          # duck-typed; expects .title + .preview
    def prompt_category(self) -> str: ...                  # returns one lower-cased char
    def prompt_choice(self, options: Sequence[str]) -> int | None: ...  # 1-based idx or None
    def show_help(self) -> None: ...
    def show_summary(self, summary: Any) -> None: ...      # 04-04 seam; accepts SessionSummary
```

### show_summary contract for 04-04

`show_summary(summary: Any) -> None` renders `summary` by:
1. Attempting attribute access: `summary.moved`, `summary.skipped`, `summary.total` — renders a "Moved: N Skipped: N Total: N" summary line
2. Falls back to `str(summary)` if those attributes are absent (AttributeError caught)

Plan 04-04 should define `SessionSummary` with `.moved: int`, `.skipped: int`, `.total: int` attributes; `RichSortUI.show_summary` will render it correctly without any changes to ui.py.

## Task Commits

1. **Task 1: SortUIProtocol + RichSortUI render_note + show_inbox_count** - `95638ae` (feat)
2. **Task 2: prompt_category + prompt_choice + show_help + mypy override** - `dfd1939` (feat)

## Files Created/Modified

- `src/notes_os/sorter/ui.py` — SortUIProtocol + RichSortUI (6 methods; 78 statements; injectable I/O)
- `tests/sorter/test_ui_unit.py` — 40 unit tests across 9 test classes; fake Console + scripted readers
- `pyproject.toml` — Added `notes_os.sorter.ui` to `[[tool.mypy.overrides]]` disallow_any_explicit=false

## Decisions Made

- **Injectable I/O:** Console, key_reader, and line_reader are constructor-injected with sane defaults. This avoids monkey-patching and makes every method testable without a real terminal.
- **mypy override:** `notes_os.sorter.ui` added to `disallow_any_explicit=false` override — `Any` is intentional for duck-typed `note` and `summary` params in Protocol methods. No Pydantic BaseModel defined in this module.
- **show_summary forward-compat seam:** Uses try/except AttributeError to render `SessionSummary` attributes, falls back to `str()`. 04-04 defines `SessionSummary`; ui.py requires no changes.
- **prompt_choice returns None on back/invalid:** Consistent with T-04-05 threat mitigation — the UI boundary always normalizes before handing off to the controller/router.
- **readchar deferred import:** `readchar` is imported inside the `else` branch of `__init__` so the module can be imported in test environments where the default reader is overridden without any readchar side effects.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ruff TC003 / RUF100 / F401 flags caught at Task 2 verify**
- **Found during:** Task 2 ruff check
- **Issue:** `Callable` and `Sequence` from `collections.abc` triggered TC003 (move to TYPE_CHECKING); one `noqa: SIM210` was unused (guard pattern removed); `pytest` imported but unused in test file.
- **Fix:** Moved `Callable`/`Sequence` into `TYPE_CHECKING` block; removed spurious noqa comments; removed unused `pytest` import.
- **Files modified:** `src/notes_os/sorter/ui.py`, `tests/sorter/test_ui_unit.py`
- **Verification:** `ruff check` clean on both files.
- **Committed in:** `dfd1939` (Task 2 commit)

**2. [Rule 2 - Missing Critical] mypy override for notes_os.sorter.ui**
- **Found during:** Task 2 mypy check
- **Issue:** `Any` in Protocol method parameters triggered `explicit-any` under strict mypy. Plan said override "likely NOT needed" but did note it if the module uses Pydantic or Any. The duck-typed `note`/`summary` params require `Any` for forward-compat.
- **Fix:** Added `notes_os.sorter.ui` to `[[tool.mypy.overrides]]` in pyproject.toml alongside existing model overrides.
- **Files modified:** `pyproject.toml`
- **Verification:** `mypy src/` — 14 source files, zero errors.
- **Committed in:** `dfd1939` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 lint fix, 1 Rule 2 missing override)
**Impact on plan:** Both fixes necessary for lint/typecheck compliance. No scope creep.

## Threat Model Coverage

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-04-05: malformed keystroke/line input | `prompt_choice` defensively returns `None` for non-numeric, out-of-range, and back input; `prompt_category` always returns lower-cased single char | Implemented |
| T-04-06: note preview information disclosure | Preview rendered to user's own local terminal only; no logging of preview content | Accepted |
| T-04-SC: pip installs | No new packages; `rich` and `readchar` already declared in pyproject.toml | N/A |

## Known Stubs

None — all 6 `SortUIProtocol` methods are fully implemented in `RichSortUI`. `show_summary` is a forward-compat seam but its duck-typed implementation is complete and tested.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The only new trust boundary is keyboard → UI (documented in the plan's threat model); mitigated by `prompt_choice` defensive parsing.

## Verification Results

| Check | Result |
|-------|--------|
| `pytest tests/sorter/test_ui_unit.py -q -m 'not integration'` | 40 passed |
| `pytest -q -m 'not integration' --cov=notes_os --cov-fail-under=80` | 218 passed, 99.65% coverage |
| `ruff check src/notes_os/sorter/ui.py tests/sorter/test_ui_unit.py` | Clean |
| `ruff format` | Clean (unchanged) |
| `mypy src/` | Success: 14 source files, zero errors |
| `SortUIProtocol isinstance check` | Pass (runtime_checkable) |
| `render_note does not re-truncate preview` | Asserted in test_does_not_re_truncate_preview |

## Next Phase Readiness

- `SortUIProtocol` is the injection interface for 04-05 controller; use `FakeUI` implementing the 6-method protocol
- `show_summary(summary)` seam ready for 04-04 `SessionSummary` — define `.moved: int`, `.skipped: int`, `.total: int` on the dataclass/model
- `RichSortUI` is ready for wiring in 04-05 controller; constructor: `RichSortUI(console=Console(), key_reader=readchar.readkey, line_reader=lambda: input(""))`

---
*Phase: 04-sorting-core*
*Completed: 2026-06-07*

## Self-Check: PASSED

Files exist:
- `/Users/ortizeg/1Projects/notes/src/notes_os/sorter/ui.py` — FOUND
- `/Users/ortizeg/1Projects/notes/tests/sorter/test_ui_unit.py` — FOUND
- `/Users/ortizeg/1Projects/notes/.planning/phases/04-sorting-core/04-03-SUMMARY.md` — FOUND

Commits exist:
- `95638ae` — FOUND
- `dfd1939` — FOUND

pyproject.toml contains `notes_os.sorter.ui` in mypy override — verified
