---
phase: 11-ux-skeleton-preview
plan: 01
subsystem: ui
tags: [textual, tcss, skeleton-loader, sort-screen, ux]

# Dependency graph
requires:
  - phase: 10-background-bulk-preview
    provides: "background paged body load + the single-note get_note cache-miss fallback that renders the pending-preview state"
provides:
  - "Dim, CSS-class-driven skeleton placeholder (_PREVIEW_SKELETON) shown in #note-preview while a note body is not yet cached"
  - "preview-loading CSS class toggled on #note-preview (added on cache-miss, removed on cache-hit) keyed to a dim #note-preview.preview-loading rule in app.tcss"
  - "Pilot coverage proving skeleton+class pre-load and real-preview+class-gone post-load"
affects: [sort-screen, preview-rendering, ux-polish]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CSS-class-driven loading state: render branch toggles a named class (add_class/remove_class) and the dim styling lives entirely in app.tcss, not in Python"
    - "Named-constant placeholder (no magic string) imported directly by the test for a single source of truth"

key-files:
  created: []
  modified:
    - "src/notes_os/screens/sort.py"
    - "src/notes_os/app.tcss"
    - "tests/screens/test_sort_screen.py"

key-decisions:
  - "Skeleton is a multi-line block-glyph (░) string, not animated — pure static dim placeholder; the dim look is CSS ($text-muted + text-style: dim), the Python only toggles the class"
  - "Query #note-preview once into a local, then branch add-class+skeleton (cache-miss) vs remove-class+real-preview (cache-hit) so a loaded note is never left dim"
  - "Kept the distinct plural 'Loading previews… N/M' bulk-stream progress indicator untouched — it is a separate Phase-10 feature with load-bearing existing assertions"

patterns-established:
  - "Loading affordances are class-driven: behavior in the render seam, appearance in app.tcss"

requirements-completed: [UX-01]

# Metrics
duration: 12min
completed: 2026-06-09
---

# Phase 11 Plan 01: UX Skeleton Preview Summary

**Replaced the literal "Loading preview…" text with a dim, CSS-class-driven (`preview-loading`) multi-line skeleton placeholder in `#note-preview`, swapped for the real preview the instant the body lands.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 2 (both TDD, executed together as one pure-UI feature)
- **Files modified:** 3

## Accomplishments
- Added two typed module constants in `sort.py`: `_PREVIEW_SKELETON` (dim multi-line `░` block placeholder) and `_PREVIEW_SKELETON_CLASS = "preview-loading"`, both with no-magic-string docstrings.
- Reworked `_render_current_note` to query `#note-preview` once and branch: cache-miss → `add_class(preview-loading)` + render the skeleton; cache-hit → `remove_class(preview-loading)` + render the real preview (`preview or "(no preview)"`). A loaded note is never left dim.
- Added a `#note-preview.preview-loading { color: $text-muted; text-style: dim; }` rule to `app.tcss`; the base `#note-preview { color: $text; }` rule is unchanged.
- Removed the literal `"Loading preview…"` string from both code and docstrings in `sort.py`; updated the class/method docstrings to describe the skeleton.
- Added a Pilot test `test_skeleton_shown_until_body_lands` proving the skeleton + class show pre-load and are gone (class removed, real preview shown) post-load.

## Files Created/Modified
- `src/notes_os/screens/sort.py` — `_PREVIEW_SKELETON` / `_PREVIEW_SKELETON_CLASS` constants; `_render_current_note` skeleton-vs-real branch with class add/remove; docstring updates removing the old loading literal.
- `src/notes_os/app.tcss` — new `#note-preview.preview-loading` dim rule after the base `#note-preview` rule.
- `tests/screens/test_sort_screen.py` — imported the two new constants; added `test_skeleton_shown_until_body_lands` (gated `get_note` fallback so the skeleton state is deterministically observable, then released to assert the real preview + class removal).

## Verification

