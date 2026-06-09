# Phase 15 — Session resume  `[UX-RESUME]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** Phase 10, Phase 13

**Goal:** Quit at note 80 of 200, pick up there next launch. Speeds repeat sessions.

**Requirements:** UX-03

**Key changes:**
- Persist lightweight progress (inbox folder, last note id, counts) to
  `~/.notes-os/session-state.json` on advance/quit.
- On SortScreen mount, if saved position matches current refs **by note id**, offer
  "Resume at N / Start over" (single-select modal); resume sets `_index`.
- Detect a materially changed inbox (ids no longer match) → safe fallback to start-over.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 15.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 6.

## Plans (2 plans · 2 waves)

- [ ] `15-01-PLAN.md` (wave 1) — UI-agnostic persistence: frozen `SessionState` +
  `ResumeStore` (atomic save, None-safe load, clear), `SortSession.restore_counts`,
  `ResumePromptModal`. Unit-tested without Textual.
- [ ] `15-02-PLAN.md` (wave 2, depends on 15-01) — SortScreen wiring: `ResumeStore` DI seam,
  save points (advance + leave-mid-session), on-mount always-ask resume decision, clear on
  finish/start-over. Pilot-tested.

**Execute next:** `/gsd-execute-phase 15`
