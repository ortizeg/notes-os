---
phase: 05-task-extraction
plan: 02
subsystem: extraction-ui-controller
tags: [taskwriter, markdown, ui, controller, di, sc1, pydantic, tdd]

# Dependency graph
requires:
  - phase: 05-task-extraction
    plan: 01
    provides: "extract_tasks(text: str) -> list[ExtractedTask], ExtractedTask.text (LOCKED contract)"
  - phase: 04-sorting-core
    provides: "SortController, SortUIProtocol, FeaturesConfig, SortSession"
provides:
  - "TaskWriter.write(tasks) appending '- [ ] {task.text}' lines to {dir}/YYYY-MM-DD.md"
  - "FeaturesConfig.extracted_tasks_dir: Path defaulting to ~/.notes-os/extracted-tasks"
  - "SortUIProtocol.prompt_task_selection + RichSortUI implementation (A/S/X)"
  - "SortController DI-injected extractor + writer; _maybe_extract_tasks gated on task_extraction"
  - "SC1 proof: task_extraction=False (default) -> ZERO extractor/UI/writer calls; loop byte-identical to Phase 4"
affects:
  - 05-03 (if any future phase builds on extraction)
  - production build_default_controller (now wires real extract_tasks + TaskWriter)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SC1 short-circuit: not config.features.task_extraction -> immediate return as first line"
    - "Injectable clock (Callable[[], date]) on TaskWriter for deterministic test output"
    - "TYPE_CHECKING imports for Callable/Sequence/Path in extractor.py and ui.py (TC003 compliance)"
    - "SpyUI + SpyExtractor + SpyWriter spy pattern for call-count assertions in controller tests"
    - "Append-mode file write (open 'a', utf-8) for YYYY-MM-DD.md daily task accumulation"

key-files:
  created:
    - tests/sorter/test_task_writer.py
    - tests/sorter/test_extraction_ui.py
    - tests/sorter/test_controller_extraction.py
  modified:
    - src/notes_os/config.py
    - src/notes_os/sorter/extractor.py
    - src/notes_os/sorter/ui.py
    - src/notes_os/sorter/controller.py

key-decisions:
  - "TaskWriter is a plain class (not Pydantic) — no new mypy override entry needed"
  - "Path/Callable/Sequence moved to TYPE_CHECKING blocks (TC003) — runtime duck typing is sufficient"
  - "note.preview used as extraction input (not body) — already HTML-stripped by bridge, no private import"
  - "build_default_controller unconditionally constructs TaskWriter — SC1 gate is inside _maybe_extract_tasks, not in factory"
  - "SpyWriter.write uses Sequence[ExtractedTask] parameter to match TaskWriter.write protocol"

requirements-completed: [TASK-02, TASK-03, TASK-04]

# Metrics
duration: 7m
completed: 2026-06-07
---

# Phase 5 Plan 02: TaskWriter + Extraction UI + Controller Integration Summary

**TaskWriter appending `- [ ] {task}` Markdown checkboxes to a daily YYYY-MM-DD.md; `prompt_task_selection` (A/S/X) on `SortUIProtocol`; SC1-gated DI extraction in `SortController`.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-07T22:52:01Z
- **Completed:** 2026-06-07T22:59:23Z
- **Tasks:** 3 (each with TDD-style verify-then-commit cycle)
- **Files modified:** 7

## Accomplishments

### Task 1: TaskWriter + `extracted_tasks_dir` config field (commit `2d6a41c`)
- Added `extracted_tasks_dir: Path` to `FeaturesConfig` with default `~/.notes-os/extracted-tasks`
- Implemented `TaskWriter` plain class in `extractor.py`: injectable `clock` (default `date.today`), `write(tasks)` appends `- [ ] {text}\n` per task in append mode, `write([])` is a no-op returning `None`, `mkdir(parents=True, exist_ok=True)` on first write
- `Callable`, `Sequence`, and `Path` moved to `TYPE_CHECKING` block (TC003 compliance); `date` stays as runtime import for `date.today` default
- 9 unit tests under `tmp_path` with fixed clock covering: creates file, correct checkbox format, append-not-truncate, empty no-op, returns Path, creates parent dirs, ISO date filename, default clock, single-task

