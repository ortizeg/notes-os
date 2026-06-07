# CLAUDE.md — Repo guide for Claude and contributors

## What this project is

**NotesOS M1 — PARA Notes Sorter.** A local-first, keyboard-driven CLI/TUI that lets you triage
your Apple Notes inbox into a PARA folder structure (Projects / Areas / Resources / Archive) using
single keystrokes. Notes are moved, never deleted; the Notes database is backed up automatically
before every write. The app runs entirely on macOS via an AppleScript bridge and has no network
dependencies in M1.

See `.planning/PROJECT.md` for the full four-milestone vision and requirement list.

## Coding standards

Standards live in `~/.claude/skills` — the two relevant skills are **Expert Coder Agent** and
**Code Quality**. Key rules that every file in this repo must follow:

- `from __future__ import annotations` in every `.py` file (placed after the module docstring,
  before all other imports)
- **mypy strict** — zero errors; no `type: ignore` without a comment explaining why
- **Ruff full ruleset** (`E,F,I,N,UP,S,B,A,C4,T20,SIM,TCH,RUF,PTH,ERA`) — run `pixi run ruff`
- **Zero `print()`** in `src/` — use `logging` exclusively
- **Pydantic V2 frozen models** for all config and data objects
- `pathlib` over `os.path` everywhere
- **Google-style docstrings** with full parameter/return type annotations
- Dependency injection, `Protocol` interfaces — no global state, no magic numbers

## Dev workflow

```bash
pixi run notes     # run the app
pixi run ruff      # lint (ruff check + format --check)
pixi run format    # auto-format (ruff format + ruff check --fix)
pixi run mypy      # type-check (strict)
pixi run pytest    # run tests
```

- Branch naming: `feat/short-description` or `fix/short-description`
- Commit format: `type(scope): description` — types: `feat fix test refactor docs chore`
- One PR per feature; never commit directly to `main`
- CI runs lint → typecheck → test on macOS-latest × Python 3.11 and 3.12

## Testing rules

- Write-path modules (`notes.py`, `backup.py`, `router.py`): **95% coverage floor**
- All other modules: **80% coverage floor**; overall CI gate is `--cov-fail-under=80`
- Integration tests: `@pytest.mark.integration`, macOS-only, use `_TestInbox` — never touch real notes
- Default CI run: `pytest -m 'not integration'`
- All external I/O (AppleScript, filesystem, subprocess) must be mocked in unit tests

## Branch protection

Run `scripts/setup-branch-protection.sh` once after the GitHub remote is created. It applies
squash-merge, delete-on-merge, and required PR + CODEOWNERS review on `main`. It is a no-op when
no remote or `gh` CLI is present.
