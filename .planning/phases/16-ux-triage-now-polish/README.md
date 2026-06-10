# Phase 16 — Triage-now polish  `[UX-TRIAGE-NOW]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** Phase 10

**Goal:** Guarantee nothing on the *action* line ever looks blocked. The category prompt is
live the instant the title shows; only the preview pane may show a placeholder.

**Requirements:** UX-04

**Key changes:**
- `screens/sort.py`: ensure `#prompt` renders the live category prompt on first paint (not
  gated on body load); audit any state where the action line shows a loading/empty string
  while input is actually accepted.

**Note:** Tiny — could fold into Phase 10's PR if you prefer fewer PRs. Kept separate per the
one-feature-one-PR request.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 16.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 7.

**Plan next:** `/gsd-plan-phase 16`
