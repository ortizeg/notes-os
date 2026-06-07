---
phase: 02-applescript-bridge
plan: "02"
subsystem: sorter/bridge
tags: [applescript, osascript, exceptions, protocol, mock, pytest, pydantic]

requires:
  - phase: 02-01
    provides: NotesRepositoryProtocol, AppleScriptNotesRepository read foundation, _run_osascript, models
provides:
  - notes_os.exceptions — NotesError(NotesOSError), FolderNotFoundError(NotesError), NotesMoveError(NotesError)
  - AppleScriptNotesRepository.move_note — BRDG-03 write op; resolves 2/3-level PARA paths; sentinel-mapped exceptions
  - AppleScriptNotesRepository.ensure_folder — BRDG-04 idempotent nested-path creation
  - AppleScriptNotesRepository._folder_reference — private helper building nested AppleScript folder references
  - tests/sorter/conftest.py — MockNotesRepository + sample_notes/sample_structure/mock_repo fixtures
affects:
  - 02-03 — unit/integration tests mock _run_osascript; consume MockNotesRepository and shared fixtures; sentinel detection is in move_note (not _run_osascript)
  - future phases — catch NotesError (or NotesOSError) at session/router level for all bridge errors

tech-stack:
  added: []
  patterns:
    - "Sentinel-in-move_note: FOLDER_NOT_FOUND/NOTE_NOT_FOUND tokens inspected in move_note after _run_osascript raises NotesError; _run_osascript stays generic (raises NotesError on any non-zero exit)"
    - "Idempotent ensure_folder via per-prefix existence guard in a single AppleScript tell block"
    - "Double-quote escaping in _folder_reference: name.replace('\"', '\"\"') before interpolation (T-02-04)"
    - "MockNotesRepository uses set-of-known-paths derived from seed structure; ensure_folder expands the set idempotently"

key-files:
  created:
    - tests/sorter/conftest.py
  modified:
    - src/notes_os/exceptions.py
    - src/notes_os/sorter/notes.py

key-decisions:
  - "Sentinel detection in move_note (not _run_osascript): _run_osascript raises generic NotesError on any non-zero exit; move_note inspects the error message for FOLDER_NOT_FOUND/NOTE_NOT_FOUND tokens and re-raises as the appropriate subclass. This keeps _run_osascript reusable for ensure_folder and future operations that need no sentinel logic."
  - "NotesOSError import removed from notes.py: all raises in the bridge now use NotesError (a NotesOSError subclass), so the direct NotesOSError import became unused and was dropped."
  - "MockNotesRepository re-exported via __all__ in conftest.py alongside NotesRepositoryProtocol so plan 02-03 tests can import both from one location."

patterns-established:
  - "AppleScript folder reference: _folder_reference(path) builds 'folder X of folder Y...' from reversed path tuple with double-quote escaping"
  - "Bridge error hierarchy: catch NotesError for all AppleScript errors; FolderNotFoundError/NotesMoveError for move-specific conditions; NotesOSError for any NotesOS-wide error"

requirements-completed: [BRDG-03, BRDG-04, BRDG-06]

duration: 5min
completed: 2026-06-07
---

# Phase 02 Plan 02: AppleScript Bridge Write Operations Summary

**Typed error hierarchy (NotesError/FolderNotFoundError/NotesMoveError), move_note + ensure_folder AppleScript write ops with sentinel-mapped exceptions, and MockNotesRepository in-memory test double with shared fixtures.**

## Performance

- **Duration:** ~5 minutes
- **Started:** 2026-06-07T20:01:54Z
- **Completed:** 2026-06-07T20:07:00Z
- **Tasks:** 3 / 3
- **Files modified:** 3 (2 modified, 1 created)

## Accomplishments

- Added `NotesError(NotesOSError)`, `FolderNotFoundError(NotesError)`, `NotesMoveError(NotesError)` to `exceptions.py`; narrowed all bridge raises from `NotesOSError` to `NotesError` (02-01 seam fulfilled)
- Implemented `_folder_reference`, `move_note`, and `ensure_folder` on `AppleScriptNotesRepository`; no `NotImplementedError` remains; `isinstance(repo, NotesRepositoryProtocol)` is True
- Created `MockNotesRepository` in `tests/sorter/conftest.py` with `sample_notes`, `sample_structure`, `mock_repo` fixtures; zero AppleScript imports; Protocol-compatible via structural subtyping

## Task Commits

1. **Task 1: Add NotesError hierarchy and narrow read-side raises** - `2db4763` (feat)
2. **Task 2: Implement move_note, ensure_folder, and _folder_reference** - `f42beb5` (feat)
3. **Task 3: MockNotesRepository test double and sample fixtures** - `094befe` (feat)

## Files Created/Modified

- `src/notes_os/exceptions.py` — Added `NotesError`, `FolderNotFoundError`, `NotesMoveError` with Google-style docstrings
- `src/notes_os/sorter/notes.py` — Implemented `_folder_reference`, `move_note`, `ensure_folder`; narrowed `_run_osascript` raise from `NotesOSError` to `NotesError`; removed now-unused `NotesOSError` import
- `tests/sorter/conftest.py` — Created `MockNotesRepository` + `sample_notes` / `sample_structure` / `mock_repo` fixtures

