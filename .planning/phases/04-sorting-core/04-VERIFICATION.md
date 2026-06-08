---
phase: 04-sorting-core
verified: 2026-06-07T00:00:00Z
status: verified
score: 5/5 must-haves verified (SC5 gap resolved post-verification)
overrides_applied: 0
gaps:
  - truth: "Session summary shows moved/skipped/error counts"
    status: resolved
    resolution: "Fixed in commit fixing show_summary to render Errors count; test asserts 'Errors' in output. 250 tests green."
    reason: >
      RichSortUI.show_summary renders moved, skipped, and total but does NOT
      display the errors count as a named field in the terminal output.
      SC5 explicitly requires moved/skipped/error counts shown to the user.
      The errors field exists in SessionSummary and appears correctly in the
      audit log file, but the terminal summary line omits it.
    artifacts:
      - path: "src/notes_os/sorter/ui.py"
        issue: >
          show_summary format string: "Moved: {moved}  Skipped: {skipped}  Total: {total}"
          — no Errors field rendered. Lines 313-321.
    missing:
      - Add errors = summary.errors and include "Errors: {errors}" in the
        RichSortUI.show_summary formatted output. Add a test assertion
        verifying errors appears in the rendered text.
---

# Phase 4: Sorting Core Verification Report

**Phase Goal:** A user can sort their entire Apple Notes inbox into PARA folders using single keystrokes — config-driven, full routing state machine, previewed notes, tracked session summary — runnable end-to-end (pre-TUI; Phase 6 wraps in Textual).

**Verified:** 2026-06-07

**Status:** GAPS FOUND

**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Config loads from ~/.notes-os/config.toml when present, defaults otherwise; malformed TOML raises a clear validation error (SC1) | VERIFIED | load_config() in config.py returns SorterConfig() defaults when path absent; wraps tomllib.TOMLDecodeError in ConfigError with file path; pydantic.ValidationError propagates for schema-invalid values. 26 config unit tests all pass. |
| 2 | P/A/R/X advances router correctly; X->Archive/{year}; [B] backs out one level; S skips; invalid input re-prompts unchanged (SC2) | VERIFIED | Router.handle_category/handle_folder/handle_subfolder/handle_back fully implemented and tested. 49 router unit tests at 99% coverage. Full-loop integration test drives all branches including back-out and invalid key. |
| 3 | Numbered folder list after P/A/R; number+Enter confirms; subfolders prompt if present (General first) (SC3) | VERIFIED | _sort_general_first() proven; prompt_choice renders 1-based list and parses number+Enter. Integration test proves 3-level path (Projects/Web/Research) with back-out. |
| 4 | Move confirmation shows full resolved PARA path before the backup-then-move executes (SC4) | VERIFIED | build_default_controller wraps AppleScriptNotesRepository in BackingUpNotesRepository. Router._do_move calls ensure_folder then move_note in that order (ordering test exists). RouteResult.display_path carries the full separator-joined path. |
| 5 | Session summary shows moved/skipped/error counts; log written to ~/.notes-os/logs/...log (SC5) | PARTIAL - BLOCKER | Log file VERIFIED: write_log() creates YYYY-MM-DD_HH-MM-SS.log with moved/skipped/errors/total. Terminal display FAILED: RichSortUI.show_summary renders moved, skipped, and total only — errors count is NOT shown on screen. |

