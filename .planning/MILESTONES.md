# Milestones — NotesOS

Historical index of shipped milestones. Full artifacts under `.planning/milestones/`.

| Version | Name | CODE step | Shipped | Phases | Plans | Notes |
|---------|------|-----------|---------|--------|-------|-------|
| **v1.0** | PARA Notes Sorter | Organize | 2026-06-08 | 6 | 19 | Keyboard PARA triage of Apple Notes inbox; backup-before-write; heuristic task extraction; Textual TUI. ~356 tests / ~92% cov. Validated against real Notes (8 UAT fixes). PRs #1–#6. |

## v1.0 — PARA Notes Sorter ✓

**Goal delivered:** triage your Apple Notes inbox into a PARA folder hierarchy with single keystrokes — fast, mouse-free, non-destructive, with the Notes DB backed up before every write.

- Archive: [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md) · [`milestones/v1.0-REQUIREMENTS.md`](milestones/v1.0-REQUIREMENTS.md)
- Phases: Scaffold → AppleScript Bridge → Backup → Sorting Core → Task Extraction → Textual TUI
- macOS prerequisites (runtime): terminal needs **Automation → Notes** + **Full Disk Access** (TCC).

---

**Next:** v2.0 — Distillation Engine (Distill). Start with `/gsd-new-milestone`.
