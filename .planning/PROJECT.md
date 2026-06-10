# NotesOS

## What This Is

NotesOS is a local-first, AI-augmented CLI/TUI for managing, distilling, and connecting knowledge in Apple Notes using Tiago Forte's PARA methodology and CODE framework (Capture → Organize → Distill → Express). It is keyboard-driven, runs entirely on the user's Mac, and keeps the human in the loop for every decision. Built as a monorepo (`notes-os/`) from day one, it grows across four milestones without restructuring.

**Milestone 1 — the PARA Notes Sorter (Organize) — is COMPLETE** (shipped via PRs #1–#6, validated against real Apple Notes on 2026-06-08). M2–M4 are captured in the vision below; next up is M2 (Distillation Engine).

> **Runtime prerequisites (macOS, discovered during UAT):** the terminal needs **two** TCC grants — *Automation → Notes* (AppleScript control) AND *Full Disk Access* (to back up `NoteStore.sqlite` before writes). Both are required for the sort flow; without Full Disk Access every move aborts on a backup `PermissionError` by design.

## Core Value

A person can triage their Apple Notes inbox into a PARA-structured folder hierarchy with single keystrokes — fast, mouse-free, and non-destructive (notes are moved, never deleted), with their Notes database safely backed up before any write.

## Current State

**Shipped: v1.0 — PARA Notes Sorter** (2026-06-08). The `notes` Textual TUI triages your
Apple Notes inbox into PARA folders by keystroke, backs up the Notes DB before every write,
and optionally extracts tasks. 6 phases, 19 plans, ~356 tests / ~92% coverage; archived under
`.planning/milestones/v1.0-*` and indexed in `.planning/MILESTONES.md`.

**Next milestone goals — v2.0 (Distillation Engine, the Distill step):** progressive
summarization with a 3-tier LLM backend (Apple Foundation Models → Ollama → Claude,
`backend="auto"`), a folder chat agent, and per-folder root-note generation written back to
Notes. Reuses the M1 bridge + backup + config. Start with `/gsd-new-milestone`.

## Requirements

### Validated

<!-- M1 — PARA Notes Sorter. Shipped (PRs #1–#6) and validated end-to-end against
     real Apple Notes on 2026-06-08. 44 v1 requirements, ~356 tests, ~92% coverage. -->

- ✓ Repo scaffold: monorepo, pixi env, pyproject (Hatchling + hatch-vcs), `notes` TUI entry point, M2–M4 stubs, CI, pre-commit — M1/SCAF
- ✓ AppleScript bridge (`notes.py`): inbox read, PARA discovery, move, ensure_folder, lazy `get_note`/`get_inbox_note_refs`, behind `NotesRepositoryProtocol` — M1/BRDG
- ✓ Notes DB backup (`backup.py`): auto-backup-before-write, list/restore/prune, 10-backup retention; idempotent-per-second `create()` — M1/BKUP
- ✓ Pydantic V2 config (`config.py`): frozen `SorterConfig` composing Bridge/Backup, TOML loader, clear errors — M1/CONF
- ✓ PARA routing state machine (`router.py`): UI-agnostic, archive auto-year, `[B]` back — M1/ROUT
- ✓ Terminal UI + Textual screens: note preview, arrow-highlight + Enter folder selection, `?` help, inbox count — M1/UI, TUI
- ✓ Session tracking (`session.py`): moved/skipped/error counts, summary, log to `~/.notes-os/logs/` — M1/SESS
- ✓ Heuristic task extraction (`extractor.py`): off by default, Markdown checkboxes to `~/.notes-os/extracted-tasks/` — M1/TASK
- ✓ Textual TUI app: HomeScreen + SortScreen + TaskExtractScreen wired end-to-end via `notes` — M1/TUI

### Active

(M1 complete. Next: **M2 — Distillation Engine** via `/gsd-new-milestone`.)

### Out of Scope

<!-- M1 v1 exclusions, with reasoning. -->

- Creating new PARA root folders — discovered dynamically; v1 only routes into existing structure
- Bulk/batch moves without review — defeats the human-in-the-loop triage model
- Undo functionality post-move — backup/restore covers recovery instead
- iCloud sync-status awareness — out of v1 control surface
- iOS/iPadOS notes — macOS AppleScript only
- GUI / non-terminal interface — keyboard-driven TUI is the product
- AI-assisted auto-categorization — deferred to M4 (Smart Suggestions); v1 task extraction is heuristic only
- LLM distillation, knowledge graph, smart suggestions — M2/M3/M4, separate milestones

## Context

**Full four-milestone vision (CODE framework):**

| Milestone | CODE step | What it adds |
|---|---|---|
| **M1 — PARA Sorter** (active) | Organize | Keyboard triage of inbox → PARA folders; backup; AppleScript bridge; heuristic task extraction |
| M2 — Distillation Engine | Distill | Progressive summarization; 3-tier LLM backend (Apple FM → Ollama → Claude); folder chat agent; root-note generation written back to Notes |
| M3 — Knowledge Graph | Express | SQLite graph of entities/concepts/relationships; GraphRAG retrieval; local embeddings |
| M4 — Smart Suggestions | — | Graph-driven routing assists during triage; related-note surfacing; distillation-candidate flagging |

**Technical environment:**
- Monorepo `notes-os/`, src layout (`src/notes_os/`), stub `__init__.py` for M2–M4 at init so package structure is stable
- AppleScript is macOS-exclusive → CI matrix is macOS-latest only (ubuntu runners would fail); Python 3.11 + 3.12
- Apple Notes body is HTML → strip with stdlib `html.parser`, no BeautifulSoup
- `memo` (github.com/antoniorodr/memo) is a **reference, not a dependency** — read its source before writing the AppleScript bridge to shortcut discovery; do not import it
- Apple Notes DB at `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite` (+ `-wal`, `-shm`) — all three must be backed up together

**Known risks to address:**
- Programmatic writes to Apple Notes have no built-in undo → backup-before-write is mandatory, non-negotiable default
- AppleScript failures must surface as warnings, never crash the session
- Write-path modules (`notes.py`, `backup.py`) carry data-loss risk → 95% coverage floor

## Constraints

- **Tech stack**: Python 3.11+, Textual ≥0.80 (TUI, replaces Typer), Rich ≥13 (Markdown/preview rendering), readchar ≥4 (single-keystroke capture), Pydantic V2 (config) — Stdlib for `subprocess`, `html.parser`, `tomllib`, `logging`, `pathlib`, `datetime`. No other runtime deps in M1.
- **Platform**: macOS only — AppleScript bridge via `osascript`; Apple Notes app required
- **Coding standards**: Expert Coder Agent + Code Quality skills — Pydantic V2 frozen models, mypy strict, Ruff full ruleset (`E,F,I,N,UP,S,B,A,C4,T20,SIM,TCH,RUF,PTH,ERA`), `from __future__ import annotations` in every file, DI, Protocol interfaces, Google-style docstrings, zero `print()` (logging only), no global state/magic numbers
- **Testing**: write-path modules (`notes.py`, `backup.py`, `router.py`) 95% floor; others 80%; overall CI gate `--cov-fail-under=80`. Unit tests mock all external I/O. Integration tests `@pytest.mark.integration`, macOS-only, use dedicated `_TestInbox` — never touch real notes. `MockNotesRepository` in `conftest.py`
- **CI/CD**: GitHub Actions, three-job tiered (lint / typecheck / test), macOS-latest × Python 3.11 & 3.12
- **Repo**: branch protection on `main`, squash merge, delete-on-merge, CODEOWNERS, PR + issue templates; never commit directly to `main`; one PR per feature
- **Git workflow**: small atomic commits, `type(scope): description` format (`feat`/`fix`/`test`/`refactor`/`docs`/`chore`); feature branches `feat/short-description`
- **Performance**: sort 20 notes in under 5 minutes, no mouse; backup completes <1s (SQLite file copy)

## Key Decisions

<!-- Pre-resolved in the PRDs; locked for M1. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Monorepo from day one, src layout, M2–M4 stubbed | Future milestones add modules without repo restructuring | — Pending |
| Textual TUI replaces Typer subcommands | Single `notes` entry point; all navigation in-app; Rich components slot in natively | — Pending |
| Inbox folder = `"Notes"` (Apple default) | Apple's default capture folder | — Pending |
| Archive routing = `Archive/{current-year}`, auto-created | Zero-prompt archival, year-bucketed | — Pending |
| Numbered list selections require Enter (Option A) | Lists grow over time; consistent muscle memory, no ambiguity. Single-keypress only for top-level PARA category | — Pending |
| `backup.py` built immediately after AppleScript bridge validated | Write-path safety before any move operation | — Pending |
| Task extraction off by default, heuristic-only in M1 | Avoid LLM dependency in M1; opt-in via config | — Pending |
| `memo` is reference only, not a dependency | Interactive-first, no batch Python API; use for discovery shortcut | — Pending |
| HTML stripping via stdlib `html.parser` | No BeautifulSoup dependency needed | ✓ Good |
| TUI does AppleScript/backup I/O in Textual thread workers | Blocking osascript on the event loop froze the app before first paint | ✓ Good (UAT fix) |
| Lazy per-note body load + prefetch in SortScreen | Eager full-body fetch of a large inbox was unusably slow | ✓ Good (UAT fix) |
| Arrow-highlight + Enter folder selection (supersedes single-key) | Single-key acted on the first digit → folders 10+ unreachable, mis-moves | ✓ Good (UAT fix) |
| `markup=False` on text Statics; normalize Enter off `event.key` | Textual ate `[P]` shortcuts; Enter arrived as `\r` not `enter` | ✓ Good (UAT fix) |
| 30s osascript timeout; idempotent-per-second `backup.create()` | Hung Apple Event froze quit; two same-second backups collided (ENOTEMPTY) | ✓ Good (UAT fix) |
| GSD roadmap scoped to M1; M2 via `/gsd:new-milestone` | One shippable unit per milestone; cleanest GSD fit | — Pending |

---
*Last updated: 2026-06-08 — Milestone 1 complete & validated against real Apple Notes (8 UAT fixes folded in)*