**Score:** 4/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/notes_os/config.py | SorterConfig composing BridgeConfig+BackupConfig; load_config TOML+defaults+error | VERIFIED | 164 lines. All four sub-models, full TOML load path. 100% coverage. |
| src/notes_os/sorter/router.py | UI-agnostic state machine; archive auto-year; [B] back; invalid no-op; separator | VERIFIED | 467 lines. RouterState (5 states), RouteAction (3), Router with all four handle_* methods. 99% coverage. |
| src/notes_os/sorter/ui.py | Thin, injectable Console/readers | VERIFIED | 325 lines. SortUIProtocol (runtime_checkable), RichSortUI with injectable I/O. Zero print() calls in src/. 100% coverage. |
| src/notes_os/sorter/session.py | SortSession counts/SessionSummary/write_log | VERIFIED | 257 lines. SortSession, frozen SessionSummary (moved/skipped/errors/total), write_log with injectable clock. 100% coverage. |
| src/notes_os/sorter/controller.py | DI loop; build_default_controller wraps bridge in BackingUpNotesRepository | VERIFIED | 349 lines. SortController with full inbox loop, error isolation, session recording. build_default_controller chains AppleScriptNotesRepository -> BackingUpNotesRepository. 82% coverage. |
| src/notes_os/sorter/__main__.py | python -m notes_os.sorter runner; NOT a notes entry point | VERIFIED | Calls load_config() -> build_default_controller() -> controller.run(). pyproject.toml [project.scripts] has only notes_os.app:main. |
| tests/test_config_unit.py | Tests: valid TOML, malformed raises, defaults when absent | VERIFIED | 26 tests. |
| tests/sorter/test_router_unit.py | Tests: all SC2/SC3 transitions | VERIFIED | 49 tests, 99% coverage. |
| tests/sorter/test_session_unit.py | Tests: counts/summary/write_log under tmp_path with injected clock | VERIFIED | 27 tests. |
| tests/sorter/test_controller_integration.py | Full-loop FakeUI + MockNotesRepository; no integration mark | VERIFIED | 7 tests, no @pytest.mark.integration — runs in CI. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| config.py: load_config | ~/.notes-os/config.toml | tomllib.load() + ConfigError on TOMLDecodeError | WIRED | Absent returns defaults; present parsed and validated. |
| router.py: handle_category("x") | (archive_base, year_provider()) | _DISPLAY_SEP.join, injected year_provider | WIRED | year_provider injected; separator confirmed. |
| controller.py: build_default_controller | backup.BackingUpNotesRepository | BackupManager(config.backup) wraps inner repo | WIRED | Lines 324-331. |
| controller.py: _sort_one_note | session.record_move/skip/error | RouteAction dispatch + try/except NotesOSError | WIRED | All three record_* methods wired. |
| controller.py: run() | session.write_log(config.log_dir) | After loop completes | WIRED | Line 132. |
| session.py: write_log | log_dir/YYYY-MM-DD_HH-MM-SS.log | Path.mkdir(parents=True) + write_text | WIRED | Pathlib only. |
| ui.py: show_summary | errors count in terminal display | NOT WIRED | BROKEN | Format string omits Errors field — only moved/skipped/total rendered. |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| mypy strict (17 files) | .pixi/envs/default/bin/mypy src | No issues in 17 source files | PASS |
| ruff lint | .pixi/envs/default/bin/ruff check src tests | All checks passed | PASS |
| ruff format | .pixi/envs/default/bin/ruff format --check src tests | 31 files already formatted | PASS |
| Router 95% coverage floor | pytest test_router_unit.py --cov-fail-under=95 | 99.04% — 49 passed | PASS |
| Overall 80% coverage floor | pytest -m 'not integration' --cov=notes_os --cov-fail-under=80 | 94.85% — 249 passed | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|------------|--------|----------|
| CONF-01 | 04-01, 04-05 | SATISFIED | load_config() called in __main__.py. |
| CONF-02 | 04-01 | SATISFIED | BridgeConfig and BackupConfig composed as nested fields — not duplicated. |
| ROUT-01..08 | 04-02 | SATISFIED | All eight routing requirements proven by 49 unit tests + integration test. |
| UI-01..04 | 04-03 | SATISFIED | render_note/prompt_category/show_help/show_inbox_count all implemented and tested. |
| SESS-01 | 04-04 | SATISFIED | record_move/skip/error accumulate independently. |
| SESS-02 | 04-04 | SATISFIED | summary() returns frozen SessionSummary with all four fields. |
| SESS-03 | 04-04 | PARTIAL | Log file fully correct. Terminal show_summary omits errors field (SC5 gap). |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/notes_os/sorter/ui.py | 313-321 | show_summary format string excludes errors field | BLOCKER | Terminal summary does not display errors count — SC5 requires all three counts shown. |

No debt markers (TBD/FIXME/XXX/TODO/HACK) in any Phase 4 source files. No placeholder code. No print() calls in src/. No empty return stubs.

---

### Human Verification Required

None. All behavioral checks are covered by the test suite and static analysis.

---

## Gaps Summary

**1 gap blocking full SC5 achievement.**

Root cause: RichSortUI.show_summary (written in plan 04-03 as a forward-compatible seam) accesses moved, skipped, and total but was not updated when SessionSummary gained the errors field in plan 04-04. The log file records errors correctly; only the on-screen summary is incomplete.

SC5 states: "Session summary shows moved/skipped/error counts"

- Log file: VERIFIED — errors count at line "Errors:  N" in every session log.
- Terminal display: FAILED — format string "Moved: {moved}  Skipped: {skipped}  Total: {total}" has no Errors line.

Fix (src/notes_os/sorter/ui.py, RichSortUI.show_summary):

Add errors = summary.errors and include "Errors: [red]{errors}[/red]" in the console.print() call. Add a test assertion in tests/sorter/test_ui_unit.py verifying the errors count appears in the rendered output.

---

_Verified: 2026-06-07_
_Verifier: Claude (gsd-verifier)_
