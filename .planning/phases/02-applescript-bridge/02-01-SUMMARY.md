---
phase: 02-applescript-bridge
plan: "01"
subsystem: sorter/bridge
tags: [applescript, pydantic, protocol, html-stripper, osascript]
dependency_graph:
  requires: []
  provides:
    - notes_os.sorter.models — Note, ParaStructure, BridgeConfig, FolderPath
    - notes_os.sorter.notes — NotesRepositoryProtocol, AppleScriptNotesRepository (read ops)
    - _strip_html — stdlib HTML-to-plain-text + entity decode + truncate
    - _run_osascript — subprocess wrapper with justified noqa
  affects:
    - 02-02 — write ops implement move_note / ensure_folder bodies on AppleScriptNotesRepository
    - 02-03 — tests mock _run_osascript; use _FIELD_SEP/_RECORD_SEP constants from notes.py
tech_stack:
  added: []
  patterns:
    - pydantic.dataclasses (not BaseModel) for mypy 2.x strict + disallow_any_explicit compat
    - runtime_checkable Protocol for bridge contract
    - chr(31)/chr(30) delimiter constants for tamper-resistant AppleScript output parsing
    - subprocess.run list-args, noqa: S603 S607 justified on osascript only
key_files:
  created:
    - src/notes_os/sorter/models.py
    - src/notes_os/sorter/notes.py
  modified: []
decisions:
  - "pydantic.dataclasses used instead of BaseModel: mypy 2.1 + disallow_any_explicit = true raises [explicit-any] on BaseModel subclasses due to pydantic internals; dataclasses avoid this with identical validation and frozen semantics"
  - "PLR2004 (magic-value comparison) not enabled in pyproject ruff config — noqa: PLR2004 was spurious; removed"
  - "record.strip() must NOT be applied before splitting note records: trailing _FIELD_SEP marks an empty body field; stripping would cause len(parts)==2 and the empty-body note would be incorrectly skipped"
metrics:
  duration: "6 minutes"
  completed_date: "2026-06-07"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 0
---

# Phase 02 Plan 01: AppleScript Bridge Read Foundation Summary

Read-side foundation of the Apple Notes bridge: frozen Pydantic V2 data models, the
`NotesRepositoryProtocol` contract, the `osascript` execution wrapper, the stdlib HTML stripper,
and `get_inbox_notes` / `get_para_structure` read operations.

## One-liner

AppleScript bridge read foundation: `NotesRepositoryProtocol` + RS/US-delimited osascript
wrapper + stdlib HTML stripper + `get_inbox_notes`/`get_para_structure` on
`AppleScriptNotesRepository` — fully typed, mypy strict, ruff clean.

## What Was Built

### `src/notes_os/sorter/models.py`

- `FolderPath: TypeAlias = tuple[str, ...]` — BRDG-07 path contract type
- `Note` — frozen pydantic dataclass: `id`, `title`, `body` (raw HTML), `preview` (stripped)
- `ParaStructure` — frozen pydantic dataclass: `roots: tuple[str, ...]`, `subfolders: dict[str, tuple[str, ...]]`, plus `subfolders_for(root) -> tuple[str, ...]` helper
- `BridgeConfig` — frozen pydantic dataclass: `inbox_folder="Notes"`, `preview_length=Field(default=250, ge=50, le=1000)`, `para_folders=("Projects","Areas","Resources","Archive")`

### `src/notes_os/sorter/notes.py`

- `_FIELD_SEP = chr(31)` — ASCII Unit Separator (0x1F); separates fields within a record
- `_RECORD_SEP = chr(30)` — ASCII Record Separator (0x1E); separates records
- `_HTMLStripper(HTMLParser)` — block-tag boundary injection + whitespace collapse
- `_strip_html(raw, preview_length) -> str` — strips tags, decodes entities via `html.unescape`, truncates
- `NotesRepositoryProtocol` — `@runtime_checkable` Protocol with all four signatures: `get_inbox_notes`, `get_para_structure`, `move_note`, `ensure_folder`
- `AppleScriptNotesRepository` — concrete class satisfying the protocol:
  - `__init__(config: BridgeConfig)` — DI; no global state
  - `_run_osascript(script: str) -> str` — subprocess wrapper
  - `get_inbox_notes() -> list[Note]` — BRDG-01
  - `get_para_structure() -> ParaStructure` — BRDG-02
  - `move_note` / `ensure_folder` — typed `NotImplementedError` placeholders for 02-02

## Interface Seams for Plan 02-02

### (a) `NotesOSError` raise sites — narrow to `NotesError` in 02-02

All three locations raise `NotesOSError` today. Plan 02-02 introduces the `NotesError` hierarchy
and re-points these raises to the appropriate subclass (e.g. `AppleScriptError`).

| Location | File | Approximate line | Comment |
|----------|------|-----------------|---------|
| `_run_osascript` | `notes.py` | ~276 | `# 02-02: narrow to NotesError (AppleScriptError subclass)` |
| `get_inbox_notes` docstring | `notes.py` | Raises section | `(02-02: narrow to NotesError)` |
| `get_para_structure` docstring | `notes.py` | Raises section | `(02-02: narrow to NotesError)` |

