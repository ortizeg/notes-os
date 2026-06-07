"""PARA router state machine for NotesOS.

Provides an explicit ``RouterState`` enum and a ``Router`` class that consumes
the current state plus an input event, and returns a ``RouteResult`` describing
the next state and any action to take (move, skip, or none).

This module is **UI-agnostic**: it performs no terminal I/O, no ``print``, no
``readchar``.  The TUI (plan 04-03) captures keystrokes and renders; this
module decides what they mean.  Keeping it I/O-free makes it deterministically
testable to the 95% write-path-adjacent coverage floor.

Architecture
------------
The machine has five states (per PRD §5.5):

- ``SHOW_NOTE``       — a note is displayed; waiting for the user to acknowledge it.
- ``AWAIT_CATEGORY``  — waiting for a PARA category key (P/A/R/X/S/?).
- ``AWAIT_FOLDER``    — the user selected a root; now picking a sub-folder by number.
- ``AWAIT_SUBFOLDER`` — the user picked a folder that itself has sub-folders; picking one.
- ``CONFIRM_MOVE``    — (reserved for future confirmation prompt; currently moves are
                         immediate in M1).

Transition entrypoints
----------------------
- :meth:`Router.handle_category`  — keystroke at ``AWAIT_CATEGORY``.
- :meth:`Router.handle_folder`    — 1-based numeric selection at ``AWAIT_FOLDER``.
- :meth:`Router.handle_subfolder` — 1-based numeric selection at ``AWAIT_SUBFOLDER``.
- :meth:`Router.handle_back`      — [B] keystroke backs out one level.

Each method returns a :class:`RouteResult` (frozen Pydantic model) carrying:
- ``state``         — the next ``RouterState``.
- ``action``        — a ``RouteAction`` (MOVE / SKIP / NONE) or ``None``.
- ``folder_path``   — resolved ``FolderPath`` tuple (populated on MOVE).
- ``display_path``  — human-readable path joined with " > " (U+203A narrow nbsp + arrow, displayed as " › ").
- ``options``       — tuple of folder/subfolder names shown to the user next.
- ``selected_root`` — the PARA root chosen at ``AWAIT_CATEGORY`` (carried forward).
- ``selected_folder``  — the folder name chosen at ``AWAIT_FOLDER`` (carried forward).
- ``help_requested``   — ``True`` when '?' is pressed.

Threat mitigations (ROUT-07, T-04-03, T-04-04)
------------------------------------------------
- Any unrecognised key at ``AWAIT_CATEGORY`` is a no-op (state unchanged).
- Out-of-range / non-positive folder/subfolder index is a no-op.
- ``FolderPath`` is resolved only from ``ParaStructure`` + configured archive
  base — no free-form folder creation from user input.
- ``ensure_folder`` is always called **before** ``move_note`` so the target
  exists when the move is issued.
"""

from __future__ import annotations