### Task 2: `prompt_task_selection` on `SortUIProtocol` + `RichSortUI` (commit `cafcc2b`)
- Added `prompt_task_selection(tasks)` to `SortUIProtocol` (Protocol stub) with full Google docstring
- Implemented on `RichSortUI`: renders numbered task list, reads single key; 'a' → all tasks; 'x'/unknown → []; 's' → reads number line, parses defensively (skip non-numeric, skip out-of-range), de-duplicates, preserves input order
- `ExtractedTask` imported under `TYPE_CHECKING` in ui.py to avoid runtime import cycle
- 17 unit tests covering: add-all (a/A), skip (x/X), unknown keys, select-subset ('s' with comma/space/mixed separators, out-of-range, non-numeric, deduplication, order preservation), protocol structural check

### Task 3: Controller DI integration + SC1 proof (commit `a35784c`)
- Extended `SortController.__init__` with optional `extractor: Callable[[str], list[ExtractedTask]] | None = None` and `writer: TaskWriter | None = None` (positional signature unchanged — backward compat)
- Added `_maybe_extract_tasks(note)`: SC1 gate as first line (`if not config.features.task_extraction: return`), then None-guard for missing extractor/writer, then extract → prompt → write pipeline
- Hooked `_maybe_extract_tasks(note)` in `_sort_one_note` MOVE branch after `record_move`
- Updated `build_default_controller` to construct and inject real `extract_tasks` + `TaskWriter`
- 5 controller-extraction tests: SC1 disabled proof, enabled-move full pipeline with real TaskWriter, preview-as-input check, enabled-skip zero calls, enabled-no-tasks no prompt/write
- All 6 Phase-4 `test_controller_integration.py` tests still pass unchanged

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | TaskWriter + extracted_tasks_dir | `2d6a41c` | config.py, extractor.py, test_task_writer.py |
| 2 | prompt_task_selection A/S/X | `cafcc2b` | ui.py, test_extraction_ui.py |
| 3 | Controller DI + SC1 proof | `a35784c` | controller.py, test_controller_extraction.py |

## Final Verification

- `mypy src`: 18 files, 0 errors
- `ruff check src tests`: all checks passed
- `pytest -m 'not integration' --cov=notes_os --cov-fail-under=80`: **305 passed, 95.06% coverage**
- `pytest tests/sorter/test_controller_integration.py`: **6 passed** (Phase 4 backward compat confirmed)

## Deviations from Plan

None — plan executed exactly as written.

Minor implementation choices within plan discretion:
- `Callable`, `Sequence`, and `Path` placed in `TYPE_CHECKING` blocks (TC003 ruff rule) rather than regular imports — no behavior change, cleaner import structure
- Dead-code first `SpyUI` construction removed from SC1 test (duplicate that was overridden)

## Known Stubs

None — all functionality is fully implemented:
- `TaskWriter.write` writes real files (tested with `tmp_path` + injected clock)
- `prompt_task_selection` returns real user-selected tasks (tested with scripted I/O)
- `_maybe_extract_tasks` runs the full pipeline (tested with SpyExtractor + SpyUI + real TaskWriter)

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: T-05-03 mitigated | src/notes_os/sorter/extractor.py | Filename constructed as `clock().isoformat() + ".md"` — no user-controlled path segments; joined under frozen `target_dir` via pathlib; open in append mode only — no path traversal from note content |
| threat_flag: T-05-05 mitigated | src/notes_os/sorter/controller.py | `_maybe_extract_tasks` SC1 gate returns before any work when `task_extraction=False` (default); zero added cost on default path |

## Self-Check: PASSED

- FOUND: src/notes_os/config.py (extracted_tasks_dir field added)
- FOUND: src/notes_os/sorter/extractor.py (TaskWriter class added)
- FOUND: src/notes_os/sorter/ui.py (prompt_task_selection on Protocol + RichSortUI)
- FOUND: src/notes_os/sorter/controller.py (_maybe_extract_tasks + DI params)
- FOUND: tests/sorter/test_task_writer.py
- FOUND: tests/sorter/test_extraction_ui.py
- FOUND: tests/sorter/test_controller_extraction.py
- FOUND: commit 2d6a41c (TaskWriter + config)
- FOUND: commit cafcc2b (prompt_task_selection)
- FOUND: commit a35784c (controller DI + SC1)
- FOUND: mypy 0 errors (18 source files)
- FOUND: 305 tests pass, 95.06% coverage >= 80% gate

---
*Phase: 05-task-extraction*
*Completed: 2026-06-07*
