"""NotesOS Textual application entry point.

``NotesOSApp`` is the root :class:`~textual.app.App` subclass that launches the
full keyboard-driven TUI.  It owns:

- The **dependency-injection seam**: ``config``, ``repo``, and ``backup_manager``
  are all optional constructor parameters.  When any parameter is ``None`` the
  production dependency is built via deferred local imports so that
  ``import notes_os.app`` NEVER pulls in AppleScript machinery (no osascript
  imported at module load time).

- The **screen registry**: ``SCREENS = {"home": HomeScreen}`` registered once;
  ``on_mount`` pushes ``"home"`` to start the TUI.

- **Global navigation bindings** (TUI-05 base — applied to all screens):
    - ``Q`` → quit (``action_quit``)
    - ``?`` → help (``action_help`` — per-screen help overlay)

  Per-screen bindings (``↑`` / ``↓`` move highlight, ``Enter`` select,
  ``Esc``/``B`` back one level) are declared on the individual screen classes,
  not here, so the set of global bindings stays minimal.  Future screens in
  06-02/06-03/06-04 MUST follow this same convention: add screen-local bindings
  to the screen class, not to ``NotesOSApp``.

- **Quit-confirm guard (TUI-05 / T-06-11)**: when a sort session is in progress
  (``sort_in_progress`` is ``True``), ``Q`` presents a ``ConfirmQuitModal``
  before exiting.  On Home/idle ``Q`` exits immediately.

``main()`` is the ``notes`` CLI entry point (``notes_os.app:main`` in
``pyproject.toml``).  It configures logging, resolves the package version, loads
the config (turning an invalid config file into a friendly message + exit code 1
rather than a traceback), and calls ``NotesOSApp(config=config).run()`` to start
the event loop.
"""

from __future__ import annotations

import importlib.metadata
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from notes_os.screens.home import HomeScreen
from notes_os.screens.sort import SortScreen
from notes_os.screens.task_extract import TaskExtractScreen


if TYPE_CHECKING:
    from notes_os.backup import BackupManager
    from notes_os.config import SorterConfig
    from notes_os.sorter.notes import NotesRepositoryProtocol


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS path (relative to this file so Textual resolves it correctly)
# ---------------------------------------------------------------------------

_CSS_PATH: Path = Path(__file__).parent / "app.tcss"


# ---------------------------------------------------------------------------
# ConfirmQuitModal — shown by action_quit when a sort session is in progress
# ---------------------------------------------------------------------------


