"""Textual screen package for NotesOS.

Each module in this package defines one top-level screen of the TUI:

- :mod:`notes_os.screens.home` — :class:`~notes_os.screens.home.HomeScreen`:
  splash, keyboard menu, live status indicators (inbox count, last backup,
  backend label).  This is the root screen pushed by :class:`~notes_os.app.NotesOSApp`.

Future plans will add:

- ``sort.py`` — SortScreen (Phase 06-02)
- ``confirm.py`` — ConfirmQuit overlay (Phase 06-04)
"""

from __future__ import annotations
