# Phase 13 — Optimistic moves  `[PERF-MOVE]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** Phase 12

**Goal:** Make a move feel as instant as a skip — show `moved ✓`, advance immediately, run
backup+move on a worker thread behind the user. Write-path → **95% coverage floor**.

**Requirements:** PERF-04, PERF-05

**Key changes:**
- `screens/sort.py` `_handle_move`: render confirmation + `_advance()` synchronously;
  dispatch `router.handle_*` → `ensure_folder`/`move_note` (+ first-write backup) to a
  `@work(thread=True)` worker. Capture id/folder_path before dispatch (no advance/worker race).
- On worker failure: non-blocking `notify`, record error, retain note (T-06-05 preserved).
  One in-flight write worker (serialize) to avoid ordering hazards.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 13.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 4.

**Plan next:** `/gsd-plan-phase 13`
