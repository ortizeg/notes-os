# NotesOS

## What This Is

NotesOS is a local-first, AI-augmented CLI/TUI for managing, distilling, and connecting knowledge in Apple Notes using Tiago Forte's PARA methodology and CODE framework (Capture → Organize → Distill → Express). It is keyboard-driven, runs entirely on the user's Mac, and keeps the human in the loop for every decision. Built as a monorepo (`notes-os/`) from day one, it grows across four milestones without restructuring.

**This project's active milestone is M1 — the PARA Notes Sorter** (the Organize step). M2–M4 are captured in the vision below and will be planned as subsequent milestones.

## Core Value

A person can triage their Apple Notes inbox into a PARA-structured folder hierarchy with single keystrokes — fast, mouse-free, and non-destructive (notes are moved, never deleted), with their Notes database safely backed up before any write.

## Requirements

### Validated

(None yet — ship to validate)

### Active

<!-- M1 scope: PARA Notes Sorter. These are hypotheses until shipped. -->

- [ ] Repo scaffold: monorepo, pixi env, pyproject (Hatchling + hatch-vcs), `notes` TUI entry point, stub modules for M2–M4, CI workflows, pre-commit
- [ ] AppleScript bridge (`notes.py`): read inbox notes, discover PARA structure, move note, ensure folder — behind `NotesRepositoryProtocol`
- [ ] Notes database backup (`backup.py`): auto-backup before every write, list/restore/prune, 10-backup retention — built immediately after the bridge is validated
- [ ] Pydantic V2 config (`config.py`): frozen models, TOML loader from `~/.notes-os/config.toml`, sensible defaults
- [ ] PARA routing state machine (`router.py`): SHOW_NOTE → AWAIT_CATEGORY → AWAIT_FOLDER → AWAIT_SUBFOLDER → CONFIRM_MOVE, with Archive auto-year and `[B]` back
- [ ] Terminal UI (`ui.py`): note title + Markdown-rendered preview (HTML-stripped, 250 chars), single-keystroke category input, numbered list selection (Enter-confirmed)
- [ ] Session tracking (`session.py`): moved/skipped/error counts, end-of-session summary, log to `~/.notes-os/logs/`
- [ ] Heuristic task extraction (`extractor.py`, M1.5): regex/NLP scan for action items, off by default, writes Markdown checkboxes to `~/.notes-os/extracted-tasks/`
- [ ] Textual TUI app (`app.py` + screens/widgets): HomeScreen splash + menu, SortScreen, TaskExtractScreen, wired end-to-end via `notes` command

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
| HTML stripping via stdlib `html.parser` | No BeautifulSoup dependency needed | — Pending |
| GSD roadmap scoped to M1; M2 via `/gsd:new-milestone` | One shippable unit per milestone; cleanest GSD fit | — Pending |

---
*Last updated: 2026-06-07 after initialization*
