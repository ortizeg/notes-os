---
phase: 04-sorting-core
plan: "01"
subsystem: config
tags: [pydantic, toml, config, frozen-models, composition]
dependency_graph:
  requires: [notes_os.sorter.models.BridgeConfig, notes_os.backup_models.BackupConfig, notes_os.exceptions.NotesOSError]
  provides: [notes_os.config.SorterConfig, notes_os.config.ArchiveConfig, notes_os.config.FeaturesConfig, notes_os.config.ConfigError, notes_os.config.load_config]
  affects: [04-02-router, 04-04-session, 04-05-ui]
tech_stack:
  added: [tomllib (stdlib 3.11+)]
  patterns: [frozen-pydantic-v2, composition-not-inheritance, toml-loader-with-defaults]
key_files:
  created:
    - src/notes_os/config.py
    - tests/test_config_unit.py
  modified:
    - pyproject.toml
decisions:
  - "SorterConfig composes BridgeConfig + BackupConfig as nested fields (Field(default_factory=...)) — no scalar field duplication (CONF-02)"
  - "load_config raises ConfigError for malformed TOML; lets pydantic.ValidationError propagate for schema-invalid values — never silent fallback (SC1)"
  - "notes_os.config added to [[tool.mypy.overrides]] disallow_any_explicit=false alongside sorter.models and backup_models"
  - "ConfigError extends NotesOSError (root) so callers can use a single except clause"
  - "FeaturesConfig is minimal (task_extraction only) — forward-compat placeholder for Phase 5"
metrics:
  duration: "157 seconds"
  completed: "2026-06-07"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 1
---

# Phase 4 Plan 01: SorterConfig + TOML Loader Summary

**One-liner:** Frozen Pydantic V2 `SorterConfig` composing `BridgeConfig`+`BackupConfig`+`ArchiveConfig`+`FeaturesConfig` with a `tomllib`-based TOML loader that returns defaults on absent file and raises `ConfigError` on malformed input.

## What Was Built

### config.py — New Models and Loader

**`ArchiveConfig`** (frozen BaseModel):
- `base_folder: str = "Archive"` — PARA Archive root folder name
- `auto_year: bool = True` — auto-create year subfolder (e.g. `Archive/2026`)

**`FeaturesConfig`** (frozen BaseModel):
- `task_extraction: bool = False` — Phase 5 opt-in flag, off by default

**`ConfigError(NotesOSError)`**:
- Raised when `tomllib.TOMLDecodeError` is caught; message always includes the file path

**`SorterConfig`** (frozen BaseModel — top-level config for all Phase 4 consumers):
- `bridge: BridgeConfig` — composed from Phase 2; `Field(default_factory=BridgeConfig)`
- `backup: BackupConfig` — composed from Phase 3; `Field(default_factory=BackupConfig)`
- `archive: ArchiveConfig` — `Field(default_factory=ArchiveConfig)`
- `features: FeaturesConfig` — `Field(default_factory=FeaturesConfig)`
- `log_dir: Path` — defaults to `~/.notes-os/logs`

**`load_config(path: Path | None = None) -> SorterConfig`** (CONF-01):
1. Resolves to `~/.notes-os/config.toml` when `path=None`
2. Returns `SorterConfig()` defaults if the resolved path does not exist
3. Reads with `tomllib.load(fh)` (binary mode, stdlib 3.11+)
4. Wraps `TOMLDecodeError` in `ConfigError` with the file path
5. Validates the parsed dict via `SorterConfig.model_validate(data)` — `ValidationError` propagates (SC1 enforced: no silent fallback)

### pyproject.toml

Added `"notes_os.config"` to the `[[tool.mypy.overrides]]` module list:
```toml
module = ["notes_os.sorter.models", "notes_os.backup_models", "notes_os.config"]
disallow_any_explicit = false
```

### tests/test_config_unit.py

26 tests across 7 test classes covering:
- `TestSorterConfigDefaults` — all default field values
- `TestSorterConfigComposition` — bridge/backup/archive/features are real nested instances
- `TestFrozenModels` — assignment raises `ValidationError` on all four model types
- `TestLoadConfigAbsent` — non-existent path returns defaults
- `TestLoadConfigValid` — bridge/archive/features sections parse correctly; partial TOML keeps other defaults
- `TestLoadConfigMalformed` — broken TOML raises `ConfigError` with file path in message
- `TestLoadConfigSchemaInvalid` — out-of-range `preview_length=10` raises an error (never silent)

## Verification Results

| Check | Result |
|-------|--------|
| `pytest tests/test_config_unit.py` | 26 passed |
| `pytest -m 'not integration'` (full suite) | 129 passed, 99.74% coverage |
| `ruff check src/notes_os/config.py tests/test_config_unit.py` | Clean |
| `ruff format` | Clean (formatted) |
| `mypy src/` | Success: 12 source files, zero errors |
| `grep notes_os.config pyproject.toml` | Present in mypy override |
| `load_config()` smoke test | `Notes Archive /Users/ortizeg/.notes-os/logs` |

## Accessors for Downstream Plans

Phase 4 plans that consume `SorterConfig`:

| Consumer Plan | Fields Used |
|--------------|-------------|
| 04-02 (router) | `cfg.bridge.inbox_folder`, `cfg.bridge.para_folders`, `cfg.bridge.preview_length` |
| 04-04 (session) | `cfg.archive.base_folder`, `cfg.archive.auto_year`, `cfg.features.task_extraction` |
| 04-05 (UI) | `cfg.log_dir`, `cfg.backup.auto_backup_on_write` |

Import pattern for downstream plans:
```python
from notes_os.config import SorterConfig, load_config, ConfigError
```

## Deviations from Plan

None — plan executed exactly as written. The `ConfigError` is defined in `config.py` per plan (not in `exceptions.py`), which is consistent with the plan's `<action>` text specifying "Define `ConfigError(NotesOSError)` in this module."

## Known Stubs

None — `SorterConfig` is fully wired with real defaults; all fields are populated from real sub-models.

## Threat Surface Scan

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-04-01: malformed/hostile config.toml | `tomllib` (no code eval) + frozen Pydantic validation; out-of-range values rejected by `ge`/`le` constraints; malformed TOML wrapped in `ConfigError` with path | Implemented |
| T-04-02: huge/garbage config file | Accepted (local single-user file; tomllib bounds parsing) | Accepted |
| T-04-SC: pip installs | No new packages; tomllib is 3.11 stdlib | N/A |

## Commits

- `a11cce9` — `test(04-01): add failing tests for SorterConfig + load_config (RED)`
- `88f3eef` — `feat(04-01): SorterConfig + ArchiveConfig + FeaturesConfig + load_config (GREEN)`

## Self-Check: PASSED

Files exist:
- `/Users/ortizeg/1Projects/notes/src/notes_os/config.py` — FOUND
- `/Users/ortizeg/1Projects/notes/tests/test_config_unit.py` — FOUND

Commits exist:
- `a11cce9` — FOUND
- `88f3eef` — FOUND

pyproject.toml contains `notes_os.config` in mypy override — FOUND
