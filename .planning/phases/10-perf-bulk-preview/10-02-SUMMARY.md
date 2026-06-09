---
phase: 10-perf-bulk-preview
plan: 02
subsystem: tui-sort-screen
tags: [performance, textual, background-worker, preview-load]
requires:
  - "10-01: repo.get_inbox_note_bodies(offset, count) -> list[Note]"
provides:
  - "SortScreen background paged bulk-load worker (_load_body_page / _apply_body_page)"
  - "Module constants _BULK_THRESHOLD (250) / _BULK_PAGE_SIZE (200)"
  - "Non-blocking 'Loading previews… N/M' streaming indicator (notes fraction)"
  - "by-id get_note path retained ONLY as cache-miss fallback (PERF-03)"
affects:
  - "src/notes_os/screens/sort.py"
  - "tests/screens/test_sort_screen.py"
tech-stack:
  added: []
  patterns:
    - "@work(thread=True) worker + call_from_thread page-merge (mirrors _load_inbox_refs)"
    - "id-keyed cache merge + id-keyed current-note re-render (out-of-order page self-correct)"
    - "range stale-guard (offset <= _index < offset+len) mirroring _apply_note_body"
key-files:
  created: []
  modified:
    - "src/notes_os/screens/sort.py"
    - "tests/screens/test_sort_screen.py"
decisions:
  - "Threshold 250 / page size 200 as locked module-level named constants (no magic numbers)"
  - "Body streaming does NOT set _loading — keystrokes stay live (T-06-07 preserved)"
  - "Retired _prefetch_next entirely; get_note survives only as cache-miss fallback"
metrics:
  duration: "~25m"
  completed: "2026-06-09"
  tasks: 2
  files: 2
---

# Phase 10 Plan 02: Background Bulk Paged Preview Load Summary

Replaced SortScreen's dead per-note prefetch chain with a background `@work(thread=True)`
bulk-load worker that pages note bodies from `get_inbox_note_bodies` into `_note_cache`
(≤250 → one silent call, >250 → pages of 200 first-page-first with a non-blocking
`Loading previews… N/M` indicator), while keeping the by-id `get_note` path solely as the
cache-miss fallback for a note skipped faster than its page loads.

## What Was Built

### Task 1 — Bulk-load worker, page-merge, constants, retire `_prefetch_next` (`src/notes_os/screens/sort.py`)
- Added module-level `_BULK_THRESHOLD: int = 250` and `_BULK_PAGE_SIZE: int = 200` with locked-default docstrings.
- Added streaming-state fields in `__init__`: `_previews_total`, `_previews_loaded`, `_previews_streaming` (distinct from `_loading`, which still gates `on_key` on refs only).
- `_apply_inbox_refs` now calls `_start_bulk_body_load()` after the first render. Sub-threshold inboxes fire one silent `_load_body_page(0, total)` (`_previews_streaming = False`); larger inboxes set `_previews_streaming = True` and kick the first page `_load_body_page(0, _BULK_PAGE_SIZE)`.
- `_load_body_page` (`@work(thread=True)`): calls `get_inbox_note_bodies` inside `try/except Exception` (logs `warning(exc_info=True)` and returns on failure — a bad page never crashes; the by-id fallback covers it), then marshals back via `call_from_thread(self._apply_body_page, notes, offset)`.
- `_apply_body_page` (main thread): merges each note id-keyed into `_note_cache`; increments `_previews_loaded` by `len(notes)`; re-renders the current note **only** when `offset <= _index < offset + len(notes)`, resolving the body id-keyed (`_note_cache.get(current_ref.id)`); chains the next page while streaming, or clears the indicator on completion.
- Added `_render_progress()` helper composing the coexisting `Note X of Y` + `Loading previews… N/M` lines; `_render_current_note` now calls it instead of writing `#progress` directly.
- **Retired `_prefetch_next`**: deleted the method and its call in `_apply_note_body`; kept `_get_or_kick_note` / `_load_note_body` unchanged as the cache-miss fallback.
- Updated both class/module docstrings (removed the "prefetch the NEXT note" bullet, documented the paged bulk load + by-id fallback, noted T-06-07 preservation).

### Task 2 — Pilot tests for the three PERF behaviors (`tests/screens/test_sort_screen.py`)
- Imports `_BULK_THRESHOLD` / `_BULK_PAGE_SIZE` from `notes_os.screens.sort` (no hardcoded 250/200). Added `_make_bulk_notes(count)` factory.
- `test_small_inbox_single_bulk_no_indicator` (PERF-01): 5-note inbox → whole cache warm, `_previews_streaming is False`, first real preview shown, no `Loading previews…`.
- `test_large_inbox_paged_indicator_and_never_blocks` (PERF-02): `_BULK_THRESHOLD + _BULK_PAGE_SIZE + 1` notes; gates the mock's `get_inbox_note_bodies` with a `threading.Event` to release page 0 then hold the rest. Asserts mid-stream indicator (`Loading previews…` + `/M` with M from the imported constant), a skip keystroke honored mid-stream (`skipped == 1`), then post-drain: streaming cleared, full cache populated, indicator gone.
- `test_cold_note_resolves_via_get_note_fallback` (PERF-03): stubs bulk fetch to `[]` so the cache stays empty, spies `get_note`; asserts `get_note("bulk-0")` was called and the real preview resolves via the fallback.

## Hardening (C1/C3/C4) — Confirmed Landed
- **C1**: `_render_current_note` still routes a cache miss through `_get_or_kick_note(ref.id, self._index)` (sort.py:967) — the by-id `get_note` fallback survives the `_prefetch_next` deletion (PERF-03 stays reachable).
- **C3**: `_apply_body_page` resolves the current note id-keyed via `_note_cache.get(current_ref.id)` (sort.py:392), not positionally — an out-of-order page self-corrects (phase's #1 named risk).
- **C4**: the indicator is a notes fraction — `_previews_loaded += len(notes)` (sort.py:385), `M == _previews_total == len(self._refs)`; pages and notes are never mixed.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

All commands run via the real pixi binary (`~/.pixi/bin/pixi`, local shim broken):

| Command | Result |
|---------|--------|
| `pixi run mypy` | exit 0 — "Success: no issues found in 22 source files" |
| `pixi run ruff` | exit 0 — "All checks passed!" |
| `pixi run pytest tests/screens/test_sort_screen.py` | exit 0 — 13 passed (10 existing + 3 new) |
| `pixi run pytest -m 'not integration'` | exit 0 — 374 passed, 6 deselected |
| coverage | TOTAL 92%; `sort.py` 86% (≥80% gate held) |

Acceptance-criteria greps:
- `grep -v '^#' src/notes_os/screens/sort.py | grep -c "_prefetch_next"` → `0`
- `_get_or_kick_note` and `_load_note_body` still present (fallback retained).

## Self-Check: PASSED
- `src/notes_os/screens/sort.py` — FOUND (contains `_BULK_THRESHOLD`, `_load_body_page`, `_apply_body_page`).
- `tests/screens/test_sort_screen.py` — FOUND (imports `_BULK_THRESHOLD`/`_BULK_PAGE_SIZE`, 3 new PERF tests).
- No commits made (per execution constraints — changes left unstaged for the orchestrator).
