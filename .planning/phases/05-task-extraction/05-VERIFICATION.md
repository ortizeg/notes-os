---
phase: 05-task-extraction
verified: 2026-06-07T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 5: Task Extraction Verification Report

**Phase Goal:** After routing a note, opt-in users review heuristically extracted action items and write selected tasks as Markdown checkboxes — INVISIBLE when disabled (default off).

**Verified:** 2026-06-07
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `task_extraction=false` (default) → NO extraction/UI runs; sort flow byte-identical to Phase 4 (spy counts == 0) | VERIFIED | `_maybe_extract_tasks` first line is `if not self._config.features.task_extraction: return`; `TestExtractionDisabled.test_disabled_move_no_extraction_calls` asserts spy_extractor.call_count == 0, spy_ui.prompt_task_selection_call_count == 0, spy_writer.call_count == 0, session.summary().moved == 1 |
| 2 | `task_extraction=true` → extractor finds ≥1 action item from a note with known patterns (action phrase / named commitment / inline date) | VERIFIED | `extract_tasks` covers all three LOCKED families with compiled regexes; `test_extractor.py` has 7 parametrized action-phrase cases, 3 named-commitment cases, 4 inline-date cases; extractor module at 100% coverage |
| 3 | add-all / select-subset / skip — only selected tasks written | VERIFIED | `prompt_task_selection` in `ui.py` implements 'a'/'s'/'x' paths; `TestExtractionEnabled.test_enabled_move_full_extraction_pipeline` asserts only `task_b` appears in daily file, `task_a` is absent; `test_extraction_ui.py` covers each branch exhaustively |
| 4 | Tasks appended as Markdown checkboxes to YYYY-MM-DD.md; file created if absent | VERIFIED | `TaskWriter.write()` uses append mode `"a"`; `test_task_writer.py` covers create-if-absent, append-if-present, empty no-op, ISO filename format — all under `tmp_path` with injected clock |

