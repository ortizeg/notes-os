# Phase 11 — Skeleton preview  `[UX-SKELETON]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** Phase 10

**Goal:** A pending preview reads as "coming," not "stuck." Replace the literal
"Loading preview…" string with a dim skeleton/shimmer placeholder.

**Requirements:** UX-01

**Key changes:**
- `screens/sort.py` `_render_current_note`: render a muted multi-line placeholder when the
  body isn't cached; swap to the real preview on load.
- `app.tcss`: skeleton styling. Pure UI — no bridge change.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 11.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 2.

**Plans:** 1 plan (wave 1)
- [ ] 11-01-PLAN.md — Dim skeleton placeholder for pending previews (UX-01): `_PREVIEW_SKELETON`
  constant + `preview-loading` CSS class, class-driven dim style, Pilot test for skeleton-then-real.

**Execute next:** `/gsd-execute-phase 11`
