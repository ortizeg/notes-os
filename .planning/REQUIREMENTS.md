# Requirements: NotesOS — Milestone 1 (PARA Notes Sorter)

**Defined:** 2026-06-07
**Core Value:** A person can triage their Apple Notes inbox into a PARA-structured folder hierarchy with single keystrokes — fast, mouse-free, and non-destructive — with their Notes database safely backed up before any write.

## v1 Requirements

Requirements for Milestone 1. Each maps to exactly one roadmap phase.

### Scaffold & Infrastructure

- [x] **SCAF-01**: Monorepo initialized with src layout (`src/notes_os/`), pixi environment, and pyproject.toml (Hatchling + hatch-vcs) exposing the `notes` entry point
- [x] **SCAF-02**: Stub `__init__.py` modules exist for `distiller/`, `graph/`, `suggestions/` (M2–M4) so package structure is stable
- [x] **SCAF-03**: CI runs three tiered jobs (lint, typecheck, test) on macOS-latest × Python 3.11 and 3.12
- [x] **SCAF-04**: Pre-commit hooks enforce ruff, ruff-format, mypy strict, and file hygiene on commit
- [x] **SCAF-05**: Repo configured with branch protection on `main`, squash-merge, CODEOWNERS, and PR/issue templates

### AppleScript Bridge

- [x] **BRDG-01**: System reads all notes (id, title, HTML body) from the configured inbox folder
- [x] **BRDG-02**: System discovers the full PARA folder structure (roots + subfolders) dynamically at runtime
- [x] **BRDG-03**: System moves a note by ID to a resolved folder path
- [x] **BRDG-04**: System creates a folder when it does not exist (idempotent `ensure_folder`)
- [x] **BRDG-05**: Note HTML body is stripped to plain text (stdlib only) and truncated to the configured preview length
- [x] **BRDG-06**: AppleScript failures raise typed errors (`NotesError`, `FolderNotFoundError`, `NotesMoveError`) and surface as warnings without crashing the session
- [x] **BRDG-07**: All bridge operations sit behind `NotesRepositoryProtocol` so the UI and router never call AppleScript directly

### Backup

- [ ] **BKUP-01**: System auto-backs-up the Notes database (sqlite + wal + shm) before every write operation by default
- [ ] **BKUP-02**: User can create a timestamped, labelled backup on demand
- [ ] **BKUP-03**: User can list existing backups
- [ ] **BKUP-04**: User can restore from a specific backup or the latest backup
- [ ] **BKUP-05**: User can prune old backups; default retention is 10 most recent
- [ ] **BKUP-06**: A failed backup aborts the pending write and raises `BackupError`

### Configuration

- [x] **CONF-01**: Config loads from `~/.notes-os/config.toml` when present and falls back to defaults otherwise
- [x] **CONF-02**: Config uses frozen Pydantic V2 models with validated fields (PARA folder names, inbox folder, preview length, archive, backup settings)

### PARA Routing

- [ ] **ROUT-01**: User selects a top-level PARA category with a single keystroke (`P`/`A`/`R`/`X`/`S`/`?`), case-insensitive
- [ ] **ROUT-02**: Archive routing (`X`) auto-resolves to the current-year subfolder, creating it if missing, with no further prompts
- [ ] **ROUT-03**: Selecting Project/Area/Resource displays a numbered list of top-level folders
- [ ] **ROUT-04**: User selects a folder by number + Enter
- [ ] **ROUT-05**: Folders with subfolders prompt for subfolder selection (General listed first); folders without subfolders move immediately
- [ ] **ROUT-06**: User can back out exactly one level with `[B]` at any selection state
- [ ] **ROUT-07**: Skip (`S`) leaves the note in the inbox and advances; invalid input re-prompts with state unchanged
- [ ] **ROUT-08**: Move confirmation shows the resolved PARA path (e.g. `Projects › Website Redesign › Research`)

### Terminal UI

- [ ] **UI-01**: Each note displays its title and a Markdown-rendered preview (HTML-stripped, configurable length) suitable for Warp
- [ ] **UI-02**: Single-keystroke category input is captured without Enter
- [ ] **UI-03**: Help (`?`) shows an inline PARA quick-reference without leaving the flow
- [ ] **UI-04**: Session start shows the inbox note count

### Session Tracking

- [ ] **SESS-01**: Session tracks moved, skipped, and error counts during triage
- [ ] **SESS-02**: Session end displays a summary of counts
- [ ] **SESS-03**: Session log is written to `~/.notes-os/logs/YYYY-MM-DD_HHMMSS.log`

### Task Extraction (M1.5)

- [ ] **TASK-01**: After routing a note, a heuristic scan surfaces action items, named commitments, and inline dates (when enabled)
- [ ] **TASK-02**: User can add all, select a subset, or skip the extracted tasks
- [ ] **TASK-03**: Tasks are written as Markdown checkboxes to `~/.notes-os/extracted-tasks/YYYY-MM-DD.md`
- [ ] **TASK-04**: Feature is off by default and enabled via `[features] task_extraction = true`

