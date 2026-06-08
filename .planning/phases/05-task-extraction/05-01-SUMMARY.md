---
phase: 05-task-extraction
plan: 01
subsystem: extractor
tags: [pydantic, regex, heuristic, tdd, pure-function]

# Dependency graph
requires:
  - phase: 04-sorting-core
    provides: frozen Pydantic BaseModel pattern (models.py / session.py) and mypy override convention
provides:
  - "extract_tasks(text: str) -> list[ExtractedTask]: pure, deterministic heuristic scanner"
  - "ExtractedTask: frozen Pydantic V2 BaseModel with text: str field"
  - "Three LOCKED signal families: action phrases / named commitments / inline dates"
  - "TASK-01 extraction contract stable and ready for 05-02 UI integration"
affects:
  - 05-02-task-ui
  - any future plan wiring extract_tasks to SortController or writer

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure function (no I/O, no config, no global state): extract_tasks maps str -> list[ExtractedTask]"
    - "Module-level compiled regexes (re.compile): performance + ReDoS safety via non-backtracking alternations"
    - "TDD RED/GREEN cycle: test file committed first (import error = RED), then implementation (GREEN)"
    - "mypy disallow_any_explicit=false override appended for each new Pydantic BaseModel module"

key-files:
  created:
    - src/notes_os/sorter/extractor.py
    - tests/sorter/test_extractor.py
  modified:
    - pyproject.toml

key-decisions:
  - "extract_tasks splits on [.\\n!?]+ into short fragments before regex matching — avoids whole-body ReDoS (T-05-01)"
  - "ExtractedTask has a single text: str field — minimal model; downstream UI/writer can extend in 05-02"
  - "De-duplication by .text preserving first-seen order — deterministic output for identical input"
  - "No new exceptions.py subclass needed — extractor returns [] on bad/empty input rather than raising"
  - "notes_os.sorter.extractor appended to [[tool.mypy.overrides]] module list (7th entry) — Pydantic BaseModel explicit-Any pattern"

patterns-established:
  - "Pure extractor pattern: heuristic scanner with no side effects, stub-free, fully unit-testable without tmp_path"
  - "Signal regex families compiled at module level (re.IGNORECASE, no nested quantifiers)"

requirements-completed: [TASK-01]

# Metrics
duration: 2min
completed: 2026-06-07
---

# Phase 5 Plan 01: Pure Heuristic Task Extractor Summary

**Regex-based `extract_tasks(text)` with frozen `ExtractedTask` Pydantic model detecting action phrases, named commitments, and inline dates — pure, deterministic, 100% coverage.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-07T22:46:51Z
- **Completed:** 2026-06-07T22:49:06Z
- **Tasks:** 3 (TDD RED + GREEN + chore)
- **Files modified:** 3

## Accomplishments

- TDD RED phase: `tests/sorter/test_extractor.py` with 25 parametrized test cases covering all three LOCKED signal families (action phrases, named commitments, inline dates), empty/no-match, purity/determinism, de-duplication, and frozen model contract
- TDD GREEN phase: `src/notes_os/sorter/extractor.py` with pure `extract_tasks(text: str) -> list[ExtractedTask]`, frozen `ExtractedTask(BaseModel)`, and 6 module-level compiled regexes for the three signal families
- `pyproject.toml` mypy override extended to 7 entries; `mypy src` zero errors; extractor at 100% coverage; overall suite 95.08% (274 tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing tests (RED)** - `85fb3b1` (test)
2. **Task 2: Implement extractor.py (GREEN)** - `7160c6c` (feat)
3. **Task 3: Register in mypy override + verify coverage** - `717fd50` (chore)

**Plan metadata:** (pending final commit)

_Note: TDD plan — test commit precedes feat commit per RED/GREEN discipline._

## Files Created/Modified

- `src/notes_os/sorter/extractor.py` — Pure heuristic scanner: `ExtractedTask` frozen Pydantic V2 BaseModel + `extract_tasks(text)` function with 6 compiled signal regexes
- `tests/sorter/test_extractor.py` — 25 parametrized unit tests across all three LOCKED signal families, empty/no-match, purity, de-duplication, and frozen model mutation guard
- `pyproject.toml` — `notes_os.sorter.extractor` appended to `[[tool.mypy.overrides]]` module list

## Decisions Made

- **Fragment splitting on `[.\n!?]+` before regex matching** — operates on short sentence fragments instead of the entire note body, preventing ReDoS on adversarial input (T-05-01 mitigation). Simple character-class split, no nested quantifiers.
- **Single `text: str` field on ExtractedTask** — minimal model; line number, confidence score, or matched-family metadata can be added in 05-02 if the UI selection step requires it. YAGNI for now.
- **De-duplication by `.text` preserving first-seen order** — identical fragments (e.g., "I need to call Bob" repeated twice) appear once; order of first match is stable → deterministic output.
- **No new `NotesOSError` subclass** — `extract_tasks` returns `[]` on empty/whitespace input rather than raising; extractor has no failure modes in this plan.
- **`notes_os.sorter.extractor` added to mypy `disallow_any_explicit=false` override** — `ExtractedTask(BaseModel)` inherits Pydantic's internal `Any` API; identical treatment to all 6 prior BaseModel modules.

## Deviations from Plan

None — plan executed exactly as written.

The `E741` ambiguous-variable-name lint error in the `DATE_CASES` parametrize ids (variable named `l`) was fixed immediately during Task 1 formatting, before the RED commit. This is a normal TDD/lint hygiene step, not a plan deviation.

## Issues Encountered

None — ruff, mypy, and pytest all passed after implementation without iteration.

## TDD Gate Compliance

RED gate commit: `85fb3b1` — `test(05-01): failing tests for extract_tasks signal families`
GREEN gate commit: `7160c6c` — `feat(05-01): pure heuristic extract_tasks + ExtractedTask model`
REFACTOR: not needed — code was clean after GREEN.

Both required gates present in git log. Plan type is `tdd`.

## Known Stubs

None — `extract_tasks` is fully implemented, no placeholder or hardcoded return values.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns introduced. Module is pure (no I/O). Threat T-05-01 (ReDoS) mitigated via fragment splitting and simple alternation regexes.

## Next Phase Readiness

- `extract_tasks(text: str) -> list[ExtractedTask]` is the **LOCKED contract** for plan 05-02.
- `ExtractedTask.text` is the field the 05-02 UI and task-writer will consume.
- The extractor is pure and fully tested — 05-02 can build the selection UI and writer against a stable, stub-free interface.
- No blockers.

## Self-Check: PASSED

- FOUND: src/notes_os/sorter/extractor.py
- FOUND: tests/sorter/test_extractor.py
- FOUND: .planning/phases/05-task-extraction/05-01-SUMMARY.md
- FOUND: commit 85fb3b1 (RED gate)
- FOUND: commit 7160c6c (GREEN gate)
- FOUND: commit 717fd50 (chore/override)
- FOUND: mypy override entry for notes_os.sorter.extractor

---
*Phase: 05-task-extraction*
*Completed: 2026-06-07*
