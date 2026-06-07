---
phase: 01-scaffold
plan: "03"
subsystem: infra
tags: [github, codeowners, branch-protection, gh-cli, issue-templates, pr-template, claude-md]

requires:
  - phase: 01-scaffold/01-01
    provides: pyproject.toml, pixi.toml, ruff/mypy config, package structure

provides:
  - CODEOWNERS assigning default ownership to @ortizeg for PR review enforcement
  - .github/PULL_REQUEST_TEMPLATE.md with ruff/mypy/pytest + conventional-commit checklist
  - .github/ISSUE_TEMPLATE/bug_report.yml — structured GitHub issue form (labels: bug)
  - .github/ISSUE_TEMPLATE/feature_request.yml — structured GitHub issue form (labels: enhancement)
  - CLAUDE.md at repo root pointing contributors and agents to coding standards and dev workflow
  - scripts/setup-branch-protection.sh — idempotent, conditional gh-based protection script

affects:
  - all future phases (CLAUDE.md is the contributor/agent guide read at every phase)
  - GitHub remote setup (CODEOWNERS and branch protection become active after remote is created)

tech-stack:
  added:
    - gh CLI (conditional dependency for branch-protection script — not a pixi dep)
  patterns:
    - CODEOWNERS at repo root (GitHub honors root placement alongside .github/)
    - Conditional guard pattern: check remote → check gh → check auth → act
    - CLAUDE.md as single source of truth for agent/contributor standards

key-files:
  created:
    - CODEOWNERS
    - .github/PULL_REQUEST_TEMPLATE.md
    - .github/ISSUE_TEMPLATE/bug_report.yml
    - .github/ISSUE_TEMPLATE/feature_request.yml
    - CLAUDE.md
    - scripts/setup-branch-protection.sh
  modified: []

key-decisions:
  - "CODEOWNERS uses @ortizeg — actual GitHub handle once remote exists; placeholder if remote differs"
  - "Branch protection script uses three sequential guards (remote → gh installed → gh auth) with exit 0 on each — safe to run in any environment"
  - "scripts/setup-branch-protection.sh references CI job names from 01-02 (lint, typecheck, test) — update if workflow job IDs change"

patterns-established:
  - "Conditional guard pattern: remote-check → tool-check → auth-check → gh api call; each guard exits 0 with a clear skip message"
  - "CLAUDE.md is the single authoritative guide for Claude agents and human contributors — kept under 60 lines, focused on must-know rules"

requirements-completed: [SCAF-05]

duration: 2min
completed: "2026-06-07"
---

# Phase 01 Plan 03: Repo Hardening Summary

**CODEOWNERS, PR/issue templates, CLAUDE.md, and a conditional branch-protection script that exits 0 gracefully with no remote and applies squash-merge + CODEOWNERS review once the GitHub remote exists**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-07T18:50:07Z
- **Completed:** 2026-06-07T18:52:10Z
- **Tasks:** 2 of 2
- **Files modified:** 6

## Accomplishments

- CODEOWNERS assigns `@ortizeg` as default reviewer; GitHub enforces this once branch protection is active
- PR template and two GitHub issue forms (bug/feature) committed; YAML forms parse cleanly
- CLAUDE.md distils coding standards, dev workflow, and testing rules into a single < 60-line file for agents and contributors
- `scripts/setup-branch-protection.sh` is idempotent, syntactically valid, executable, and exits 0 with a clear skip message when no remote or `gh` is available — verified in this environment

## Task Commits

1. **Task 1: Create CODEOWNERS, PR template, and issue templates** — `ea34fac` (chore)
2. **Task 2: Author CLAUDE.md and the conditional branch-protection script** — `34b6599` (chore)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `CODEOWNERS` — default `* @ortizeg` ownership rule with explanatory comment header
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist: summary, issue link, type of change, ruff/mypy/pytest pass, conventional commits, no direct-to-main commits
- `.github/ISSUE_TEMPLATE/bug_report.yml` — GitHub issue form: what happened, steps to reproduce, expected behaviour, macOS/Python/Apple Notes version fields
- `.github/ISSUE_TEMPLATE/feature_request.yml` — GitHub issue form: problem/motivation, proposed solution, alternatives, milestone (M1–M4) selector
- `CLAUDE.md` — project overview, coding standards (mypy strict, ruff full ruleset, Pydantic V2, pathlib, logging-not-print, Google docstrings), dev workflow, testing rules
- `scripts/setup-branch-protection.sh` — guarded idempotent script applying squash-merge, delete-on-merge, and main branch protection with CODEOWNERS review via `gh api`

## Decisions Made

- **CODEOWNERS handle `@ortizeg`**: GitHub login derived from project email (ortizeg@gmail.com). If the actual GitHub remote uses a different organization name, update CODEOWNERS before enabling branch protection.
- **Three-guard pattern for branch protection script**: checks remote presence → `gh` installed → `gh auth status` — each exits 0 with an actionable skip message. This makes the script safe in any CI or local environment without a remote.
- **CI status check names in protection script**: `lint`, `typecheck`, `test` match the job names from 01-02 CI workflows. If those job IDs change, update the `contexts` array in the `gh api` JSON payload.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- `pyyaml` is not in the pixi environment (only stdlib is available by default). Used the system `python3` (with pyyaml installed via pip3) for YAML parse verification. The project's pixi environment has no YAML parsing need — this was a verification-only concern.

## User Setup Required

None — no external service configuration required.

After a GitHub remote is created, run:

```bash
bash scripts/setup-branch-protection.sh
```

This applies squash-merge + delete-on-merge + required PR review with CODEOWNERS enforcement on `main`.

## Known Stubs

None — all files are complete and production-ready. The branch-protection script contains a commented placeholder (`@ortizeg`) that should be verified against the actual GitHub org/user once the remote is created, but this is documentation, not a code stub.

## Next Phase Readiness

- Phase 01 is now complete: scaffold (01-01), CI workflows (01-02), and repo hardening (01-03) are all committed
- Phase 02 (AppleScript bridge) can proceed immediately: the package structure, CI, and contributor standards are all in place
- CODEOWNERS and branch protection will activate automatically once the GitHub remote is added and `setup-branch-protection.sh` is run

## Self-Check: PASSED

All 6 key files verified present on disk. Both task commits verified in git log (ea34fac, 34b6599).

---
*Phase: 01-scaffold*
*Completed: 2026-06-07*
