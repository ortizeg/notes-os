# Phase 14 — Undo last action (`U`)  `[UX-UNDO]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** Phase 10, Phase 13

**Goal:** Reverse the last skip or move. Confidence → speed: users stop second-guessing and
fly through the inbox.

**Requirements:** UX-02

**Key changes:**
- `sorter/session.py`: undo stack of `(note_id, prev_state, outcome, source_path?)`.
- `sorter/notes.py`: capture the source `FolderPath` at move time so a move-back targets the
  true origin (note may have come from a subfolder of inbox).
- `screens/sort.py`: bind `U`; move-back reuses Phase 13's off-thread write plumbing; step
  `_index` back; correct counts. `U` is **repeatable** — each press pops one more action,
  unbounded within the session (LIFO to session start). Edge cases: empty stack (no-op +
  hint), undo of a skip (no write), undo after finish.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 14.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 5.

**Plan next:** `/gsd-plan-phase 14`
