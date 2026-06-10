---
phase: 16-ux-triage-now-polish
plan: 01
subsystem: tui-sort-screen
tags: [ux-04, regression-guard, pilot-test, action-line]
requires:
  - "SortScreen._render_current_note unconditional #prompt AWAIT_CATEGORY render"
  - "on_key guarded only by _loading (never by body load)"
  - "_note_for_move() minimal-Note-from-ref fallback (move before body lands)"
provides:
  - "Regression guard locking UX-04: action line live + category move honored while body streams"
  - "UX-04 invariant comment guarding the unconditional #prompt render against future regression"
affects:
  - src/notes_os/screens/sort.py
  - tests/screens/test_sort_screen.py
tech-stack:
  added: []
  patterns:
    - "Cache-miss + gated get_note threading.Event pattern to observe the body-streaming window deterministically (mirrors test_skeleton_shown_until_body_lands)"
    - "Pilot keystroke honored mid-stream: press('x') asserts summary().moved == 1 with skeleton still on #note-preview"
key-files:
  created: []
  modified:
    - src/notes_os/screens/sort.py
    - tests/screens/test_sort_screen.py
decisions:
  - "No production behavior change — AUDIT confirmed no gap. UX-04 was already satisfied; this phase only adds the Pilot regression guard plus a one-line invariant comment."
  - "Reused the default all-leaf ParaStructure (archive 'x' route auto-years to Archive) rather than a custom structure — no helper needed."
metrics:
  duration: "~6 min"
  completed: 2026-06-09
  tasks: 1
  files: 2
---

# Phase 16 Plan 01: Action-Line-Live Regression Guard (UX-04) Summary

One Pilot test (`test_category_prompt_live_while_body_streams`) locks UX-04 — the
triage action line (`#prompt`) shows the live category prompt and honors a category
move (`x`) the instant the note title paints, while the body is still streaming and
the Phase-11 skeleton sits on `#note-preview` — plus a one-line UX-04 invariant
comment guarding the unconditional `#prompt` render. No production behavior change.

## What Was Built

- **Test (`tests/screens/test_sort_screen.py`):** Added
  `test_category_prompt_live_while_body_streams`. Builds a one-archive-note inbox,
  stubs `get_inbox_note_bodies` → `[]` (bulk page never lands) and gates the by-id
  `get_note` fallback on an un-set `threading.Event` so the body-streaming window is
  observable. WITHOUT draining workers it asserts: `#note-preview` carries
  `_PREVIEW_SKELETON_CLASS` (body not loaded), `#prompt` render contains
  `_CATEGORY_PROMPT` (live action line, imported — not hardcoded), and
  `_router_state is RouterState.AWAIT_CATEGORY`. Then `await pilot.press("x")` and
  asserts `screen._session.summary().moved == 1` — the category move was honored
  mid-stream. Releases the gate and drains for clean teardown.
- **Import block:** Added `_CATEGORY_PROMPT` to the
  `from notes_os.screens.sort import (...)` block (no hardcoded prompt string).
- **Production (comment only — NO behavior change):** Added a UX-04 invariant comment
  in `_render_current_note` immediately above the `if self._router_state ==
  RouterState.AWAIT_CATEGORY:` `#prompt` render, stating the prompt MUST render
  unconditionally (outside the `_current_note` body-cache branch) so the action line
  is never gated on body load.

## How It Satisfies the Plan

- (UX-04, success criterion 1) `test_category_prompt_live_while_body_streams` proves
  the live prompt with the skeleton on `#note-preview` AND that a category keystroke
  is honored (`summary().moved == 1`).
- (success criterion 2) The only empty-`#prompt` window remains `_loading` (refs not
  fetched), where `on_key` early-returns — unchanged.
- T-16-01 (mitigate): the new test fails if the `#prompt` render is ever moved under
  the body-cache branch; the `UX-04` comment documents the invariant.

## Deviations from Plan

None — plan executed exactly as written. (The plan's optional second
skip-assertion path was not added; the primary move-honored assertion fully covers
the acceptance criteria.)

## Verification

All commands run via the absolute pixi paths (local shim is broken):

| Command | Result |
|---------|--------|
| `~/.pixi/bin/pixi run mypy` | `Success: no issues found in 22 source files` |
| `~/.pixi/bin/pixi run ruff` (= `ruff check src tests`) | `All checks passed!` |
| `.pixi/envs/default/bin/ruff format --check src tests` | `48 files already formatted` |
| `~/.pixi/bin/pixi run pytest tests/screens/test_sort_screen.py -q` | `23 passed` |
| `~/.pixi/bin/pixi run pytest tests/screens/test_sort_screen.py::test_category_prompt_live_while_body_streams -q` | `1 passed` |
| `~/.pixi/bin/pixi run pytest -m 'not integration'` | `403 passed, 6 deselected` (>=80% gate held) |
| `grep -n "UX-04" src/notes_os/screens/sort.py` | non-empty (lines 1206, 1210) |

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: src/notes_os/screens/sort.py (UX-04 comment at line 1206)
- FOUND: tests/screens/test_sort_screen.py (test_category_prompt_live_while_body_streams)
- Note: per orchestrator instructions, changes are left UNSTAGED — the orchestrator
  commits. No per-task commit hashes recorded.