### Textual TUI Application

- [ ] **TUI-01**: The `notes` command launches the full Textual TUI application (no subcommands)
- [ ] **TUI-02**: HomeScreen shows the splash + main menu with live status indicators (inbox count, active backend, last backup)
- [ ] **TUI-03**: SortScreen runs the inbox triage flow end-to-end
- [ ] **TUI-04**: TaskExtractScreen reviews extracted tasks after each note when extraction is enabled
- [ ] **TUI-05**: Navigation conventions are consistent across screens (`↑↓` move, `Enter` select, `Esc`/`B` back, `Q` quit, `?` help)

## v2 Requirements

Deferred — acknowledged but not in the M1 roadmap.

### Task Extraction (LLM + export)

- **TASK-V2-01**: LLM-based task extraction using the distiller backend (requires M2)
- **TASK-V2-02**: Task export to other formats (`reminders`, `omnifocus`, `things`)

## Out of Scope

Explicitly excluded from M1. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Creating new PARA root folders | Roots discovered dynamically; v1 only routes into existing structure |
| Bulk / batch moves without review | Defeats the human-in-the-loop triage model |
| Undo functionality post-move | Backup/restore covers recovery instead |
| iCloud sync-status awareness | Out of v1 control surface |
| iOS / iPadOS notes | macOS AppleScript only |
| GUI / non-terminal interface | Keyboard-driven TUI is the product |
| AI-assisted auto-categorization | Deferred to M4 (Smart Suggestions); M1 task extraction is heuristic only |
| Note distillation / knowledge graph | M2 / M3 — separate milestones |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
| --- | --- | --- |
| SCAF-01 | Phase 1 — Scaffold | Complete |
| SCAF-02 | Phase 1 — Scaffold | Complete |
| SCAF-03 | Phase 1 — Scaffold | Pending |
| SCAF-04 | Phase 1 — Scaffold | Pending |
| SCAF-05 | Phase 1 — Scaffold | Complete |
| BRDG-01 | Phase 2 — AppleScript Bridge | Complete |
| BRDG-02 | Phase 2 — AppleScript Bridge | Complete |
| BRDG-03 | Phase 2 — AppleScript Bridge | Complete |
| BRDG-04 | Phase 2 — AppleScript Bridge | Complete |
| BRDG-05 | Phase 2 — AppleScript Bridge | Complete |
| BRDG-06 | Phase 2 — AppleScript Bridge | Complete |
| BRDG-07 | Phase 2 — AppleScript Bridge | Complete |
| BKUP-01 | Phase 3 — Backup | Pending |
| BKUP-02 | Phase 3 — Backup | Pending |
| BKUP-03 | Phase 3 — Backup | Pending |
| BKUP-04 | Phase 3 — Backup | Pending |
| BKUP-05 | Phase 3 — Backup | Pending |
| BKUP-06 | Phase 3 — Backup | Pending |
| CONF-01 | Phase 4 — Sorting Core | Complete |
| CONF-02 | Phase 4 — Sorting Core | Complete |
| ROUT-01 | Phase 4 — Sorting Core | Pending |
| ROUT-02 | Phase 4 — Sorting Core | Pending |
| ROUT-03 | Phase 4 — Sorting Core | Pending |
| ROUT-04 | Phase 4 — Sorting Core | Pending |
| ROUT-05 | Phase 4 — Sorting Core | Pending |
| ROUT-06 | Phase 4 — Sorting Core | Pending |
| ROUT-07 | Phase 4 — Sorting Core | Pending |
| ROUT-08 | Phase 4 — Sorting Core | Pending |
| UI-01 | Phase 4 — Sorting Core | Pending |
| UI-02 | Phase 4 — Sorting Core | Pending |
| UI-03 | Phase 4 — Sorting Core | Pending |
| UI-04 | Phase 4 — Sorting Core | Pending |
| SESS-01 | Phase 4 — Sorting Core | Pending |
| SESS-02 | Phase 4 — Sorting Core | Pending |
| SESS-03 | Phase 4 — Sorting Core | Pending |
| TASK-01 | Phase 5 — Task Extraction | Pending |
| TASK-02 | Phase 5 — Task Extraction | Pending |
| TASK-03 | Phase 5 — Task Extraction | Pending |
| TASK-04 | Phase 5 — Task Extraction | Pending |
| TUI-01 | Phase 6 — Textual TUI Integration | Pending |
| TUI-02 | Phase 6 — Textual TUI Integration | Pending |
| TUI-03 | Phase 6 — Textual TUI Integration | Pending |
| TUI-04 | Phase 6 — Textual TUI Integration | Pending |
| TUI-05 | Phase 6 — Textual TUI Integration | Pending |

**Coverage:**

- v1 requirements: 44 total (note: earlier count of 37 was an undercount; 44 enumerated requirements confirmed)
- Mapped to phases: 44
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-07*
*Last updated: 2026-06-07 — traceability populated after roadmap creation*
