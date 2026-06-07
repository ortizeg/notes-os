"""Shared exception hierarchy for NotesOS.

All project-specific exceptions extend ``NotesOSError`` so callers can catch
the entire NotesOS surface with a single ``except NotesOSError`` clause.
Phase 2+ modules add domain-specific subclasses (e.g. ``AppleScriptError``,
``BackupError``) that inherit from this root.
"""

from __future__ import annotations


class NotesOSError(Exception):
    """Root exception for all NotesOS errors.

    Raise this class directly only for generic, uncategorized failures.
    Prefer a domain-specific subclass defined in the relevant module.
    """
