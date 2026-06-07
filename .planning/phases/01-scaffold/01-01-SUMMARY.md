---
phase: 01-scaffold
plan: "01"
subsystem: infra
tags: [python, pixi, hatchling, hatch-vcs, ruff, mypy, pytest, textual, pydantic, rich]

requires: []

provides:
  - pyproject.toml with Hatchling+hatch-vcs build, notes entry point, ruff/mypy/pytest config
  - pixi.toml workspace with osx-arm64/osx-64 platforms, editable install, task runner
  - src/notes_os package tree with py.typed, exceptions, config, sorter, distiller, graph, suggestions stubs
  - notes console entry point resolves and runs without error (SCAF-01)
  - distiller/graph/suggestions stub packages importable without extras (SCAF-02)
  - ruff, mypy strict, pytest all passing on scaffold

affects:
  - 01-scaffold/01-02 (CI workflows — consumes pixi.toml and pyproject.toml)
  - 01-scaffold/01-03 (pre-commit — consumes ruff/mypy config)
  - all future phases (all build on this package structure)

tech-stack:
  added:
    - hatchling + hatch-vcs (build backend)
    - pixi 0.62.2 (env + task runner)
    - ruff (linting + formatting)
    - mypy strict (type checking)
    - pytest + pytest-cov (testing)
    - rich >=13 (runtime dep, Phase 4+ use)
    - textual >=0.80 (runtime dep, Phase 6 TUI)
    - readchar >=4 (runtime dep, Phase 4+ use)
    - pydantic >=2 (runtime dep, Phase 4 config)
  patterns:
    - src layout (src/notes_os/) with editable pixi install
    - from __future__ import annotations in all .py files (module docstring first)
    - T20 compliance — zero print() in src, logging only
    - Google-style docstrings with full type annotations
    - hatch-vcs version from git tags (no hand-set version)

key-files:
  created:
    - pyproject.toml
    - pixi.toml
    - .python-version
    - README.md
    - pixi.lock
    - src/notes_os/__init__.py
    - src/notes_os/py.typed
    - src/notes_os/exceptions.py
    - src/notes_os/config.py
    - src/notes_os/app.py
    - src/notes_os/sorter/__init__.py
    - src/notes_os/distiller/__init__.py
    - src/notes_os/graph/__init__.py
    - src/notes_os/suggestions/__init__.py
    - tests/__init__.py
    - tests/sorter/__init__.py
    - tests/test_app.py
  modified: []

key-decisions:
  - "pixi.toml uses [workspace] (not deprecated [project]) — updated to current pixi 0.62+ schema"
  - "types-readchar does not exist on PyPI — removed from pixi.toml dev deps; readchar typing handled via inline annotations"
  - "README.md created as minimal stub — required by hatchling build backend to resolve readme field"
  - "Module docstring placed before from __future__ import annotations to satisfy ruff E402 (imports after docstring) while keeping I001 (isort) clean"
  - "Editable install requires uv pip install -e . after src/ is created — pixi install alone does not inject .pth when src/ did not exist at first install"

patterns-established:
  - "ruff import order: module docstring first, then from __future__ import annotations, then stdlib/third-party imports"
  - "All src files: T20-compliant (logging not print), full type annotations, Google docstrings"
  - "pixi task runner: notes / ruff / format / mypy / pytest aliases"

requirements-completed: [SCAF-01, SCAF-02]

duration: 4min
completed: "2026-06-07"
---

# Phase 01 Plan 01: Repo Scaffold Summary

**Hatchling+hatch-vcs monorepo with pixi task runner, `notes` entry point, and M2-M4 stub packages — ruff, mypy strict, and pytest all green from day one**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-07T18:42:18Z
- **Completed:** 2026-06-07T18:47:11Z
- **Tasks:** 3 of 3
- **Files modified:** 17

## Accomplishments

- `pixi run notes` resolves through the hatchling entry point and exits 0 with a logged version banner (SCAF-01)
- `import notes_os.distiller`, `import notes_os.graph`, `import notes_os.suggestions` all succeed without extras (SCAF-02)
- All three quality gates pass on the scaffold: ruff (full ruleset E,F,I,N,UP,S,B,A,C4,T20,SIM,TCH,RUF,PTH,ERA), mypy strict, pytest 3/3

