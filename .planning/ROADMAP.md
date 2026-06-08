# Roadmap: NotesOS — Milestone 1 (PARA Notes Sorter)

## Overview

Milestone 1 delivers a keyboard-driven, non-destructive PARA inbox triage tool for Apple Notes. The build follows a strict dependency chain — scaffold the repo, build the AppleScript bridge (the sole read/write path), lock in backup safety before any move is ever exercised, wire up the sorting core (config + router + UI + session), add opt-in task extraction, then integrate everything into the Textual TUI. Each phase is independently verifiable before the next begins.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Scaffold** — Monorepo, pixi env, CI, pre-commit, branch protection, M2-M4 stubs
- [x] **Phase 2: AppleScript Bridge** — Read inbox, discover PARA structure, move note, ensure folder, typed errors, NotesRepositoryProtocol (completed 2026-06-07)
- [x] **Phase 3: Backup** — Auto-backup-before-write, create/list/restore/prune, BackupError (completed 2026-06-07)
- [x] **Phase 4: Sorting Core** — Config (Pydantic V2), PARA router state machine, terminal UI primitives, session tracking (completed 2026-06-07)
- [x] **Phase 5: Task Extraction** — Heuristic action-item scanner, user selection, Markdown output, off by default (completed 2026-06-07)
- [ ] **Phase 6: Textual TUI Integration** — Full Textual app wired end-to-end via `notes` entry point

## Phase Details

### Phase 1: Scaffold

**Goal**: The repo infrastructure exists and every future commit is guarded by CI and code-quality gates.
**Depends on**: Nothing (first phase)
**Requirements**: SCAF-01, SCAF-02, SCAF-03, SCAF-04, SCAF-05
**Success Criteria** (what must be TRUE):

  1. `pixi run notes` resolves from the repo root without error (entry point wired through pyproject.toml + Hatchling)
  2. Stub packages exist at `src/notes_os/distiller/`, `graph/`, and `suggestions/` so `import notes_os.distiller` succeeds without installing extras
  3. A `git push` to a feature branch triggers the three-job CI matrix (lint / typecheck / test) on macOS-latest × Python 3.11 and 3.12 and all jobs pass on the scaffold
  4. A commit with a ruff violation or a missing type annotation is rejected by the pre-commit hook before it reaches the remote
  5. The `main` branch requires a passing PR to accept changes and CODEOWNERS is enforced

**Plans**: 3 plans

Plans:

- [x] 01-01-PLAN.md — Monorepo init: pyproject.toml (Hatchling + hatch-vcs), pixi.toml, src layout, `notes` entry point, M2-M4 stubs
- [x] 01-02-PLAN.md — CI + pre-commit: three-job GitHub Actions matrix (lint/typecheck/test, macOS × 3.11/3.12), pre-commit hooks
- [x] 01-03-PLAN.md — Repo hardening: CODEOWNERS, PR/issue templates, CLAUDE.md, conditional branch-protection script

---

### Phase 2: AppleScript Bridge

**Goal**: The system can read, navigate, and write Apple Notes through a typed protocol interface — every higher-level module calls this contract, never raw AppleScript.
**Depends on**: Phase 1
**Requirements**: BRDG-01, BRDG-02, BRDG-03, BRDG-04, BRDG-05, BRDG-06, BRDG-07
**Success Criteria** (what must be TRUE):

  1. A unit test retrieves a list of notes from the configured inbox via `NotesRepositoryProtocol` using a `MockNotesRepository` — no AppleScript called
  2. An integration test (macOS-only, `@pytest.mark.integration`, `_TestInbox` folder) reads a real note, confirms its title and stripped-plain-text preview match expectations, then moves it back — the note leaves the inbox and arrives in the target folder
  3. Calling `ensure_folder` twice for the same path succeeds idempotently with no duplicate folder created
  4. Injecting a failing AppleScript stub raises `NotesError` / `FolderNotFoundError` / `NotesMoveError` and the session continues (no crash)
  5. `notes.py` passes mypy strict and achieves ≥95% branch coverage in CI

