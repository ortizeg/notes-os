"""Application configuration models for NotesOS.

Frozen Pydantic V2 config models for the full sort session, a TOML loader with
sensible defaults, and ``ConfigError`` for clear parse/validation failures.

Usage::

    from notes_os.config import load_config

    cfg = load_config()  # reads ~/.notes-os/config.toml or returns defaults
    cfg = load_config(Path("..."))  # explicit path — returns defaults if absent

The returned :class:`SorterConfig` is immutable after construction (``frozen=True``).
All sub-configs (``bridge``, ``backup``, ``archive``, ``features``) are composed as
nested fields — no scalar fields are duplicated from the Phase 2/3 models.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from notes_os.backup_models import BackupConfig
from notes_os.exceptions import NotesOSError
from notes_os.sorter.models import BridgeConfig


logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH: Path = Path.home() / ".notes-os" / "config.toml"
"""Default location for the user-authored TOML configuration file."""


class ConfigError(NotesOSError):
    """Raised when the config file is malformed or fails TOML parsing.

    Extends :class:`~notes_os.exceptions.NotesOSError` so callers can catch the
    entire NotesOS error surface with a single ``except NotesOSError`` clause.

    Schema-validation failures (invalid field values) may be raised as
    :class:`pydantic.ValidationError` directly (per plan decision) — callers
    that care only about the existence of an error do not need to distinguish
    between the two.

    Args:
        message: Human-readable description that includes the offending file path.
    """


class ArchiveConfig(BaseModel):
    """Config for the archive destination group inside SorterConfig.

    Controls where notes are sent when the user presses the Archive key, and
    whether a year subfolder is auto-created under the archive root.

    Attributes:
        base_folder: Name of the PARA Archive root folder in Apple Notes.
            Defaults to ``"Archive"``.
        auto_year: When ``True`` (the default), notes are placed in a
            year-named subfolder (e.g. ``Archive/2026``) rather than directly
            in the root.  Set to ``False`` to archive flat.
    """

    model_config = ConfigDict(frozen=True)

    base_folder: str = "Archive"
    auto_year: bool = True


class FeaturesConfig(BaseModel):
    """Forward-compatibility feature flags for optional Phase 5+ capabilities.

    Only minimal flags needed by the Phase 4 router and session are declared
    here.  New flags will be added when the corresponding phase plan is executed.

    Attributes:
        task_extraction: When ``True``, the sort session attempts to extract
            action items from note bodies and surface them during review.
            Defaults to ``False`` (Phase 5 opt-in; off in M1).
        extracted_tasks_dir: Directory where the daily Markdown task files are
            written when ``task_extraction`` is enabled.  One file per day,
            named ``YYYY-MM-DD.md``, under this directory.  Created on first
            write if absent.  Defaults to ``~/.notes-os/extracted-tasks``.
    """

    model_config = ConfigDict(frozen=True)

    task_extraction: bool = False
    extracted_tasks_dir: Path = Field(
        default_factory=lambda: Path.home() / ".notes-os" / "extracted-tasks"
    )


class SorterConfig(BaseModel):
    """Top-level immutable configuration for a NotesOS sort session.

    Composes the Phase 2 bridge config and Phase 3 backup config as nested
    fields (CONF-02 — no field duplication) and adds Phase 4-specific groups
    for archive behaviour, feature flags, and log output location.

    All fields are frozen — the object is immutable after construction.  Pass
    overridden sub-configs at construction time; do not attempt to mutate.

    Attributes:
        bridge: AppleScript bridge settings (inbox folder name, preview
            length, PARA folder discovery order).  Composed from
            :class:`~notes_os.sorter.models.BridgeConfig`.
        backup: Backup subsystem settings (backup dir, Notes DB dir,
            retention count, auto-backup toggle).  Composed from
            :class:`~notes_os.backup_models.BackupConfig`.
        archive: Archive destination settings (root folder name, auto-year
            subfolder).  Defined by :class:`ArchiveConfig`.
        features: Optional feature flags for Phase 5+ capabilities.
            Defined by :class:`FeaturesConfig`.
        log_dir: Directory where NotesOS writes its rotating log files.
            Defaults to ``~/.notes-os/logs/``.  Created on first log write
            if absent.
    """

    model_config = ConfigDict(frozen=True)

    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    log_dir: Path = Field(default_factory=lambda: Path.home() / ".notes-os" / "logs")


def load_config(path: Path | None = None) -> SorterConfig:
    """Load and validate a :class:`SorterConfig` from a TOML file.

    When *path* is ``None``, the default ``~/.notes-os/config.toml`` is used.
    If the resolved path does not exist, :class:`SorterConfig` defaults are
    returned and the absence is logged at INFO level.

    Args:
        path: Explicit path to a ``config.toml`` file, or ``None`` to use the
            default location (``~/.notes-os/config.toml``).

    Returns:
        A frozen :class:`SorterConfig` populated from the TOML file when
        present, or from built-in defaults when the file is absent.

    Raises:
        ConfigError: When the file exists but is syntactically invalid TOML.
            The error message names the offending file path.
        pydantic.ValidationError: When the TOML is well-formed but a field
            value fails schema validation (e.g. ``preview_length`` below the
            minimum of 50).  This is never silently swallowed — it always
            propagates so the user sees a clear failure message.
    """
    resolved: Path = path if path is not None else _DEFAULT_CONFIG_PATH

    if not resolved.exists():
        logger.info("Config file not found at %s — using built-in defaults.", resolved)
        return SorterConfig()

    logger.info("Loading config from %s.", resolved)
    try:
        with resolved.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed TOML in config file {resolved}: {exc}") from exc

    # Let pydantic.ValidationError propagate: schema-invalid values must never
    # fall back silently to defaults (SC1 — provable error on bad input).
    return SorterConfig.model_validate(data)
