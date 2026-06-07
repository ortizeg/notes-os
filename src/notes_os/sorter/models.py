"""Frozen Pydantic V2 data models for the NotesOS AppleScript bridge.

Defines the typed contract surface for note data and PARA structure returned
by the AppleScript bridge.  All models are frozen (immutable after construction)
to prevent accidental mutation across the sort session.

Uses ``pydantic.dataclasses`` (Pydantic V2) rather than ``BaseModel`` because
mypy 2.x ``disallow_any_explicit`` does not interact well with ``BaseModel``
inheritance; ``pydantic.dataclasses`` provide identical validation, freezing,
and field constraint behaviour with full mypy strict compatibility.
"""

from __future__ import annotations

from typing import TypeAlias

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass


FolderPath: TypeAlias = tuple[str, ...]
"""Represents a path to a folder in Apple Notes as an ordered tuple of names.

Example:
    ``("Projects", "NotesOS")`` addresses the subfolder ``NotesOS`` inside
    the ``Projects`` PARA root.  A single-element tuple ``("Projects",)``
    addresses the root folder itself.
"""


@dataclass(config=ConfigDict(frozen=True))
class Note:
    """An Apple Notes note surfaced to the sort session.

    Attributes:
        id: The opaque unique identifier returned by Apple Notes
            (e.g. ``"x-coredata://..."``) used to address the note in
            subsequent AppleScript operations.
        title: The note's display name.
        body: The raw HTML body as vended by Apple Notes (may contain
            ``<div>``, ``<b>``, ``<p>``, entity references, etc.).
        preview: Plain-text excerpt derived from *body*, already stripped of
            HTML tags and entity-decoded, truncated to
            ``BridgeConfig.preview_length`` characters.  Populated by the
            repository; kept as a stored field so the Protocol remains I/O-free.
    """

    id: str
    title: str
    body: str
    preview: str


@dataclass(config=ConfigDict(frozen=True))
class ParaStructure:
    """Snapshot of the PARA folder hierarchy discovered in Apple Notes at runtime.

    Attributes:
        roots: The ordered PARA root folder names that were found (typically
            ``("Projects", "Areas", "Resources", "Archive")``).
        subfolders: Mapping from each root name to a tuple of its immediate
            child folder names discovered at query time.  Roots with no
            children map to an empty tuple.
    """

    roots: tuple[str, ...]
    subfolders: dict[str, tuple[str, ...]]

    def subfolders_for(self, root: str) -> tuple[str, ...]:
        """Return the subfolders for a given PARA root.

        Args:
            root: The PARA root folder name (e.g. ``"Projects"``).

        Returns:
            A tuple of subfolder names, or an empty tuple if *root* has no
            children or is not present in this structure.
        """
        return self.subfolders.get(root, ())


@dataclass(config=ConfigDict(frozen=True))
class BridgeConfig:
    """Minimal configuration surface required by the AppleScript bridge in Phase 2.

    Only bridge-relevant settings live here.  Full application config (backup
    paths, router options, archive settings) is deferred to Phase 4's
    ``SorterConfig``.

    Attributes:
        inbox_folder: Name of the Apple Notes folder used as the capture inbox.
            Defaults to ``"Notes"`` (Apple's built-in default).
        preview_length: Maximum character length for the plain-text preview
            shown in the sort UI.  Must be between 50 and 1000 inclusive.
        para_folders: Ordered tuple of PARA root folder names to discover in
            Apple Notes.  Defaults to the canonical PARA order.
    """

    inbox_folder: str = "Notes"
    preview_length: int = Field(default=250, ge=50, le=1000)
    para_folders: tuple[str, ...] = ("Projects", "Areas", "Resources", "Archive")