**Plans**: 3 plans

Plans:

- [x] 02-01-PLAN.md — `models.py` + `notes.py`: `NotesRepositoryProtocol`, osascript wrapper, HTML strip, inbox read, PARA discovery (wave 1)
- [x] 02-02-PLAN.md — `notes.py` move/ensure-folder, `NotesError` hierarchy in exceptions.py, `MockNotesRepository` in conftest.py (wave 2, after 02-01)
- [x] 02-03-PLAN.md — Bridge tests: mocked unit suite (≥95% notes.py coverage) + macOS `_TestInbox` integration suite (wave 3)

---

### Phase 3: Backup

**Goal**: Every write to Apple Notes is preceded by a safe, timestamped copy of the Notes database — backup failure aborts the write, recovery is a single command.
**Depends on**: Phase 2 (write-path knowledge from bridge)
**Requirements**: BKUP-01, BKUP-02, BKUP-03, BKUP-04, BKUP-05, BKUP-06
**Success Criteria** (what must be TRUE):

  1. Calling the bridge's move operation triggers an automatic backup of all three Notes DB files (`NoteStore.sqlite`, `-wal`, `-shm`) before the move executes — verifiable by checking backup directory contents
  2. A timestamped backup created on demand appears in the backup list with its label
  3. Restoring from the most-recent backup replaces the active DB files with the backup copies
  4. Pruning with `retention=3` leaves exactly 3 backups when 5 exist
  5. Simulating a backup I/O failure raises `BackupError` and the pending move is never attempted — confirmed by asserting the target folder did not receive the note
  6. `backup.py` passes mypy strict and achieves ≥95% branch coverage in CI

**Plans**: TBD

Plans:

- [x] 03-01: `backup.py` — auto-backup-before-write hook, create/list, `BackupError`, 95% coverage
- [x] 03-02: `backup.py` — restore, prune (retention=10 default), integration + unit tests

---

### Phase 4: Sorting Core

**Goal**: A user can sort their entire Apple Notes inbox into PARA folders using single keystrokes — with config-driven behavior, full routing state machine, previewed notes, and a tracked session summary — all from the CLI (pre-TUI wrapper).
**Depends on**: Phase 3 (backup active before any move), Phase 2 (bridge)
**Requirements**: CONF-01, CONF-02, ROUT-01, ROUT-02, ROUT-03, ROUT-04, ROUT-05, ROUT-06, ROUT-07, ROUT-08, UI-01, UI-02, UI-03, UI-04, SESS-01, SESS-02, SESS-03
**Success Criteria** (what must be TRUE):

  1. Config loads from `~/.notes-os/config.toml` when present and falls back to frozen Pydantic V2 defaults; a malformed TOML raises a validation error with a clear message
  2. Pressing `P`, `A`, `R`, or `X` at the category prompt advances the router to the correct next state; `X` resolves to `Archive/{year}` with no further prompts; `[B]` backs out one level; `S` skips; invalid input re-prompts unchanged
  3. A numbered folder list appears after selecting Project/Area/Resource, user types a number + Enter to confirm, and subfolders prompt next if they exist (General listed first)
  4. Move confirmation displays the full resolved PARA path (e.g. `Projects › Website Redesign › Research`) before the backup-then-move executes
  5. After the session, a summary shows moved/skipped/error counts and a log file is written to `~/.notes-os/logs/YYYY-MM-DD_HHMMSS.log`

**Plans**: 5 plans

Plans:

