---
phase: 10-perf-bulk-preview
plan: 01
subsystem: applescript-bridge
tags: [perf, bridge, bulk-read, osascript]
requires:
  - AppleScriptNotesRepository.get_inbox_notes (wire format + parse loop)
  - AppleScriptNotesRepository.get_inbox_note_refs (notes-of-inbox ordering source)
provides:
  - get_inbox_note_bodies(offset, count) on NotesRepositoryProtocol
  - get_inbox_note_bodies on AppleScriptNotesRepository (single range osascript read)
  - get_inbox_note_bodies no-backup pass-through on BackingUpNotesRepository
  - get_inbox_note_bodies in-memory slice on MockNotesRepository
affects:
  - Plan 10-02 background worker (consumes this bulk paged read)
tech-stack:
  added: []
  patterns:
    - "Single osascript range read (items N thru M of noteList) replaces per-note by-id reads"
    - "Control-char US/RS delimiters reused verbatim for the bulk wire format"
key-files:
  created: []
  modified:
    - src/notes_os/sorter/notes.py
    - src/notes_os/backup.py
    - tests/sorter/conftest.py
    - tests/sorter/test_notes_unit.py
decisions:
  - "Empty-page guard (count <= 0 returns [] before osascript) lives in Python to avoid an invalid AppleScript range; offset-past-end is handled by the in-script clamp returning empty stdout."
  - "Bulk read reuses the get_inbox_notes parse loop verbatim (split RS, skip empty/malformed, split FS x2, body kept raw, preview via _strip_html) since the wire format is identical."
metrics:
  duration: "~12 min"
  completed: 2026-06-08
  tasks: 2
  files: 4
---

# Phase 10 Plan 01: Bulk Paged Body-Fetch Bridge Summary

Added `get_inbox_note_bodies(offset, count)` — a single AppleScript range read that fetches a
contiguous folder-ordered page of fully-populated `Note` objects, id-aligned to
`get_inbox_note_refs`, replacing the per-note by-id preview path.

## What Was Built

- **`NotesRepositoryProtocol.get_inbox_note_bodies`** (`src/notes_os/sorter/notes.py`) — protocol
  stub with a Google-style docstring documenting folder-order + id-alignment to
  `get_inbox_note_refs`, the empty-page `[]` contract, and `Raises: NotesError`.
- **`AppleScriptNotesRepository.get_inbox_note_bodies`** — one `_run_osascript` call. Sources the
  same node set as `get_inbox_note_refs` (`set noteList to notes of inbox`), reads the clamped
  slice `repeat with i from (offset+1) to lastIdx` (`lastIdx` clamped to `count of noteList` so an
  over-long `count` / past-end `offset` yields empty stdout, not an error), emits
  `<id> FS <name> FS <body>` records joined by RS — the identical wire format to `get_inbox_notes`,
  so the same parse loop is reused. Guards `count <= 0` in Python (returns `[]` before any osascript
  call) to avoid an invalid AppleScript range.
- **`BackingUpNotesRepository.get_inbox_note_bodies`** (`src/notes_os/backup.py`) — pure read
  pass-through in the "Read operations — no backup" section; delegates to
  `self._inner.get_inbox_note_bodies(offset, count)`; never calls `self._backup_manager.create()`.
- **`MockNotesRepository.get_inbox_note_bodies`** (`tests/sorter/conftest.py`) — returns
  `list(self._inbox[offset : offset + count])`, folder-ordered and id-aligned to
  `get_inbox_note_refs` (Python slicing clamps out-of-range offsets/counts to `[]`/short tail).
- **`TestGetInboxNoteBodies`** suite (`tests/sorter/test_notes_unit.py`) — 15 tests covering
  happy/multi-record single-call, empty-page (`count==0` and negative count, both assert
  `mock_run.assert_not_called()`), empty/whitespace stdout, malformed-record skip, trailing-RS skip,
  empty-body preview, preview truncation, ordering/id-alignment, inbox-name double-quote escaping,
  computed 1-based range assertion (`offset=2,count=3` → start `3`, `lastIdx 5`, `notes of inbox`),
  single-call-per-page, and two MockNotesRepository checks (ordered slice without subprocess,
  id-alignment to refs).

## Files Changed

| File | Change |
| ---- | ------ |
| `src/notes_os/sorter/notes.py` | Added `get_inbox_note_bodies` to protocol + AppleScript impl |
| `src/notes_os/backup.py` | Added `get_inbox_note_bodies` no-backup read pass-through |
| `tests/sorter/conftest.py` | Added `get_inbox_note_bodies` in-memory slice to `MockNotesRepository` |
| `tests/sorter/test_notes_unit.py` | Added `TestGetInboxNoteBodies` (15 tests) |

## Verification Results

All commands run via the real pixi binary (`~/.pixi/bin/pixi`, the local shell shim is broken):

| Command | Result |
| ------- | ------ |
| `pixi run mypy` | exit 0 — `Success: no issues found in 22 source files` |
| `pixi run ruff` | exit 0 — `All checks passed!` |
| `pixi run pytest tests/sorter/test_notes_unit.py` | exit 0 — `90 passed in 0.10s` |
| `pixi run pytest -m 'not integration' --cov=notes_os.sorter.notes --cov-report=term-missing` | exit 0 — `371 passed, 6 deselected`; `src/notes_os/sorter/notes.py 193 stmts, 0 miss, 100%` |

- **Coverage on `notes.py`: 100%** (≥95% write-path-adjacent floor met; every line of the new
  method exercised).
- **Single osascript call per page** asserted by `mock_run.call_count == 1` in the happy-path and
  single-call tests.
- No new `type: ignore`; `from __future__ import annotations` remains the first import in both
  edited source files; zero `print()` added.

## Deviations from Plan

None — plan executed exactly as written. Both tasks implemented in order; all acceptance criteria
and `<verify>` commands passed on first run.

## Threat Surface

No new security-relevant surface beyond the plan's `<threat_model>`. Mitigations applied as
specified: inbox name AppleScript-escaped via `.replace('"', '""')` (T-10-01, asserted by the
escaping test); US/RS control-char delimiters reused so note text cannot forge a record boundary
(T-10-02); malformed records logged by field-count only, never body content (T-10-04). No new
packages installed (T-10-SC).

## Known Stubs

None — the method is fully wired through the DI chain (protocol → AppleScript impl → backup
pass-through → mock). Plan 10-02 can call `self.app.repo.get_inbox_note_bodies(...)`.

## Self-Check: PASSED

- All four modified files present on disk; `10-01-SUMMARY.md` written.
- `def get_inbox_note_bodies` present on `NotesRepositoryProtocol` + `AppleScriptNotesRepository`
  (2 in notes.py), `BackingUpNotesRepository` (1 in backup.py), `MockNotesRepository` (1 in conftest.py).
- `class TestGetInboxNoteBodies` present in test_notes_unit.py.
- Backup pass-through contains zero `_backup_manager.create` references (pure read, no backup).