import datetime
import enum
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from notes_os.sorter.models import (
    FolderPath,  # noqa: TC001  # needed at runtime for Pydantic model validation
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from notes_os.config import SorterConfig
    from notes_os.sorter.models import Note, ParaStructure
    from notes_os.sorter.notes import NotesRepositoryProtocol


logger = logging.getLogger(__name__)

# Separator used in display paths — U+203A (SINGLE RIGHT-POINTING ANGLE QUOTATION MARK)
_DISPLAY_SEP: str = " › "


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RouterState(enum.Enum):
    """Explicit states of the PARA routing state machine (PRD §5.5).

    Values are lowercase strings so they are human-readable in logs and repr.
    """

    SHOW_NOTE = "show_note"
    AWAIT_CATEGORY = "await_category"
    AWAIT_FOLDER = "await_folder"
    AWAIT_SUBFOLDER = "await_subfolder"
    CONFIRM_MOVE = "confirm_move"


class RouteAction(enum.Enum):
    """Action to perform after a state transition.

    Attributes:
        MOVE: The note should be moved to ``RouteResult.folder_path``.
        SKIP: The note should be left in the inbox and skipped for now.
        NONE: No write action; purely a navigation transition.
    """

    MOVE = "move"
    SKIP = "skip"
    NONE = "none"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class RouteResult(BaseModel):
    """Immutable outcome of a single state-machine transition.

    Returned by every ``Router.handle_*`` method.  The UI reads this object to
    update its display and issue any write operations the router decided upon.

    Attributes:
        state:           The next ``RouterState`` after this transition.
        action:          What the caller should do (MOVE / SKIP / NONE), or
                         ``None`` when the transition is purely navigational and
                         no specific action is required (same as NONE but
                         explicit absence).  Callers should treat ``None`` and
                         ``NONE`` identically.
        folder_path:     Resolved ``FolderPath`` tuple populated only when
                         ``action == MOVE``.
        display_path:    Human-readable path string joined with the narrow
                         arrow separator (e.g. ``"Projects > Web"``).
                         Populated when ``action == MOVE``.
        options:         Tuple of folder/subfolder names to present to the user
                         at the next step.  Empty when no further selection is
                         needed.
        selected_root:   The PARA root chosen at ``AWAIT_CATEGORY``; carried
                         forward through folder and subfolder states so the
                         router can build the full ``FolderPath``.
        selected_folder: The folder name chosen at ``AWAIT_FOLDER``; carried
                         forward to the subfolder state.
        help_requested:  ``True`` when the user pressed '?'; the state is
                         unchanged (``AWAIT_CATEGORY``) and the UI should render
                         its help overlay.
    """

    model_config = ConfigDict(frozen=True)

    state: RouterState
    action: RouteAction | None = None
    folder_path: FolderPath | None = None
    display_path: str | None = None
    options: tuple[str, ...] = Field(default_factory=tuple)
    selected_root: str | None = None
    selected_folder: str | None = None
    help_requested: bool = False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _sort_general_first(names: tuple[str, ...]) -> tuple[str, ...]:
    """Return *names* sorted so ``"General"`` appears first, others follow stably.

    Args:
        names: Folder or subfolder names in any order.

    Returns:
        A new tuple with ``"General"`` first (if present), followed by all
        remaining names in their original relative order.
    """
    general = [n for n in names if n == "General"]
    others = [n for n in names if n != "General"]
    return tuple(general + others)


class Router:
    """PARA routing state machine.

    Consumes the current state plus an input event and returns a
    :class:`RouteResult` describing the next state and any action to take.

    The ``Router`` is **stateless between calls** — all context required to
    compute the next state is passed explicitly as arguments (current
    ``RouteResult`` or a ``Note`` instance).  This makes the transitions
    deterministic and easy to test without any shared mutable state.

    Args:
        repo:          The :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`
                       implementation used to issue ``ensure_folder`` and
                       ``move_note`` calls.
        config:        The full :class:`~notes_os.config.SorterConfig` supplying
                       the archive base folder name.
        year_provider: Zero-argument callable that returns the current year as
                       an ``int``.  Defaults to ``lambda: datetime.now().year``.
                       Inject a fixed-year lambda in tests for determinism.
    """

    def __init__(
        self,
        repo: NotesRepositoryProtocol,
        config: SorterConfig,
        year_provider: Callable[[], int] | None = None,
    ) -> None:
        """Initialise the router.

        Args:
            repo:          AppleScript repository protocol implementation.
            config:        Frozen application configuration.
            year_provider: Callable returning the year for archive auto-year.
                           Defaults to the current calendar year from
                           ``datetime.datetime.now().year``.
        """
        self._repo = repo
        self._config = config
        self._year_provider: Callable[[], int] = (
            year_provider if year_provider is not None else lambda: datetime.datetime.now().year
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _subfolders_for_folder(
        self, structure: ParaStructure, root: str, folder: str
    ) -> tuple[str, ...]:
        """Return the sub-subfolders for a ``(root, folder)`` pair.

        In M1 the ``ParaStructure`` is 2-level deep (root → subfolders).  A
        3-level hierarchy is represented by encoding the parent path as a key
        ``"root/folder"`` in the ``subfolders`` dict.  If no such key exists,
        the folder is treated as a leaf (no sub-subfolders).

        Args:
            structure: The PARA structure snapshot.
            root:      The PARA root folder name.
            folder:    The folder name immediately under *root*.

        Returns:
            A tuple of sub-subfolder names, or an empty tuple if none exist.
        """
        key = f"{root}/{folder}"
        return structure.subfolders.get(key, ())

    def _do_move(
        self,
        note: Note,
        path: FolderPath,
        display: str,
    ) -> RouteResult:
        """Call ``ensure_folder`` then ``move_note`` and return SHOW_NOTE + MOVE.

        Args:
            note:    The note to move.
            path:    The resolved destination ``FolderPath``.
            display: The human-readable display path string.

        Returns:
            A ``RouteResult`` with ``state=SHOW_NOTE``, ``action=MOVE``, and
            the resolved path/display info.
        """
        self._repo.ensure_folder(path)
        self._repo.move_note(note.id, path)
        logger.info("Moved note %r to %s", note.id, display)
        return RouteResult(
            state=RouterState.SHOW_NOTE,
            action=RouteAction.MOVE,
            folder_path=path,
            display_path=display,
        )

    # ------------------------------------------------------------------
    # Public transition entrypoints
    # ------------------------------------------------------------------

    def handle_category(self, key: str, note: Note) -> RouteResult:
        """Process a keystroke at the ``AWAIT_CATEGORY`` state.

        Handles the initial PARA category selection keys.  Case-insensitive.

        - **P/p** → ``AWAIT_FOLDER`` (Projects root)
        - **A/a** → ``AWAIT_FOLDER`` (Areas root) — or immediate MOVE if Areas
          has no sub-folders
        - **R/r** → ``AWAIT_FOLDER`` (Resources root) — or immediate MOVE if
          Resources has no sub-folders
        - **X/x** → auto-archive to ``(archive_base, current_year)`` (ROUT-02)
        - **S/s** → skip note (ROUT-07)
        - **?**   → help requested (state unchanged, ``help_requested=True``)
        - *other* → no-op (state unchanged, ``action=NONE``)

        Args:
            key:  The keystroke string (typically a single character).
            note: The note currently being sorted.

        Returns:
            A :class:`RouteResult` describing the outcome of the transition.
        """
        structure = self._repo.get_para_structure()
        lower_key = key.lower()

        # --- Archive auto-year (ROUT-02) ---
        if lower_key == "x":
            archive_base = self._config.archive.base_folder
            year = str(self._year_provider())
            path: FolderPath = (archive_base, year)
            display = _DISPLAY_SEP.join((archive_base, year))
            return self._do_move(note, path, display)

        # --- Skip (ROUT-07) ---
        if lower_key == "s":
            return RouteResult(state=RouterState.SHOW_NOTE, action=RouteAction.SKIP)

        # --- Help (ROUT-07 invalid-safe) ---
        if key == "?":
            return RouteResult(
                state=RouterState.AWAIT_CATEGORY,
                help_requested=True,
            )

        # --- PARA category keys (ROUT-01) ---
        root_map = {"p": "Projects", "a": "Areas", "r": "Resources"}
        if lower_key not in root_map:
            # Unrecognised key — no-op (ROUT-07, T-04-03 mitigation)
            return RouteResult(state=RouterState.AWAIT_CATEGORY, action=RouteAction.NONE)

        root = root_map[lower_key]

        # Compute the folder options for this root (General first per ROUT-05)
        raw_folders = structure.subfolders_for(root)
        folder_options = _sort_general_first(raw_folders)

        # If the root has no sub-folders, move directly to the root (ROUT-05)
        if not folder_options:
            path = (root,)
            display = root
            return self._do_move(note, path, display)

        return RouteResult(
            state=RouterState.AWAIT_FOLDER,
            selected_root=root,
            options=folder_options,
        )

    def handle_folder(self, index: int, prev: RouteResult, note: Note) -> RouteResult:
        """Process a 1-based numeric folder selection at the ``AWAIT_FOLDER`` state.

        Validates *index* against the available ``prev.options``.  Out-of-range
        or zero indices are no-ops (state unchanged, ROUT-07).

        If the selected folder has sub-subfolders (``"root/folder"`` key in the
        structure), transitions to ``AWAIT_SUBFOLDER`` with General-first ordering.
        Otherwise performs an immediate move to ``(root, folder)`` (ROUT-05).

        Args:
            index: 1-based selection (``1`` selects ``prev.options[0]``).
            prev:  The ``RouteResult`` from the preceding ``handle_category``
                   call; carries ``selected_root`` and ``options``.
            note:  The note currently being sorted.

        Returns:
            A :class:`RouteResult` with the next state and context.
        """
        options = prev.options
        # Validate 1-based index
        if index < 1 or index > len(options):
            return RouteResult(
                state=RouterState.AWAIT_FOLDER,
                selected_root=prev.selected_root,
                options=options,
            )

        root = prev.selected_root or ""
        folder = options[index - 1]

        # Check for sub-subfolders
        structure = self._repo.get_para_structure()
        sub_options = self._subfolders_for_folder(structure, root, folder)
        sub_options = _sort_general_first(sub_options)

        if sub_options:
            # Has sub-subfolders — go to AWAIT_SUBFOLDER
            return RouteResult(
                state=RouterState.AWAIT_SUBFOLDER,
                selected_root=root,
                selected_folder=folder,
                options=sub_options,
            )

        # No sub-subfolders — move immediately (ROUT-05)
        path = (root, folder)
        display = _DISPLAY_SEP.join(path)
        return self._do_move(note, path, display)

    def handle_subfolder(self, index: int, prev: RouteResult, note: Note) -> RouteResult:
        """Process a 1-based numeric subfolder selection at the ``AWAIT_SUBFOLDER`` state.

        Validates *index* against ``prev.options``.  Out-of-range or zero indices
        are no-ops (ROUT-07).  Valid selection issues ``ensure_folder`` then
        ``move_note`` to the 3-level path ``(root, folder, subfolder)``.

        Args:
            index: 1-based selection (``1`` selects ``prev.options[0]``).
            prev:  The ``RouteResult`` from the preceding ``handle_folder`` call;
                   carries ``selected_root``, ``selected_folder``, and ``options``.
            note:  The note currently being sorted.

        Returns:
            A :class:`RouteResult` with ``state=SHOW_NOTE`` and ``action=MOVE``
            on success, or an unchanged ``AWAIT_SUBFOLDER`` result on invalid input.
        """
        options = prev.options
        if index < 1 or index > len(options):
            return RouteResult(
                state=RouterState.AWAIT_SUBFOLDER,
                selected_root=prev.selected_root,
                selected_folder=prev.selected_folder,
                options=options,
            )

        root = prev.selected_root or ""
        folder = prev.selected_folder or ""
        subfolder = options[index - 1]

        path = (root, folder, subfolder)
        display = _DISPLAY_SEP.join(path)
        return self._do_move(note, path, display)

    def handle_back(self, current_state: RouterState, prev: RouteResult) -> RouteResult:
        """Handle a [B] back event to navigate one level up in the routing flow.

        Back semantics (ROUT-06):

        - ``AWAIT_SUBFOLDER`` → ``AWAIT_FOLDER`` (re-populate folder options for the
          same root)
        - ``AWAIT_FOLDER``    → ``AWAIT_CATEGORY``

        Pressing back at any other state is a no-op (returns the current state as
        ``AWAIT_CATEGORY`` for safety).

        Args:
            current_state: The state the UI is currently in (used to determine
                           where to go back to).
            prev:          The previous ``RouteResult`` carrying context (selected
                           root/folder and options).

        Returns:
            A :class:`RouteResult` with the one-level-up state populated.
        """
        if current_state == RouterState.AWAIT_SUBFOLDER:
            # Go back to AWAIT_FOLDER — recompute folder options for the same root
            root = prev.selected_root or ""
            structure = self._repo.get_para_structure()
            raw_folders = structure.subfolders_for(root)
            folder_options = _sort_general_first(raw_folders)
            return RouteResult(
                state=RouterState.AWAIT_FOLDER,
                selected_root=root,
                options=folder_options,
            )

        if current_state == RouterState.AWAIT_FOLDER:
            return RouteResult(state=RouterState.AWAIT_CATEGORY)

        # No-op for any other state
        return RouteResult(state=RouterState.AWAIT_CATEGORY)