- [x] 04-01-PLAN.md — `config.py` — frozen Pydantic V2 SorterConfig composing BridgeConfig+BackupConfig, TOML loader + defaults, mypy override (wave 1)
- [x] 04-02-PLAN.md — `router.py` — UI-agnostic PARA routing state machine (SHOW_NOTE → AWAIT_CATEGORY → AWAIT_FOLDER → AWAIT_SUBFOLDER → CONFIRM_MOVE), archive auto-year (injected clock), `[B]` back, ≥95% coverage (wave 2)
- [x] 04-03-PLAN.md — `ui.py` — thin Rich/readchar layer: title + Markdown preview, single-keystroke capture, numbered choices, `?` help, inbox count, SortUIProtocol for fakes (wave 2)
- [x] 04-04-PLAN.md — `session.py` — moved/skipped/error tracking, frozen SessionSummary, log writer to `~/.notes-os/logs/YYYY-MM-DD_HHMMSS.log` (wave 3)
- [x] 04-05-PLAN.md — Integration — SortController wiring config + backing-up repo + router + ui + session into an end-to-end testable sort flow + full suite (wave 4)

---

### Phase 5: Task Extraction

**Goal**: After routing a note, users who opt in can review heuristically extracted action items and write selected tasks as Markdown checkboxes — the feature is invisible when disabled.
**Depends on**: Phase 4 (routing flow established)
**Requirements**: TASK-01, TASK-02, TASK-03, TASK-04
**Success Criteria** (what must be TRUE):

  1. With `task_extraction = false` (default), no extraction runs and no extraction UI appears — the sort flow is identical to Phase 4
  2. With `task_extraction = true`, the extractor identifies at least one action item (verb phrase, named commitment, or inline date) from a note containing known patterns
  3. User can add all extracted tasks, select a subset by number, or skip — only selected tasks are written
  4. Tasks are appended as Markdown checkboxes to `~/.notes-os/extracted-tasks/YYYY-MM-DD.md`; the file is created if it does not exist

**Plans**: TBD

Plans:

- [x] 05-01: `extractor.py` — heuristic regex/NLP scanner, action-item detection, off-by-default config gate (completed 2026-06-07)
- [x] 05-02: Extraction UI — add-all / select-subset / skip interaction, Markdown file writer, tests

---

### Phase 6: Textual TUI Integration

**Goal**: The `notes` command launches a full Textual application — HomeScreen, SortScreen, and TaskExtractScreen are wired end-to-end with consistent navigation, live status indicators, and the complete sort + extraction flow working as a single cohesive product.
**Depends on**: Phase 5 (all core modules ready), Phase 4, Phase 3, Phase 2
**Requirements**: TUI-01, TUI-02, TUI-03, TUI-04, TUI-05
**Success Criteria** (what must be TRUE):

  1. Running `notes` launches the Textual application and displays the HomeScreen splash with live inbox count, active backend, and last-backup timestamp
  2. Navigating from HomeScreen to SortScreen and triaging one note end-to-end (keyboard-only) moves the note in Apple Notes — backup fires, note leaves inbox, session count increments
  3. With extraction enabled, TaskExtractScreen appears after routing each note and task selection writes to the daily Markdown file
  4. `Esc`/`B` backs up one screen level, `Q` quits from any screen, `?` shows contextual help — navigation is consistent across all screens
  5. CI test suite (Textual Pilot + mocks) passes on macOS-latest × Python 3.11 and 3.12 with overall ≥80% coverage gate green

**Plans**: TBD

Plans:

- [ ] 06-01: `app.py` + `screens/home.py` — Textual app shell, HomeScreen splash, menu, live status indicators
- [ ] 06-02: `screens/sort.py` + widget plumbing — SortScreen wrapping router/UI/backup flow
- [ ] 06-03: `screens/task_extract.py` — TaskExtractScreen wrapping extractor/UI, navigation integration
- [ ] 06-04: End-to-end wiring + test suite — Textual Pilot tests, 80% overall coverage gate, CI green

---

## Progress

**Execution Order:**
Phases execute in dependency order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
| --- | --- | --- | --- |
| 1. Scaffold | 3/3 | Complete | 2026-06-07 |
| 2. AppleScript Bridge | 3/3 | Complete   | 2026-06-07 |
| 3. Backup | 2/2 | Complete | 2026-06-07 |
| 4. Sorting Core | 5/5 | Complete   | 2026-06-07 |
| 5. Task Extraction | 2/2 | Complete   | 2026-06-07 |
| 6. Textual TUI Integration | 0/4 | Not started | - |