class ConfirmQuitModal(ModalScreen[bool]):
    """Minimal two-button confirm modal for guarding quit during a sort session.

    Presents a message and Yes / No buttons.  Dismissed with ``True`` (user
    confirmed quit) or ``False`` (user cancelled).  Does NOT include
    ``Header`` or ``Footer`` widgets — those raise ``NoMatches`` in modal
    context (TUI discovery from 06-03).

    Bindings:
        - ``Y`` / ``y`` → confirm quit (dismiss ``True``).
        - ``N`` / ``n`` → cancel (dismiss ``False``).
        - ``Escape`` → cancel (dismiss ``False``).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Yes, quit", show=True),
        Binding("n", "cancel", "No, stay", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        """Lay out the confirm message and Yes/No buttons.

        Yields:
            Label with the prompt message, two Buttons (Yes / No).
        """
        yield Label(
            "A sort session is in progress.\nQuit anyway? (Y / N)",
            id="confirm-quit-label",
        )
        yield Button("Yes — quit", id="confirm-quit-yes", variant="error")
        yield Button("No — stay", id="confirm-quit-no", variant="primary")

    def action_confirm(self) -> None:
        """Dismiss the modal with ``True`` — user chose to quit."""
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Dismiss the modal with ``False`` — user chose to stay."""
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Yes/No button clicks.

        Args:
            event: The :class:`~textual.widgets.Button.Pressed` event.
        """
        if event.button.id == "confirm-quit-yes":
            self.dismiss(True)
        elif event.button.id == "confirm-quit-no":
            self.dismiss(False)


# ---------------------------------------------------------------------------
# ResumePromptModal — shown by the "always ask" resume prompt (UX-03)
# ---------------------------------------------------------------------------

# Button ids and the prompt template (no magic strings).
_RESUME_YES_ID: str = "resume-yes"
_RESUME_NO_ID: str = "resume-no"
_RESUME_LABEL_ID: str = "resume-prompt-label"
_RESUME_PROMPT_TEMPLATE: str = (
    "A saved session was found.\nResume at note {position} of {total}, or start over?"
)


class ResumePromptModal(ModalScreen[bool]):
    """Two-button "Resume / Start over" prompt for the saved-session check (UX-03).

    Mirrors :class:`ConfirmQuitModal`: it presents a message plus two buttons and
    is dismissed with ``True`` (user chose to Resume) or ``False`` (user chose to
    Start over).  Does NOT include ``Header`` or ``Footer`` widgets — those raise
    ``NoMatches`` in modal context.

    The Wave-2 SortScreen (Plan 15-02) pushes this modal BY INSTANCE (it is not
    registered in :attr:`NotesOSApp.SCREENS`) with the saved ``index``/``total`` so
    the prompt can show the 1-based position the session would resume at.

    Bindings:
        - ``Y`` / ``y`` → Resume (dismiss ``True``).
        - ``N`` / ``n`` → Start over (dismiss ``False``).
        - ``Escape`` → Start over (dismiss ``False``).

    Args:
        index: The 0-based inbox index the session would resume at.  Shown to the
            user as the 1-based position ``index + 1``.
        total: The total number of notes in the saved inbox signature.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "resume", "Resume", show=True),
        Binding("n", "start_over", "Start over", show=True),
        Binding("escape", "start_over", "Start over", show=False),
    ]

    def __init__(self, index: int, total: int) -> None:
        """Store the saved position so :meth:`compose` can render the prompt.

        Args:
            index: The 0-based inbox index the session would resume at.
            total: The total number of notes in the saved inbox signature.
        """
        super().__init__()
        self._index = index
        self._total = total

    def compose(self) -> ComposeResult:
        """Lay out the resume prompt and Resume / Start over buttons.

        Yields:
            Label with the resume prompt (showing the 1-based position), then two
            Buttons (Resume / Start over).
        """
        yield Label(
            _RESUME_PROMPT_TEMPLATE.format(position=self._index + 1, total=self._total),
            id=_RESUME_LABEL_ID,
        )
        yield Button("Resume", id=_RESUME_YES_ID, variant="primary")
        yield Button("Start over", id=_RESUME_NO_ID, variant="warning")

    def action_resume(self) -> None:
        """Dismiss the modal with ``True`` — user chose to resume."""
        self.dismiss(True)

    def action_start_over(self) -> None:
        """Dismiss the modal with ``False`` — user chose to start over."""
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Resume / Start over button clicks.

        Args:
            event: The :class:`~textual.widgets.Button.Pressed` event.
        """
        if event.button.id == _RESUME_YES_ID:
            self.dismiss(True)
        elif event.button.id == _RESUME_NO_ID:
            self.dismiss(False)


class NotesOSApp(App[None]):
    """Root Textual application for NotesOS.

    Registers all screens and declares the global navigation bindings that
    apply throughout the TUI (Q quit, ? help).  Individual screens add their
    own local bindings (↑↓ move, Enter select, Esc back).

    Dependency-injection seam — mirrors ``build_default_controller(config)``
    in :mod:`notes_os.sorter.controller`:

    - When ``repo`` is ``None``, the production
      :class:`~notes_os.backup.BackingUpNotesRepository` wrapping an
      :class:`~notes_os.sorter.notes.AppleScriptNotesRepository` is built via
      deferred local imports, preserving the backup-then-move invariant (SC2,
      T-06-01 mitigation).
    - When ``repo`` is supplied (Pilot tests), it is used as-is — no
      AppleScript is imported.
    - ``backup_manager`` follows the same pattern: built from ``config.backup``
      when ``None``, or used as injected.

    Attributes:
        app_config: The frozen :class:`~notes_os.config.SorterConfig` driving
            this session.  Named ``app_config`` (not ``config``) to avoid
            shadowing the Textual :attr:`~textual.app.App.config` attribute.
        repo: The :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`
            implementation used for all inbox reads and writes.
        backup_manager: The :class:`~notes_os.backup.BackupManager` used for
            backup-status queries in the status panel (and for pre-write backups
            when the production repo is active).
        sort_in_progress: Set to ``True`` by :class:`~notes_os.screens.sort.SortScreen`
            when the first note is processed; reset to ``False`` at session finish.
            Drives the :meth:`action_quit` guard (TUI-05 / T-06-11 mitigation).

    Args:
        config: Optional :class:`~notes_os.config.SorterConfig`.  Built from
            the default ``~/.notes-os/config.toml`` when ``None``.
        repo: Optional :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`
            implementation.  When ``None``, the production AppleScript-backed
            repository is constructed.
        backup_manager: Optional :class:`~notes_os.backup.BackupManager`.
            When ``None``, constructed from ``config.backup``.
    """

    CSS_PATH = str(_CSS_PATH)

    SCREENS: ClassVar[dict[str, type]] = {  # type: ignore[assignment]
        "home": HomeScreen,
        "sort": SortScreen,
        "task_extract": TaskExtractScreen,
    }

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
    ]

    def __init__(
        self,
        config: SorterConfig | None = None,
        repo: NotesRepositoryProtocol | None = None,
        backup_manager: BackupManager | None = None,
    ) -> None:
        """Initialise the app, building production dependencies when not injected.

        Deferred imports for production-only classes ensure that
        ``import notes_os.app`` does not pull in AppleScript machinery
        (``osascript`` is never imported at module load time).

        Args:
            config: Optional frozen :class:`~notes_os.config.SorterConfig`.
                When ``None``, :func:`~notes_os.config.load_config` is called to
                read ``~/.notes-os/config.toml`` or use built-in defaults.
            repo: Optional :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`
                implementation.  When ``None``, the production
                :class:`~notes_os.backup.BackingUpNotesRepository` wrapping
                :class:`~notes_os.sorter.notes.AppleScriptNotesRepository` is
                built from ``config.bridge`` and ``config.backup``.
            backup_manager: Optional :class:`~notes_os.backup.BackupManager`.
                When ``None``, constructed from ``config.backup``.  Shared between
                the repo (pre-write backups) and the status panel (last-backup
                display).
        """
        super().__init__()

        if config is None:
            from notes_os.config import load_config  # deferred — avoids home-dir I/O at import

            config = load_config()

        self.app_config: SorterConfig = config

        if backup_manager is None:
            from notes_os.backup import BackupManager as _BackupManager  # deferred

            backup_manager = _BackupManager(config.backup)

        self.backup_manager: BackupManager = backup_manager

        if repo is None:
            from notes_os.backup import (
                BackingUpNotesRepository,
            )  # deferred — avoids AppleScript import
            from notes_os.sorter.notes import AppleScriptNotesRepository  # deferred

            inner = AppleScriptNotesRepository(config.bridge)
            repo = BackingUpNotesRepository(inner, backup_manager, config.backup)

        self.repo: NotesRepositoryProtocol = repo

        # Quit-confirm guard flag — set True by SortScreen on first record;
        # reset to False at _finish().  Drives action_quit (TUI-05 / T-06-11).
        self.sort_in_progress: bool = False

        logger.debug(
            "NotesOSApp initialised — repo=%s, backup_dir=%s",
            type(self.repo).__name__,
            self.app_config.backup.backup_dir,
        )

    def on_mount(self) -> None:
        """Push the HomeScreen when the app mounts.

        The HomeScreen is the root screen of the TUI.  All other navigation
        (SortScreen, HelpOverlay, ConfirmQuit) is pushed on top of it by
        subsequent actions.
        """
        self.push_screen("home")

    async def action_quit(self) -> None:
        """Quit the app, with a confirm guard when a sort session is in progress.

        TUI-05 / T-06-11 mitigation: a bare ``Q`` quits immediately from
        Home/idle.  When ``self.sort_in_progress`` is ``True``, a
        :class:`ConfirmQuitModal` is pushed first.  If the user confirms
        (dismisses with ``True``), :meth:`~textual.app.App.exit` is called.
        If the user cancels (dismisses with ``False``), the app continues.

        Overrides ``App.action_quit`` (which is also ``async``) to inject the
        session-guard logic before delegating to ``self.exit()``.
        """
        if not self.sort_in_progress:
            logger.debug("action_quit: no session in progress — exiting immediately")
            self.exit()
            return

        logger.debug("action_quit: sort session in progress — showing confirm modal")

        def _on_confirm(confirmed: bool | None) -> None:
            """Handle the ConfirmQuitModal result.

            Args:
                confirmed: ``True`` when the user chose to quit; ``False`` or
                    ``None`` to continue the session.
            """
            if confirmed:
                logger.info("action_quit: user confirmed quit during active session")
                self.exit()
            else:
                logger.debug("action_quit: user cancelled quit — resuming session")

        self.push_screen(ConfirmQuitModal(), _on_confirm)

    def action_help(self) -> None:
        """Dispatch help request to the active screen.

        The active screen is responsible for rendering its own contextual help
        (e.g. a key-legend overlay).  This global action simply calls through
        so the binding appears in the footer but the actual UI is per-screen.
        """
        action_fn = getattr(self.screen, "action_help", None)
        if callable(action_fn):
            action_fn()

    def compose(self) -> ComposeResult:
        """Yield no widgets — the HomeScreen is pushed in on_mount.

        Yields:
            Nothing: the app shell has no persistent widgets of its own.
        """
        return
        yield  # pragma: no cover — unreachable; makes the generator valid


def main() -> None:
    """Entry point for the ``notes`` console command.

    Configures basic logging, resolves the package version via
    ``importlib.metadata`` (falls back to ``"0.0.0+unknown"`` when the package
    is not installed or the VCS tag is absent), and launches the full Textual
    TUI via :class:`NotesOSApp`.

    The ``notes = notes_os.app:main`` entry point in ``pyproject.toml`` is
    unchanged from Phase 1 — no subcommands are added in Phase 6.

    Configuration is loaded here (rather than lazily inside ``NotesOSApp``) so a
    malformed ``~/.notes-os/config.toml`` surfaces as a single clear,
    actionable log line and exit code 1 — never a raw Python traceback. Both
    failure modes are handled: :class:`~notes_os.config.ConfigError` (invalid
    TOML syntax) and :class:`pydantic.ValidationError` (well-formed TOML whose
    values fail schema validation).

    Returns:
        None
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        version = importlib.metadata.version("para-notes-sorter")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0+unknown"

    # Load config up front so a bad config file produces a friendly message,
    # not a traceback from deep inside NotesOSApp.__init__ (deferred import keeps
    # AppleScript machinery out of module load — see class docstring).
    from pydantic import ValidationError

    from notes_os.config import ConfigError, load_config

    try:
        config = load_config()
    except (ConfigError, ValidationError) as exc:
        logger.error(
            "Could not start NotesOS — your configuration is invalid:\n%s\n"
            "Fix the issue in ~/.notes-os/config.toml (or delete the file to use "
            "built-in defaults) and try again.",
            exc,
        )
        sys.exit(1)

    logger.info("NotesOS %s — launching TUI.", version)
    NotesOSApp(config=config).run()
