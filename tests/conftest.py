"""Project-root pytest fixtures for NotesOS TUI tests.

Provides fixtures shared across the ``tests/screens/`` package and
``tests/test_app.py``:

- :func:`tui_config` — a :class:`~notes_os.config.SorterConfig` with all I/O
  paths redirected to ``tmp_path`` so no real Notes DB or home-directory paths
  are touched.
- :func:`tui_repo` — a :class:`~tests.sorter.conftest.MockNotesRepository`
  seeded with two representative notes and a :class:`~notes_os.sorter.models.ParaStructure`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from notes_os.backup_models import BackupConfig
from notes_os.config import FeaturesConfig, SorterConfig
from notes_os.sorter.models import Note, ParaStructure
from tests.sorter.conftest import MockNotesRepository


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# tui_config
# ---------------------------------------------------------------------------


@pytest.fixture()
def tui_config(tmp_path: Path) -> SorterConfig:
    """Return a SorterConfig with all I/O paths under ``tmp_path``.

    Ensures that test runs never touch the real Apple Notes database directory
    or the user's ``~/.notes-os/`` home folder.  The ``features.task_extraction``
    flag stays ``False`` (default).

    Args:
        tmp_path: pytest's built-in temporary directory fixture, unique per test.

    Returns:
        A frozen :class:`~notes_os.config.SorterConfig` safe for use in TUI
        unit and Pilot tests.
    """
    notes_db_dir = tmp_path / "notes-db"
    backup_dir = tmp_path / "backups"
    log_dir = tmp_path / "logs"
    extracted_tasks_dir = tmp_path / "tasks"

    notes_db_dir.mkdir()
    backup_dir.mkdir()

    backup_cfg = BackupConfig(
        notes_db_dir=notes_db_dir,
        backup_dir=backup_dir,
    )
    features_cfg = FeaturesConfig(
        task_extraction=False,
        extracted_tasks_dir=extracted_tasks_dir,
    )

    return SorterConfig(
        backup=backup_cfg,
        features=features_cfg,
        log_dir=log_dir,
    )


# ---------------------------------------------------------------------------
# tui_repo
# ---------------------------------------------------------------------------


@pytest.fixture()
def tui_repo() -> MockNotesRepository:
    """Return a MockNotesRepository seeded with two notes and PARA structure.

    The two notes are used to verify that the HomeScreen's inbox count reads
    ``2`` when driven by this fixture (SC1).

    Returns:
        A :class:`~tests.sorter.conftest.MockNotesRepository` with two inbox
        notes and a four-root PARA structure.
    """
    notes = [
        Note(id="tui-1", title="First TUI Test Note", body="<p>body one</p>", preview="body one"),
        Note(id="tui-2", title="Second TUI Test Note", body="<p>body two</p>", preview="body two"),
    ]
    structure = ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": (),
            "Areas": (),
            "Resources": (),
            "Archive": (),
        },
    )
    return MockNotesRepository(notes=notes, structure=structure)