### (b) Delimiter constants and AppleScript output format

```
_FIELD_SEP = chr(31)   # ASCII Unit Separator (0x1F)
_RECORD_SEP = chr(30)  # ASCII Record Separator (0x1E)
```

**`get_inbox_notes` output format (one record per note):**
```
<noteID>  _FIELD_SEP  <name>  _FIELD_SEP  <body-html>
^---------- joined by _RECORD_SEP between notes ----------^
```
- Empty inbox → empty string output → `[]`
- Empty body → trailing `_FIELD_SEP` on the record; do NOT strip the record before splitting

**`get_para_structure` output format:**
- Root with subfolders: `<rootName>  _FIELD_SEP  <subfolderName>` (one record per subfolder)
- Root with no subfolders: bare `<rootName>` record (so root still appears)
- Records joined by `_RECORD_SEP`

**Plan 02-03 note:** Import `_FIELD_SEP`, `_RECORD_SEP` from `notes_os.sorter.notes` to build
mock subprocess stdout in unit tests. Do not hardcode the char values.

### (c) `move_note` / `ensure_folder` placeholders

Both methods exist on `AppleScriptNotesRepository` with correct Protocol signatures and raise
`NotImplementedError("Implemented in plan 02-02")`. Plan 02-02 replaces the bodies with working
AppleScript write operations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `pydantic.dataclasses` used instead of `BaseModel`**
- **Found during:** Task 1
- **Issue:** `mypy 2.1` + `disallow_any_explicit = true` (pyproject.toml) raises `[explicit-any]` on every
  `class Foo(BaseModel)` definition because Pydantic's internal `model_fields: ClassVar[dict[str, Any]]`
  bleeds through to subclasses. The pydantic mypy plugin (`pydantic.mypy`) is also incompatible with
  mypy 2.x (`AttributeError: ExpandTypeVisitor`), so there is no plugin workaround.
- **Fix:** Use `pydantic.dataclasses.dataclass` (Pydantic V2) with `ConfigDict(frozen=True)`.
  These provide identical validation, `ValidationError` on constraint violation, and `FrozenInstanceError`
  on mutation — without triggering `[explicit-any]`.
- **Files modified:** `src/notes_os/sorter/models.py`
- **Commit:** 83f7236

**2. [Rule 1 - Bug] Empty-body note parsing: `record.strip()` before split**
- **Found during:** Task 3 verification
- **Issue:** `record.strip()` trims the trailing `_FIELD_SEP` from a note record with an empty HTML body,
  causing `len(parts) == 2` instead of 3, so the note is silently skipped instead of being returned with
  `preview == ""`.
- **Fix:** Check `record.strip()` only for the "is this record empty?" guard; do NOT strip the record
  itself before splitting on `_FIELD_SEP`.
- **Files modified:** `src/notes_os/sorter/notes.py`
- **Commit:** 86d9237

## Verification Results

| Check | Result |
|-------|--------|
| `mypy src/` (strict, 10 files) | PASS — 0 errors |
| `ruff check src/` (full ruleset) | PASS — 0 errors |
| Task 1 smoke test | PASS |
| Task 2 smoke test | PASS |
| Task 3 behavior tests (parse logic) | PASS |
| `pytest -m 'not integration'` (13 tests) | PASS — 13/13 |

## Requirements Addressed

- **BRDG-01:** `get_inbox_notes()` → `list[Note]` with stripped previews; empty inbox → `[]`
- **BRDG-02:** `get_para_structure()` → `ParaStructure` with all config roots; childless roots → `()`
- **BRDG-05:** `_strip_html` uses stdlib `html.parser` only; decodes entities; separates block tags; truncates to `preview_length`
- **BRDG-07:** `NotesRepositoryProtocol` (`@runtime_checkable`) declares all four operations; `AppleScriptNotesRepository` registers as an instance

## Threat Surface Scan

No new trust boundaries introduced beyond the plan's registered threats:
- T-02-01: Mitigated — `subprocess.run` with list args, `noqa: S603 S607` justified
- T-02-02: Mitigated — folder names escaped with AppleScript double-quote doubling; config is frozen
- T-02-03: Mitigated — chr(31)/chr(30) delimiters; empty-body guard fixed to not silently drop notes

## Known Stubs

| Stub | File | Notes |
|------|------|-------|
| `move_note` | `src/notes_os/sorter/notes.py` | `NotImplementedError("Implemented in plan 02-02")` — plan 02-02 fills the body |
| `ensure_folder` | `src/notes_os/sorter/notes.py` | `NotImplementedError("Implemented in plan 02-02")` — plan 02-02 fills the body |

These stubs are intentional; plan 02-02 is the direct successor and implements the write operations.

## Self-Check: PASSED

Files created:
- FOUND: src/notes_os/sorter/models.py
- FOUND: src/notes_os/sorter/notes.py

Commits exist:
- 83f7236 — feat(02-01): add frozen Pydantic V2 bridge data models
- 299222c — feat(02-01): add NotesRepositoryProtocol, HTML stripper, and osascript wrapper
- 86d9237 — feat(02-01): implement get_inbox_notes and get_para_structure read operations
