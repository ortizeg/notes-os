# Phase 12 — Backup once-per-session  `[BKUP-CADENCE]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** —

**Goal:** Capture a restore point before the *first* write of a session instead of before
every write (~100× less churn on a 92 MB `NoteStore.sqlite`). Write-path module → **95%
coverage floor**.

**Requirements:** BKUP-07, BKUP-08

**Key changes:**
- `backup.py` `BackingUpNotesRepository`: per-session "already backed up" latch; first-write
  backup failure still aborts that write (BKUP-06 preserved).
- Remove the before-every-write path entirely — per-session is the sole cadence (no
  `backup_cadence` config hatch; decided 2026-06-08).
- Threat-model notes (T-04-09 / T-06-04) updated in `backup.py` and CLAUDE.md.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 12.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 3.

**Plans:** 1 plan, 1 wave (autonomous)
- [ ] `12-01-PLAN.md` — per-session backup latch + `begin_session` seam, threat-model doc reword (BKUP-07, BKUP-08)

**Execute next:** `/gsd-execute-phase 12`
