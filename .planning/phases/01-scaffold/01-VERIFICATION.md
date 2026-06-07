---
phase: 01-scaffold
verified: 2026-06-07T00:00:00Z
status: gaps_found
score: 4/5
overrides_applied: 0
gaps:
  - truth: "A git push to a feature branch triggers the three-job CI matrix (lint / typecheck / test) on macOS-latest x Python 3.11 and 3.12 and all jobs PASS on the scaffold"
    status: failed
    reason: "The test.yml job runs `pytest --cov=notes_os --cov-fail-under=80` but coverage on the Phase 1 scaffold is 48% (stub packages config.py, distiller, graph, suggestions, exceptions have 0% coverage and are included in the --cov scope). Exit code 1 confirmed locally. The CI job would reject the scaffold it is supposed to guard."
    artifacts:
      - path: ".github/workflows/test.yml"
        issue: "Line 33: `pytest -m 'not integration' --cov=notes_os --cov-report=xml --cov-fail-under=80` fails on current scaffold with 48% total coverage"
      - path: "pyproject.toml"
        issue: "No [tool.coverage.report] omit section to exclude stub __init__.py files from coverage measurement"
    missing:
      - "Add a [tool.coverage.report] omit list in pyproject.toml to exclude stub packages (distiller/, graph/, suggestions/, config.py) from coverage, OR lower --cov-fail-under to a value the scaffold actually achieves, OR add minimal tests for stub packages to reach 80%"
      - "The coverage scope --cov=notes_os covers all subpackages including Phase 2-4 stubs that have no tests by design; either the gate threshold must reflect reality or the measured scope must be narrowed"
---

# Phase 1: Scaffold — Verification Report

**Phase Goal:** The repo infrastructure exists and every future commit is guarded by CI and code-quality gates.
**Verified:** 2026-06-07
**Status:** VERIFIED (gap resolved post-verification)
**Re-verification:** Yes — single gap (SC-3) closed in commits `e579f7f`, `2dc305b`

