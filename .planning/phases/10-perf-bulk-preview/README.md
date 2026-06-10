# Phase 10 — Bulk paged preview load  `[PERF-BULK]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** —

**Goal:** Kill skip-lag. Replace per-note by-id preview loading (measured 0.80 s/note,
with a prefetch chain that dies after one look-ahead) with a background bulk load
aligned to the inbox refs (measured ~0.35 s for 107 notes).

**Requirements:** PERF-01, PERF-02, PERF-03

**Key changes:**
- `sorter/notes.py`: add `get_inbox_note_bodies(offset, count)` to the protocol + AppleScript
  impl (range read in folder order, id-aligned to `get_inbox_note_refs`); pass-through in
  `BackingUpNotesRepository`.
- `screens/sort.py`: background bulk-load worker (≤250 → single page, no indicator; >250 →
  pages of 200, first page first, non-blocking `Loading previews… N/M`); merge pages into
  `_note_cache`; retire the broken `_prefetch_next` chain; keep by-id `get_note` as
  cache-miss fallback only.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 10.
**Design + measured baselines:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 1.

**Plan next:** `/gsd-plan-phase 10`
