"""HomeScreen — NotesOS splash, keyboard menu, and live status panel.

This is the root screen pushed by :class:`~notes_os.app.NotesOSApp` when the
TUI mounts.  It displays:

1. **Splash panel** (``#splash``): ASCII "NotesOS" logo plus the resolved
   package version (``importlib.metadata``, with the same
   ``PackageNotFoundError → "0.0.0+unknown"`` fallback as ``main()``).

2. **Menu** (``#menu``): A keyboard-navigable :class:`~textual.widgets.OptionList`
   with two items — "Sort Inbox" and "Quit".  Supports ↑/↓ to move the
   highlight and Enter to activate (TUI-05 nav base).

3. **Status panel** (``#status``): Three live indicators.  ``on_mount`` sets
   placeholder text immediately and kicks off a background thread worker
   (``_load_status``) to fetch real values without blocking the event loop:

   - *Inbox* — ``len(self.app.repo.get_inbox_notes())`` notes waiting.
   - *Last backup* — newest from ``self.app.backup_manager.list()``.  Shows
     ``"never"`` when no backups exist; otherwise formats
     ``backup.timestamp.strftime("%Y-%m-%d %H:%M:%S")``.
   - *Backend* — the HONEST M1 label ``"sort-only (M1)"``; NO fabricated LLM
     backend (T-06-02 mitigation).  Set synchronously in ``on_mount`` (no I/O
     needed).

Navigation bindings on HomeScreen (TUI-05):
    - ``?`` → contextual help overlay (``action_help`` — overrides the global
      action at the screen level to show a home-specific key legend).
    - ↑/↓ and Enter are natively handled by :class:`~textual.widgets.OptionList`.
    - Esc has nothing to back out to (root screen) — it is treated as a no-op.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets._option_list import Option


if TYPE_CHECKING:
    from textual.app import ComposeResult

    from notes_os.app import NotesOSApp


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MENU_SORT = "sort"
_MENU_QUIT = "quit"

_ASCII_LOGO = r"""
 _   _       _            ___  ____
| \ | | ___ | |_ ___  ___|/ _ \/ ___|
|  \| |/ _ \| __/ _ \/ __| | | \___ \
| |\  | (_) | ||  __/\__ \ |_| |___) |
|_| \_|\___/ \__\___||___/\___/|____/
""".strip()

_HELP_TEXT = """\
Key legend — Home Screen
  ↑ / ↓   Move menu selection
  Enter    Activate selected item
  Q        Quit NotesOS
  ?        Show this help