## Task Commits

1. **Task 1: Author pyproject.toml, pixi.toml, and .python-version** — `3aac751` (chore)
2. **Task 2: Scaffold src/notes_os package tree with M2-M4 stubs** — `003fba6` (feat)
3. **Task 3: Implement app.py entry point and minimal test** — `499e3ce` (feat)

## Files Created/Modified

- `pyproject.toml` — Hatchling+hatch-vcs build, `notes = "notes_os.app:main"` entry point, ruff/mypy/pytest config
- `pixi.toml` — pixi workspace, osx-arm64/osx-64, editable install, notes/ruff/format/mypy/pytest tasks
- `.python-version` — pins Python 3.11
- `README.md` — minimal project readme (required by hatchling)
- `pixi.lock` — locked dependency snapshot
- `src/notes_os/__init__.py` — top-level package marker
- `src/notes_os/py.typed` — PEP 561 typing marker (empty)
- `src/notes_os/exceptions.py` — `NotesOSError` root exception hierarchy
- `src/notes_os/config.py` — config module stub (Pydantic models in Phase 4)
- `src/notes_os/app.py` — `NotesOSApp` placeholder + `main()` entry point with logging and version resolution
- `src/notes_os/sorter/__init__.py` — PARA sorting subpackage stub
- `src/notes_os/distiller/__init__.py` — M2 Distillation Engine stub
- `src/notes_os/graph/__init__.py` — M3 Knowledge Graph stub
- `src/notes_os/suggestions/__init__.py` — M4 Smart Suggestions stub
- `tests/__init__.py` — empty package marker
- `tests/sorter/__init__.py` — empty package marker
- `tests/test_app.py` — 3 tests for app.py (main, instantiate, run)

## Decisions Made

- **[workspace] over [project] in pixi.toml**: pixi 0.62+ deprecates `[project]`; updated to `[workspace]` to avoid warnings.
- **types-readchar removed**: Package does not exist on PyPI. Removed from dev dependencies to unblock `pixi install`. Readchar types handled via inline annotations when needed in later phases.
- **README.md stub added**: Hatchling raises `OSError: Readme file does not exist: README.md` when `readme` field is present in pyproject.toml but the file is missing. Created minimal README.md to satisfy the build backend.
- **Module docstring placement**: Ruff E402 fires when stdlib imports follow a module-level docstring that appears after `from __future__ import annotations`. The correct layout is: module docstring first, then `from __future__ import annotations`, then all other imports. This is valid per PEP 236 and satisfies both E402 and I001.
- **Editable install via uv after src/ creation**: `pixi install` ran before `src/notes_os/` existed and produced a dist-info without the `_editable_impl_*.pth` file. Re-ran `uv pip install -e . --python .pixi/envs/default/bin/python` to inject the `.pth` pointing to `src/`. Future `pixi install` runs pick up the already-registered editable install correctly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created README.md (hatchling build backend required it)**
- **Found during:** Task 1 (pixi install)
- **Issue:** `pixi install` failed — hatchling's `prepare_metadata_for_build_wheel` raised `OSError: Readme file does not exist: README.md` because `readme = "README.md"` was declared in pyproject.toml but the file was absent
- **Fix:** Created minimal `README.md` with project name and one-line description
- **Files modified:** `README.md`
- **Verification:** `pixi install` succeeded after creation
- **Committed in:** `3aac751` (Task 1 commit)

**2. [Rule 3 - Blocking] Removed types-readchar (package does not exist on PyPI)**
- **Found during:** Task 1 (pixi install)
- **Issue:** `pixi install` failed resolving PyPI deps — `types-readchar was not found in the package registry`
- **Fix:** Removed `types-readchar = "*"` from pixi.toml `[pypi-dependencies]`; readchar type stubs are not available and not needed at scaffold stage
- **Files modified:** `pixi.toml`
- **Verification:** `pixi install` succeeded after removal
- **Committed in:** `3aac751` (Task 1 commit)