## Interface Seams for Plan 02-03

### (a) Sentinel detection location

Sentinel detection happens **inside `move_note`**, not inside `_run_osascript`:

```
move_note calls self._run_osascript(script)
  → _run_osascript raises NotesError(stderr_or_message) on non-zero exit
  → move_note catches NotesError, inspects str(exc):
      "FOLDER_NOT_FOUND" in msg → re-raise FolderNotFoundError(folder_path)
      "NOTE_NOT_FOUND" in msg   → re-raise NotesMoveError(note_id)
      otherwise                 → re-raise NotesError unchanged
```

**Plan 02-03 implication:** Mock `_run_osascript` to raise `NotesError("FOLDER_NOT_FOUND")` or `NotesError("NOTE_NOT_FOUND")` to exercise `move_note`'s sentinel-mapping logic. Do NOT mock at the `subprocess.run` level for these tests.

### (b) MockNotesRepository constructor signature and fixture names

```python
class MockNotesRepository:
    def __init__(self, notes: list[Note], structure: ParaStructure) -> None: ...
    moves: list[tuple[str, tuple[str, ...]]]      # recorded after move_note
    created_folders: list[tuple[str, ...]]         # recorded after ensure_folder (idempotent)
```

Shared fixtures in `tests/sorter/conftest.py`:
- `sample_notes` → `list[Note]` (3 notes: HTML body, Unicode title, empty body)
- `sample_structure` → `ParaStructure` (4 PARA roots; Projects has General + Web subs)
- `mock_repo` → `MockNotesRepository(sample_notes, sample_structure)`

`NotesRepositoryProtocol` is also re-exported from `conftest.py` via `__all__`.

## Decisions Made

1. **Sentinel detection in move_note**: `_run_osascript` stays generic (raises `NotesError` on any non-zero exit). `move_note` inspects the error message for `FOLDER_NOT_FOUND`/`NOTE_NOT_FOUND` and re-raises as the typed subclass. This keeps `_run_osascript` reusable for `ensure_folder` and future operations without sentinel logic.

2. **NotesOSError import removed from notes.py**: All raises in the bridge now use `NotesError` (a `NotesOSError` subclass), so the direct `NotesOSError` import became unused and was dropped per ruff F401.

3. **`noqa: RUF001` on Unicode test data**: The `sample_notes` fixture intentionally contains a RIGHT SINGLE QUOTATION MARK (U+2019) in the note title and preview to test Unicode-title handling. Two targeted `# noqa: RUF001` suppressions with justification comments were added — not a blanket suppression.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Verification Results

| Check | Result |
|-------|--------|
| `ruff check src/ tests/` | PASS — 0 errors |
| `mypy src/ tests/sorter/` (strict, 12 files) | PASS — 0 errors |
| Exception MRO smoke test | PASS |
| `_folder_reference` 2-level and 3-level | PASS |
| `isinstance(AppleScriptNotesRepository(...), NotesRepositoryProtocol)` | PASS |
| `MockNotesRepository` behavior (moves, inbox removal, idempotent ensure_folder, typed exceptions) | PASS |
| `pytest -m 'not integration'` (13 tests) | PASS — 13/13 |

## Requirements Addressed

- **BRDG-03:** `move_note(note_id, folder_path)` moves a note by ID to a resolved 2-level or 3-level PARA path; does not call `ensure_folder`
- **BRDG-04:** `ensure_folder(folder_path)` creates missing folders idempotently; nested paths (Archive/2026) supported; no duplicate on second call
- **BRDG-06:** `NotesError`, `FolderNotFoundError`, `NotesMoveError` exist as `NotesOSError` descendants; `move_note` maps missing-folder → `FolderNotFoundError`, missing-note → `NotesMoveError`, other non-zero → `NotesError`; read ops raise `NotesError`

## Threat Surface Scan

No new trust boundaries introduced beyond the plan's registered threats:
- T-02-04: Mitigated — `_folder_reference` double-quote escapes every folder name before interpolation; list-arg `osascript` (no shell)
- T-02-05: Mitigated — `move_note` verifies folder `exists` before `move`; raises `FolderNotFoundError` instead of silently creating; `move_note` never calls `ensure_folder`
- T-02-06: Mitigated — all failures surface as `NotesError` subclasses; caller (router/UI, later phases) catches and continues — verified by `MockNotesRepository` raising correctly

## Known Stubs

None — all stubs from plan 02-01 (`move_note`, `ensure_folder`) are now fully implemented.

## Self-Check: PASSED

Files verified:
- FOUND: src/notes_os/exceptions.py
- FOUND: src/notes_os/sorter/notes.py
- FOUND: tests/sorter/conftest.py

Commits verified:
- 2db4763 — feat(02-02): add NotesError hierarchy and narrow read-side raises
- f42beb5 — feat(02-02): implement move_note, ensure_folder, and _folder_reference
- 094befe — feat(02-02): add MockNotesRepository and sample fixtures to tests/sorter/conftest.py

---
*Phase: 02-applescript-bridge*
*Completed: 2026-06-07*