**Score:** 4/4 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/notes_os/sorter/extractor.py` | `extract_tasks(text: str) -> list[ExtractedTask]` pure scanner + frozen `ExtractedTask` + `TaskWriter` plain class | VERIFIED | 246 lines; all three components present; `ExtractedTask` is frozen Pydantic V2 `BaseModel`; `TaskWriter` is a plain class (not a model); pure function with no I/O |
| `src/notes_os/sorter/ui.py` | `SortUIProtocol.prompt_task_selection` + `RichSortUI` implementation | VERIFIED | Protocol method defined with full docstring; `RichSortUI.prompt_task_selection` implements A/S/X keystroke paths; injected key_reader and line_reader used throughout |
| `src/notes_os/sorter/controller.py` | DI-injected extractor+writer; post-move extraction gated on `config.features.task_extraction` | VERIFIED | Two optional `__init__` params added after existing 5 (backward-compat preserved); `_maybe_extract_tasks` called from MOVE branch only; `build_default_controller` wires real `extract_tasks` + `TaskWriter` |
| `src/notes_os/config.py` | `FeaturesConfig.task_extraction: bool = False` + `extracted_tasks_dir: Path` field | VERIFIED | `task_extraction: bool = False` already present; `extracted_tasks_dir: Path = Field(default_factory=lambda: Path.home() / ".notes-os" / "extracted-tasks")` added |
| `tests/sorter/test_extractor.py` | Unit tests for all signal families + empty/no-match + purity | VERIFIED | 200 lines; 7 parametrized action phrases, 3 named commitments, 4 date patterns, negative/empty cases, purity/determinism, deduplication, frozen-model assertion |
| `tests/sorter/test_task_writer.py` | TaskWriter writer tests under `tmp_path` with injected clock | VERIFIED | 166 lines; covers create-if-absent, append-if-present, empty no-op, filename format, nested parent creation, default clock, return value |
| `tests/sorter/test_extraction_ui.py` | A/S/X interaction branch tests | VERIFIED | 211 lines; covers add-all uppercase/lowercase, skip, unknown keys, select with comma/space/mixed separators, out-of-range/non-numeric ignored, deduplication, ordering, Protocol isinstance check |
| `tests/sorter/test_controller_extraction.py` | SC1 off-by-default proof + enabled-path proof | VERIFIED | 562 lines; 4 test classes: Disabled (SC1), Enabled (full pipeline), Skip path, No-tasks path |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `controller.py` | `extractor.py extract_tasks + TaskWriter` | DI-injected callables; invoked after successful MOVE when `config.features.task_extraction` is True | WIRED | `build_default_controller` imports and passes `extractor=extract_tasks, writer=writer`; `_sort_one_note` MOVE branch calls `self._maybe_extract_tasks(note)` |
| `controller.py` | `ui.py prompt_task_selection` | UI prompt for add-all/select/skip on extracted tasks | WIRED | `self._ui.prompt_task_selection(tasks)` called inside `_maybe_extract_tasks` on enabled path when tasks found |
| `SortController.__init__` | Phase 4 call sites | Optional params with defaults `None` — positional signature unchanged | WIRED | `extractor: Callable[[str], list[ExtractedTask]] | None = None` and `writer: TaskWriter | None = None` appended after existing 5 params; Phase 4 `test_controller_integration.py` 6/6 pass unchanged |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `TaskWriter.write()` | `tasks: Sequence[ExtractedTask]` | Injected from controller after `_extractor(note.preview)` | Yes — note preview text flows through extractor to writer | FLOWING |
| `test_controller_extraction.py enabled test` | `daily_file` content | Real `TaskWriter` with `tmp_path` + fixed clock writes actual file | Yes — `daily_file.read_text()` asserted against specific line content | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| extractor module 100% coverage across full suite | `.pixi/envs/default/bin/pytest -m 'not integration' --cov=notes_os.sorter.extractor --cov-report=term-missing -q` | 100% (53/53 stmts), 305 passed | PASS |
| Overall suite ≥80% coverage | `.pixi/envs/default/bin/pytest -m 'not integration' --cov=notes_os --cov-fail-under=80 -q` | 95.06% (850 stmts, 42 missed), 305 passed | PASS |
| mypy strict — 18 source files, zero errors | `.pixi/envs/default/bin/mypy src` | `Success: no issues found in 18 source files` | PASS |
| ruff check + format | `.pixi/envs/default/bin/ruff check src tests && ruff format --check src tests` | All checks passed; 36 files already formatted | PASS |
| Phase 4 backward compatibility | `.pixi/envs/default/bin/pytest tests/sorter/test_controller_integration.py -v -q` | 6/6 passed | PASS |

---

## Probe Execution

No probe scripts declared in plan files. Step 7c: SKIPPED (no probe-*.sh files declared or present).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TASK-01 | 05-01 | Heuristic scan when enabled | SATISFIED | `extract_tasks` with 3 LOCKED signal families; 100% coverage |
| TASK-02 | 05-02 | add-all / select-subset / skip | SATISFIED | `prompt_task_selection` A/S/X in `ui.py`; tested in `test_extraction_ui.py` and `test_controller_extraction.py` |
| TASK-03 | 05-02 | Append Markdown checkboxes to `~/.notes-os/extracted-tasks/YYYY-MM-DD.md` | SATISFIED | `TaskWriter.write()` append-mode, YYYY-MM-DD filename, create-if-absent; tested under `tmp_path` |
| TASK-04 | 05-02 | Off by default, `[features] task_extraction=true` | SATISFIED | `FeaturesConfig.task_extraction: bool = False`; SC1 gate as first line of `_maybe_extract_tasks`; SC1 test proves zero calls when disabled |

---

## Anti-Patterns Found

Scanned: `extractor.py`, `controller.py`, `ui.py`, `config.py`, `test_extractor.py`, `test_task_writer.py`, `test_extraction_ui.py`, `test_controller_extraction.py`.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | None found |

No `TBD`, `FIXME`, or `XXX` markers. No stub returns (`return null / {} / []` without data source). No `print()` calls. No hardcoded empty props. No unreferenced debt markers.

---

## Human Verification Required

None. All observable behaviors are verifiable programmatically via the injected-I/O test architecture. The UI renders to a `StringIO` console in tests; no real terminal needed.

---

## Gaps Summary

None. All four success criteria are verified with passing tests and clean static analysis.

---

## SC1 Critical Check — Detailed

The `_maybe_extract_tasks` method body (controller.py lines 187-231):

- **First executable line:** `if not self._config.features.task_extraction: return` — no extractor, UI, or writer reference appears before this guard.
- **Test proof:** `TestExtractionDisabled.test_disabled_move_no_extraction_calls` constructs the controller with real `SpyExtractor` and `SpyWriter` injected but `task_extraction=False`, scripts a move ('x' key), runs the full loop, and asserts all three spy call counts are exactly 0 while `session.summary().moved == 1`.

## pyproject.toml Checks

- `notes_os.sorter.extractor` is present in the `[[tool.mypy.overrides]]` module list (line 73).
- `disallow_any_explicit = false` applies to the extractor module (required because `ExtractedTask` is a `BaseModel`).
- `TaskWriter` is a plain class — it does NOT extend `BaseModel`, so no additional override needed.
- No new `[project.scripts]` entries were added (only the pre-existing `notes = "notes_os.app:main"` exists).

---

_Verified: 2026-06-07_
_Verifier: Claude (gsd-verifier)_