**3. [Rule 1 - Bug] Fixed pixi.toml [workspace] deprecation**
- **Found during:** Task 1 (pixi install)
- **Issue:** `pixi install` warned that `[project]` field is deprecated; should use `[workspace]`
- **Fix:** Changed `[project]` to `[workspace]` in pixi.toml
- **Files modified:** `pixi.toml`
- **Verification:** No deprecation warning after change
- **Committed in:** `3aac751` (Task 1 commit)

**4. [Rule 1 - Bug] Fixed editable install not registering src/ path**
- **Found during:** Task 2 (import verification)
- **Issue:** `import notes_os` failed in pixi env — `pixi install` ran before `src/notes_os/` existed and did not create the `_editable_impl_para_notes_sorter.pth` file pointing to `src/`
- **Fix:** Ran `uv pip install -e . --python .pixi/envs/default/bin/python` to register the editable install path; verified `_editable_impl_para_notes_sorter.pth` contains `/path/to/notes/src`
- **Files modified:** `.pixi/envs/default/lib/python3.12/site-packages/_editable_impl_para_notes_sorter.pth` (pixi env, not committed)
- **Verification:** `import notes_os` succeeded; all 7 package imports worked
- **Committed in:** `003fba6` (Task 2 commit — source files only; .pixi/ is gitignored)

**5. [Rule 1 - Bug] Fixed ruff E402 / I001 import ordering in all .py files**
- **Found during:** Task 2 (ruff check)
- **Issue:** ruff reported I001 (import block un-sorted) when `from __future__ import annotations` preceded the module docstring; after ruff --fix moved it to the top, E402 fired on stdlib imports following the docstring
- **Fix:** Restructured all .py files: module docstring first → `from __future__ import annotations` → blank line → stdlib/third-party imports. This satisfies PEP 236, ruff I001, and ruff E402 simultaneously
- **Files modified:** all `.py` files in src/notes_os/ and tests/
- **Verification:** `ruff check src/ tests/` → "All checks passed!"
- **Committed in:** `003fba6`, `499e3ce`

---

**Total deviations:** 5 auto-fixed (2 blocking, 3 bugs)
**Impact on plan:** All auto-fixes were necessary to unblock installation and meet quality gates. No scope creep — all changes are within the plan's stated file list.

## Issues Encountered

- pixi task `ruff` passes `src tests` as positional args; the `tests` directory had to exist before Task 2 completed or ruff would fail with E902. Created empty `tests/__init__.py` and `tests/sorter/__init__.py` during Task 2 (they are Task 3 files per the plan spec, but blocking a quality gate justified early creation under Rule 3).

## Known Stubs

| File | Stub | Reason |
|------|------|--------|
| `src/notes_os/config.py` | Empty module | Pydantic V2 config models arrive in Phase 4 |
| `src/notes_os/distiller/__init__.py` | Empty module | M2 Distillation Engine planned in future milestone |
| `src/notes_os/graph/__init__.py` | Empty module | M3 Knowledge Graph planned in future milestone |
| `src/notes_os/suggestions/__init__.py` | Empty module | M4 Smart Suggestions planned in future milestone |
| `src/notes_os/sorter/__init__.py` | Empty module | Router/UI/session modules arrive in Phases 2-4 |
| `src/notes_os/app.py` — `NotesOSApp` | Placeholder class with no Textual wiring | Full Textual App subclass arrives in Phase 6 |

All stubs are intentional per SCAF-02 and the plan objective. They do not prevent the plan's goal (scaffold stability + quality gate green) from being achieved.

## Next Phase Readiness

- Phase 01-02 (CI workflows) can proceed immediately: pyproject.toml and pixi.toml are complete; Python 3.11/3.12 matrix and macOS-only constraint are encoded
- Phase 01-03 (pre-commit) can proceed immediately: ruff and mypy configs are in pyproject.toml
- All future phases have a stable package namespace to import from

## Self-Check: PASSED

All 11 key files verified present on disk. All 3 task commits verified in git log (3aac751, 003fba6, 499e3ce).

---
*Phase: 01-scaffold*
*Completed: 2026-06-07*