All commands run via the absolute pixi binary (`~/.pixi/bin/pixi`) per the broken-shim note.

- `~/.pixi/bin/pixi run ruff` → `All checks passed!`
- `~/.pixi/bin/pixi run mypy` → `Success: no issues found in 22 source files`
- `grep -n "preview-loading" src/notes_os/app.tcss` → rule present (line 78).
- Singular `"Loading preview…"` literal fully removed (code + docstrings): `grep -rnE "Loading preview([^s]|$)" src/notes_os/screens/sort.py` → no matches.
- `~/.pixi/bin/pixi run pytest -m 'not integration' -k "skeleton or sort_screen or bulk or cold_note"` → 23 passed.
- `~/.pixi/bin/pixi run pytest -m 'not integration'` → 402 passed, 6 deselected.
- `~/.pixi/bin/pixi run pytest -m 'not integration' --cov=src/notes_os --cov-fail-under=80` → **91.63% total, gate reached** (`sort.py` 85%).

Confirmed behavior: pre-load (body withheld) `#note-preview.has_class("preview-loading")` is True and its render contains `_PREVIEW_SKELETON` (and NOT "Loading preview"); post-load the class is removed and the render shows the real `"preview 0"` text.

## Decisions Made
- Skeleton kept as a static dim multi-line block-glyph string; appearance is entirely CSS-driven (`$text-muted` + `text-style: dim`) so the Python render path only toggles a class — matches the no-magic-string and separation-of-concerns rules in CLAUDE.md.

## Deviations from Plan

### Interpretation deviation — grep gate scope (no code change required)

**1. [Rule 1 — Spec/verification ambiguity] The plan's `grep -rn "Loading preview" sort.py` "returns nothing" gate is literally unsatisfiable and was applied to the singular literal only.**
- **Found during:** Task 1 verification.
- **Issue:** The plan's verification (`test -z "$(grep -rn 'Loading preview' src/notes_os/screens/sort.py)"`) substring-matches the *plural* `"Loading previews… N/M"` bulk-stream progress indicator — a distinct, legitimate Phase-10 feature whose string is load-bearing for existing tests (`test_large_inbox_paged_indicator_and_never_blocks` asserts `"Loading previews" in progress`). Removing it would break those tests. The plan's stated intent (lines 79/114/142) targets only the *singular* `"Loading preview…"` placeholder.
- **Fix:** Removed the singular `"Loading preview…"` literal entirely from code and docstrings (the actual UX-01 goal), and left the plural `"Loading previews…"` indicator intact. Verified the singular is gone via a negative-lookahead grep: `grep -rnE "Loading preview([^s]|$)" sort.py` → no matches.
- **Files modified:** `src/notes_os/screens/sort.py` (no extra change beyond the planned edits).
- **Verification:** Singular-literal grep clean; all Phase-10 `"Loading previews"`/`"Loading preview" not in` assertions still pass (402 passed).

---

**Total deviations:** 1 (verification-scope interpretation; no scope creep, no extra code).
**Impact on plan:** None functional — the UX-01 goal is fully met. The only adjustment is reading the grep gate as the singular placeholder, which the plan's own intent requires.

## Issues Encountered
- The `pixi run pytest` task does not wire `--cov`/`--cov-fail-under` into addopts (coverage is a CI-level gate). Ran coverage explicitly to confirm the ≥80% floor: 91.63% total. `sort.py` sits at 85% (the project's enforced overall gate is 80%); the new skeleton render branches are covered by the new test.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- UX-01 complete; the pending-preview now reads as "coming," not "stuck." No bridge/router/write-path changes — the seam is purely presentational and isolated to `_render_current_note` + one CSS rule.
- Per the worktree's parallel-safe protocol, no commit was made and no root STATE/ROADMAP/REQUIREMENTS files were touched; the orchestrator owns commits and state updates.

---
*Phase: 11-ux-skeleton-preview*
*Completed: 2026-06-09*
