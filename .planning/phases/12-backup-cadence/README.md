# Phase 12 — Backup once-per-session  `[BKUP-CADENCE]`

**Milestone:** v3.0 Speed & Triage UX · **PR:** one · **Depends on:** —

**Goal:** Capture a restore point before the *first* write of a session instead of before
every write (~100× less churn on a 92 MB `NoteStore.sqlite`). Write-path module → **95%
coverage floor**.

**Requirements:** BKUP-07, BKUP-08

**Key changes:**
- `backup.py` `BackingUpNotesRepository`: per-session "already backed up" latch; first-write
  backup failure still aborts that write (BKUP-06 preserved).
- `config`: `backup_cadence: "session" | "write"` (default `"session"`).
- Threat-model notes (T-04-09 / T-06-04) updated in `backup.py` and CLAUDE.md.

**Success criteria:** see `.planning/milestones/v3.0-speed-triage-ux-ROADMAP.md` › Phase 12.
**Design:** `.planning/SPEC-speed-and-triage-ux.md` › Phase 3.

**Plan next:** `/gsd-plan-phase 12`