"""


class HomeScreen(Screen[None]):
    """Root TUI screen: ASCII splash, keyboard menu, and live status panel.

    All live data is sourced from ``self.app.repo`` and
    ``self.app.backup_manager`` so injected test doubles drive the values
    deterministically without any AppleScript (SC1 provable via Pilot tests).

    ``on_mount`` sets placeholder text immediately and delegates all blocking
    I/O to :meth:`_load_status` (a ``@work(thread=True)`` worker) so Textual
    can paint the screen before the first ``osascript`` call completes.

    Bindings declared here are SCREEN-LOCAL and supplement the global Q/? bindings
    declared on :class:`~notes_os.app.NotesOSApp`.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "noop", "Back", show=False),
    ]

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Lay out the splash, menu, and status widgets.

        Yields:
            Header, splash Static, version Static, menu OptionList, status
            Statics, and Footer.
        """
        yield Header(show_clock=False)

        version = _resolve_version()

        yield Static(_ASCII_LOGO, id="splash")
        yield Static(f"v{version}", id="version-label")

        yield OptionList(
            Option("Sort Inbox", id=_MENU_SORT),
            Option("Quit", id=_MENU_QUIT),
            id="menu",
        )

        yield Static("Inbox: loading…", id="status-inbox")
        yield Static("Last backup: loading…", id="status-backup")
        yield Static("Backend: sort-only (M1)", id="status-backend")

        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Set placeholder status text and kick off the background status loader.

        The backend label needs no I/O and is set synchronously.  Inbox count
        and last-backup timestamp are fetched off the event-loop thread by
        :meth:`_load_status` so Textual can paint the screen immediately.
        """
        # Backend label — honest M1 string; NOT fabricated LLM backend (T-06-02)
        self.query_one("#status-backend", Static).update("Backend: sort-only (M1)")

        # Kick off non-blocking background worker for I/O-bound status fields.
        self._load_status()

    @work(thread=True, exclusive=True)
    def _load_status(self) -> None:
        """Fetch inbox count and last-backup timestamp off the event-loop thread.

        Runs in a background thread so the blocking ``osascript`` subprocess
        (inside ``get_inbox_notes()``) does not stall Textual's event loop
        before first paint.  Each result is marshalled back to the main thread
        via ``self.app.call_from_thread`` before updating the widgets.

        Preserves the same fallback strings as the previous synchronous
        implementation (``"Inbox: (unavailable)"`` and
        ``"Last backup: (unavailable)"`` / ``"Last backup: never"``).
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]

        # Inbox count
        inbox_count = 0
        try:
            notes = app.repo.get_inbox_notes()
            inbox_count = len(notes)
            inbox_text = f"Inbox: {inbox_count} note(s)"
        except Exception:
            logger.warning("HomeScreen: failed to fetch inbox count", exc_info=True)
            inbox_text = "Inbox: (unavailable)"

        self.app.call_from_thread(
            self.query_one("#status-inbox", Static).update,
            inbox_text,
        )

        # Last backup
        try:
            backups = app.backup_manager.list()
            if backups:
                ts_str = backups[0].timestamp.strftime("%Y-%m-%d %H:%M:%S")
                backup_text = f"Last backup: {ts_str}"
            else:
                backup_text = "Last backup: never"
        except Exception:
            logger.warning("HomeScreen: failed to fetch backup list", exc_info=True)
            backup_text = "Last backup: (unavailable)"

        self.app.call_from_thread(
            self.query_one("#status-backup", Static).update,
            backup_text,
        )

        logger.debug("HomeScreen _load_status complete — inbox_count=%d", inbox_count)

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        """Handle menu item activation.

        "Sort Inbox" is a placeholder seam for Phase 06-02 (SortScreen does not
        exist yet); it logs the action and is a no-op in this plan.  "Quit"
        calls the global quit action.

        Args:
            event: The :class:`~textual.widgets.OptionList.OptionSelected`
                message carrying the activated option.
        """
        option_id = event.option.id
        if option_id == _MENU_SORT:
            self.action_sort()
        elif option_id == _MENU_QUIT:
            self.app.exit()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_sort(self) -> None:
        """Push the SortScreen to begin inbox triage (Phase 06-02).

        Pushes ``"sort"`` from the app's SCREENS registry, which resolves to
        :class:`~notes_os.screens.sort.SortScreen`.  The SortScreen inherits
        the app's injected repo (already wrapped in BackingUpNotesRepository)
        so backup-then-move holds for every move the user makes (SC2).
        """
        self.app.push_screen("sort")

    def action_noop(self) -> None:
        """No-op handler for Esc on the root screen.

        The HomeScreen is the root; there is nothing to back out to.  Esc is
        silently swallowed here.  Phase 06-04 may replace this with a
        quit-confirm dialog.
        """

    def action_help(self) -> None:
        """Show a contextual help overlay for the home screen.

        Displays the key legend as a temporary notification so the user can see
        available bindings without leaving the home screen.
        """
        self.notify(_HELP_TEXT, title="Help", timeout=6.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_version() -> str:
    """Resolve the package version string.

    Returns:
        The version string from :func:`importlib.metadata.version`, or
        ``"0.0.0+unknown"`` when the package is not installed.
    """
    try:
        return importlib.metadata.version("para-notes-sorter")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0+unknown"