> **Gap Resolution (2026-06-07):** The sole gap — the CI test job failing at 48% coverage
> against the `--cov-fail-under=80` gate — was closed by adding a package-import smoke test
> (`tests/test_package_imports.py`, which also strengthens SCAF-02 proof) and a `main()`
> version-fallback test. Coverage is now **100%**. The exact CI command
> (`pytest -m 'not integration' --cov=notes_os --cov-fail-under=80`) exits 0. A `.gitignore`
> was also added (`e579f7f`) — a scaffold omission caught during finalization. All 5 success
> criteria now genuinely pass. Final local sweep: `ruff check` ✓, `mypy --strict` ✓ (8 files),
> `pytest` ✓ (13 passed, 100% cov).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `pixi run notes` resolves from repo root without error (entry point wired via pyproject.toml + Hatchling) | VERIFIED | `pixi run notes` exits 0; logs `INFO notes_os.app: NotesOS 0.1.dev6+... — TUI arrives in Phase 6.`; `pyproject.toml [project.scripts]` contains `notes = "notes_os.app:main"`; `app.py` defines `def main() -> None` |
| 2 | Stub packages exist at `src/notes_os/distiller/`, `graph/`, `suggestions/` so `import notes_os.distiller` (and graph, suggestions) succeeds without extras | VERIFIED | `pixi run python -c "import notes_os, notes_os.distiller, notes_os.graph, notes_os.suggestions; print('imports ok')"` exits 0 and prints `imports ok`; all three `__init__.py` stubs confirmed present and non-empty |
| 3 | A git push triggers three-job CI matrix (lint / typecheck / test) on macOS-latest x Python 3.11 and 3.12 AND all jobs pass on the scaffold | FAILED | CI job definitions are correct (macOS-only, both Python versions, three jobs). But `pytest --cov=notes_os --cov-fail-under=80` **fails** on the scaffold: total coverage 48.28%. Exit code 1 confirmed by running the exact CI command locally. The stub packages (distiller, graph, suggestions, config, exceptions) have 0% coverage and are included in the `--cov=notes_os` measurement scope. |
| 4 | A commit with a ruff violation or missing type annotation is rejected by pre-commit | VERIFIED (deferred to CI) | `.pre-commit-config.yaml` contains ruff, ruff-format, and mirrors-mypy (--strict) hooks with correct revs; `types-readchar` correctly absent (does not exist on PyPI); `pydantic>=2.0` present. SUMMARY records direct proof: ruff caught T201+PTH109, mypy caught no-untyped-def on a throwaway file. `pre-commit run --all-files` deferred to CI (pre-commit not installed in local pixi env). |
| 5 | `main` requires passing PR + CODEOWNERS enforced (codified in conditional script) | VERIFIED | `CODEOWNERS` exists with `* @ortizeg`; `scripts/setup-branch-protection.sh` is executable, syntax-valid (`bash -n` passes), exits 0 gracefully with no remote (prints skip message), and contains `gh api --method PUT .../branches/main/protection` with `require_code_owner_reviews: true`, squash-merge, delete-on-merge |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | Hatchling build, `notes` entry point, ruff/mypy/pytest config | VERIFIED | All specs present: `notes = "notes_os.app:main"`, `hatchling` + `hatch-vcs`, all ruff rules, mypy strict flags, pytest markers + `addopts = ["-m", "not integration"]` |
| `pixi.toml` | pixi workspace + task runner (notes, ruff, mypy, pytest) | VERIFIED | `[workspace]` section (correct pixi v0.62+ syntax), `[tasks]` with all required tasks; editable install via `para-notes-sorter = { path = ".", editable = true }` |
| `.python-version` | Contains `3.11` | VERIFIED | File contains `3.11` |
| `src/notes_os/app.py` | `NotesOSApp` placeholder + `main()` entry stub | VERIFIED | `def main() -> None` present, uses `importlib.metadata`, logs banner, no print(), full type annotations |
| `src/notes_os/py.typed` | PEP 561 marker | VERIFIED | Empty file exists |
| `src/notes_os/distiller/__init__.py` | M2 stub package | VERIFIED | Exists, has `from __future__ import annotations` and docstring |
| `src/notes_os/graph/__init__.py` | M3 stub package | VERIFIED | Exists, has `from __future__ import annotations` and docstring |
| `src/notes_os/suggestions/__init__.py` | M4 stub package | VERIFIED | Exists, has `from __future__ import annotations` and docstring |
| `.github/workflows/lint.yml` | lint + typecheck jobs on macOS x py3.11/3.12 | VERIFIED | Two jobs (`lint`, `typecheck`), `runs-on: macos-latest`, matrix `["3.11", "3.12"]`, `fail-fast: false`; no ubuntu |
| `.github/workflows/test.yml` | pytest job with coverage gate on macOS x py3.11/3.12 | STUB-BROKEN | File exists and is structurally correct, but `--cov-fail-under=80` fails on the scaffold at 48% coverage |
| `.pre-commit-config.yaml` | ruff, ruff-format, mypy(strict) hooks | VERIFIED | All three hook repos present with pinned revs; `pydantic>=2.0` in additional_dependencies; `types-readchar` correctly absent |
| `CODEOWNERS` | Default owner assignment | VERIFIED | `* @ortizeg` present |
| `scripts/setup-branch-protection.sh` | Conditional gh-based protection script | VERIFIED | Executable, syntax valid, exits 0 with no remote, contains `gh api` branch protection call |
| `CLAUDE.md` | Repo guide pointing to skills + coding standards | VERIFIED | Present, references `~/.claude/skills`, documents all key rules and dev workflow |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `pyproject.toml [project.scripts]` | `src/notes_os/app.py:main` | `notes = "notes_os.app:main"` | WIRED | Entry point resolves; `pixi run notes` runs without error |
| `pixi.toml [tasks] notes` | `notes` console script | `notes = "notes"` task invokes installed console script | WIRED | `pixi run notes` works |
| `.github/workflows/*.yml` | `pyproject.toml` tool configs | `pip install -e .` + `ruff/mypy/pytest` read from pyproject | WIRED (structurally) | CI installs project and runs tools that read pyproject.toml config |
| `.pre-commit-config.yaml mirrors-mypy` | pydantic | `additional_dependencies: ["pydantic>=2.0"]` | WIRED | pydantic present; types-readchar correctly absent |
| `test.yml --cov-fail-under=80` | scaffold coverage | requires >=80% total coverage | NOT_WIRED | 48% coverage on scaffold — gate will block CI |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Entry point runs without error | `pixi run notes` | Exits 0, logs banner | PASS |
| All stub imports succeed | `pixi run python -c "import notes_os, notes_os.distiller, notes_os.graph, notes_os.suggestions"` | `imports ok` | PASS |
| Ruff passes clean | `pixi run ruff` | `All checks passed!` | PASS |
| Mypy strict passes clean | `pixi run mypy` | `Success: no issues found in 8 source files` | PASS |
| Pytest passes (3 tests) | `pixi run pytest` | `3 passed in 0.01s` | PASS |
| Ruff format passes | `pixi run python -m ruff format --check src tests` | `11 files already formatted` | PASS |
| CI coverage gate | `pytest -m 'not integration' --cov=notes_os --cov-report=xml --cov-fail-under=80` | **EXIT CODE 1** — `FAIL Required test coverage of 80% not reached. Total coverage: 48.28%` | **FAIL** |
| Branch protection script exits 0 with no remote | `bash scripts/setup-branch-protection.sh` | Exits 0 with skip message | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SCAF-01 | 01-01 | Monorepo, src layout, pixi env, `notes` entry point | SATISFIED | Entry point wired and running |
| SCAF-02 | 01-01 | Stub packages for distiller/graph/suggestions importable | SATISFIED | All three imports confirmed |
| SCAF-03 | 01-02 | Three-tiered CI on macOS × 3.11/3.12 | BLOCKED | Jobs defined correctly but test job fails on scaffold (48% coverage vs 80% gate) |
| SCAF-04 | 01-02 | Pre-commit enforces ruff, mypy strict, file hygiene | SATISFIED (deferred to CI) | Config correct; direct tool proof in SUMMARY; full hook run deferred |
| SCAF-05 | 01-03 | CODEOWNERS, PR/issue templates, branch protection script | SATISFIED | All files present and functional |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/notes_os/app.py` | 1-8 | Module docstring precedes `from __future__ import annotations` | Warning | Violates coding standard "every .py file starts with `from __future__ import annotations`"; does not affect runtime or mypy |
| `tests/test_app.py` | 1-2 | Module docstring precedes `from __future__ import annotations` | Warning | Same violation; no runtime impact |
| `src/notes_os/__init__.py` et al. | 1 | `from __future__ import annotations` before module docstring | Warning | Opposite ordering: future import first means `module.__doc__` is `None` (confirmed: `import notes_os; notes_os.__doc__` returns `None`) |
| `.github/workflows/test.yml` | 33 | `--cov-fail-under=80` with no coverage omit config | BLOCKER | CI test job fails on current scaffold (48% coverage); see Gap detail |

No TBD/FIXME/XXX debt markers found in any phase files.

### Human Verification Required

None — all success criteria are verifiable by inspection and tool execution.

### Gaps Summary

**One BLOCKER gap:**

**SC-3: CI test job coverage gate incompatible with scaffold**

The `test.yml` job runs `pytest -m 'not integration' --cov=notes_os --cov-report=xml --cov-fail-under=80`. The `--cov=notes_os` flag measures coverage across the entire `notes_os` package including stub `__init__.py` files for Phase 2-4 packages (`distiller/`, `graph/`, `suggestions/`, `config.py`, `exceptions.py`) that have zero tests by design. Total measured coverage is **48.28%** — failing the 80% floor.

This means the CI gate defined in this phase would **reject the scaffold it is supposed to protect**. The ROADMAP Success Criterion 3 requires "all jobs pass on the scaffold" — the test job does not.

**Options to resolve:**

1. **Recommended:** Add `[tool.coverage.report]` to `pyproject.toml` with `omit` listing stub-only files (or use `exclude_lines` for `__init__.py` stubs), so the measured coverage reflects testable code only.
2. **Alternative:** Change `--cov=notes_os` to `--cov=notes_os.app --cov=notes_os.sorter` (scope to non-stub packages only) in `test.yml`.
3. **Alternative:** Lower `--cov-fail-under` to a value the scaffold achieves (e.g. 80% of `app.py` alone = 86%), but this would require restructuring the measurement scope.

The most semantically correct fix is option 1: stubs with no tests should not count against the coverage floor.

---

## Additional Notes (Non-Blocking)

**`from __future__ import annotations` placement inconsistency:**

The coding standard states files should start with `from __future__ import annotations`, but the two styles found are:
- Most `__init__.py` files: future import on line 1 (before docstring) — loses `module.__doc__`
- `app.py` and `test_app.py`: docstring on line 1, future import after — preserves `__doc__` but violates "starts with" rule

Neither style blocks any tooling (ruff passes both). This inconsistency should be standardized in a follow-up commit.

**`pixi.toml` uses `[workspace]` not `[project]`:** The PLAN specified `[project]` but the file correctly uses `[workspace]`, which is the valid section key in pixi v0.14+. Pixi resolves the environment without error. This is correct.

**`types-readchar` correctly absent:** The PLAN spec included `types-readchar` in both `pixi.toml` dev deps and `.pre-commit-config.yaml` `additional_dependencies`. Both the SUMMARY and the actual files correctly omit it — the package does not exist on PyPI. SC-4 success criteria explicitly require this absence.

---
_Verified: 2026-06-07_
_Verifier: Claude (gsd-verifier)_
