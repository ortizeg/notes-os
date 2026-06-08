"""SortScreen — inbox triage flow as a Textual screen.

``SortScreen`` drives the UI-agnostic :class:`~notes_os.sorter.router.Router`
DIRECTLY via Textual key events.  Each keystroke calls
:meth:`~notes_os.sorter.router.Router.handle_category`,
:meth:`~notes_os.sorter.router.Router.handle_folder`,
:meth:`~notes_os.sorter.router.Router.handle_subfolder`, or
:meth:`~notes_os.sorter.router.Router.handle_back` and the screen renders the
returned :class:`~notes_os.sorter.router.RouteResult`.

ARCHITECTURE NOTE: The Phase-4 ``SortController.run()`` is a SYNCHRONOUS
readchar loop and Textual is async/event-driven.  ``SortScreen`` does NOT
call ``SortController.run()`` — that would block the event loop.  Instead
it holds the per-note routing context (:attr:`_router_state`, :attr:`_prev`)
that the old controller held on its call stack and advances through Router
transitions as discrete, non-blocking event handlers.

State the screen holds (mirrors SortController call-stack context):
- ``_router`` — the stateless PARA state machine; stateless between calls.
- ``_session`` — accumulates moves/skips/errors for this screen visit.
- ``_notes`` — snapshot of the inbox taken at ``on_mount``.
- ``_index`` — pointer into ``_notes``; advances after each note is done.
- ``_router_state`` — current state-machine state (AWAIT_CATEGORY etc.).
- ``_prev`` — last ``RouteResult`` carrying folder/subfolder context.

TUI-05 navigation (consistent with HomeScreen):
- Global: Q quit (on NotesOSApp), ? help (dispatches to action_help here).
- Screen-local: Esc / B = back one router level; at AWAIT_CATEGORY, Esc/B
  pops back to HomeScreen (session-in-progress seam left for 06-04).

Threat mitigations:
- T-06-04 (tamper bypass backup): SortScreen uses ``self.app.repo`` which is
  the BackingUpNotesRepository from 06-01's DI seam — backup fires before move.
- T-06-05 (one bad note aborts session): every move wrapped in
  ``try/except NotesOSError`` → ``record_error`` + advance (mirrors T-04-10).
- T-06-06 (invalid keystroke causing bad state): Router returns no-op
  RouteResult for unknown keys / out-of-range indices; screen re-renders only.
- T-06-07 (blocking event loop): SortController.run() is never called here;
  Router transitions are discrete async event handlers.
- T-06-08 (extraction running when disabled): ``_after_move`` first line
  returns ``False`` immediately when ``task_extraction`` is ``False``; the
  disabled path never imports TaskExtractScreen or TaskWriter.
- T-06-10 (blocking event loop on extraction): ``push_screen`` with a
  dismiss callback is non-blocking; ``_advance`` fires via the callback after
  TaskExtractScreen is dismissed.

The ``_after_move`` seam (06-03):
  Called from :meth:`_handle_move` after ``_session.record_move``.  Returns
  ``True`` if it took ownership of the advance flow (modal pushed — advance
  will fire via :meth:`_on_tasks_resolved` callback on dismiss).  Returns
  ``False`` for the disabled path or when no tasks are found — caller
  (:meth:`_handle_move`) calls ``_advance()`` immediately in that case.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from notes_os.exceptions import NotesOSError
from notes_os.sorter.extractor import extract_tasks
from notes_os.sorter.router import RouteAction, Router, RouteResult, RouterState
from notes_os.sorter.session import SortSession


if TYPE_CHECKING:
    from collections.abc import Callable

    from textual import events
    from textual.app import ComposeResult

    from notes_os.app import NotesOSApp
    from notes_os.sorter.extractor import ExtractedTask
    from notes_os.sorter.models import Note


logger = logging.getLogger(__name__)

_HELP_TEXT = """\
Key legend - Sort Screen
  P        Projects (select sub-folder by number)
  A        Areas
  R        Resources
  X        Archive (auto-year)
  S        Skip this note
  1-9      Select numbered folder/subfolder
  Esc / B  Back one level (or return to Home)
  Q        Quit NotesOS
  ?        Show this help
"""

_CATEGORY_PROMPT = "[P]rojects  [A]reas  [R]esources  [X] archive  [S]kip  Esc/B back  ? help"


class SortScreen(Screen[None]):
    """Inbox triage screen that drives the Router via Textual key events.

    The screen renders the current note (title + preview), the available
    options at each router state (PARA keys / numbered folder list), and a
    progress indicator.  Keystrokes are translated into Router calls without
    any blocking loop — each key event is handled discretely and returns
    immediately so the Textual event loop stays responsive.

    All live data comes from ``self.app.repo`` (the backup-wrapped repository
    from the NotesOSApp DI seam) and ``self.app.app_config``.

    Args:
        year_provider: Optional zero-argument callable returning the current
            year as an int.  Injected in tests for determinism; defaults to
            ``None`` (Router uses ``datetime.now().year``).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", show=True),
        Binding("b", "back", "Back", show=False),
    ]

    def __init__(
        self,
        year_provider: Callable[[], int] | None = None,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 — mirrors Textual Screen signature
        classes: str | None = None,
    ) -> None:
        """Initialise SortScreen instance attributes.

        Router, session, notes snapshot, and navigation state are all
        initialised here as sentinel values and populated in ``on_mount``
        after the app is attached and ``self.app.repo`` is available.

        Args:
            year_provider: Optional fixed-year lambda for tests.
            name: Textual widget name (passed to super).
            id: Textual widget id (passed to super).
            classes: Textual CSS classes (passed to super).
        """
        super().__init__(name=name, id=id, classes=classes)
        self._year_provider = year_provider
        self._router: Router | None = None
        self._session: SortSession = SortSession()
        self._notes: list[Note] = []
        self._index: int = 0
        self._router_state: RouterState = RouterState.AWAIT_CATEGORY
        self._prev: RouteResult | None = None
        self._inbox_empty: bool = False

    def compose(self) -> ComposeResult:
        """Lay out the sort-screen widgets.

        Yields a Header, note-title Static, note-preview Static, prompt
        Static (PARA keys or numbered folder list), progress Static, and
        a Footer.

        Yields:
            Header, four Static content panels, Footer.
        """
        yield Header(show_clock=False)
        yield Static("", id="note-title")
        yield Static("", id="note-preview")
        yield Static("", id="prompt")
        yield Static("", id="progress")
        yield Footer()

    def on_mount(self) -> None:
        """Build Router + Session, snapshot inbox, render first note.

        Accesses ``self.app.repo`` and ``self.app.app_config`` (always
        present via the NotesOSApp DI seam from 06-01).  If the inbox is
        empty, renders the empty-inbox state and returns early.
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]

        self._router = Router(
            repo=app.repo,
            config=app.app_config,
            year_provider=self._year_provider,
        )
        self._session = SortSession()
        self._notes = app.repo.get_inbox_notes()
        self._index = 0
        self._router_state = RouterState.AWAIT_CATEGORY
        self._prev = None

        if not self._notes:
            self._inbox_empty = True
            self._render_empty_inbox()
            return

        self._render_current_note()

    def on_key(self, event: events.Key) -> None:
        """Translate Textual key events into Router transitions.

        Dispatches based on the current ``_router_state``:
        - ``AWAIT_CATEGORY``: category keys (P/A/R/X/S/?), or Esc/B back.
        - ``AWAIT_FOLDER``: numeric keys 1-9, or Esc/B back.
        - ``AWAIT_SUBFOLDER``: numeric keys 1-9, or Esc/B back.

        Unknown keys are silently ignored (re-renders current state).
        ROUT-07 — Router also no-ops on invalid keys.

        Args:
            event: The Textual :class:`~textual.events.Key` event.
        """
        if self._inbox_empty:
            if event.key in ("escape", "b"):
                self.app.pop_screen()
            return

        key = event.character or event.key

        if self._router_state == RouterState.AWAIT_CATEGORY:
            self._handle_category_key(key)
        elif self._router_state == RouterState.AWAIT_FOLDER:
            self._handle_folder_or_subfolder_key(key, folder=True)
        elif self._router_state == RouterState.AWAIT_SUBFOLDER:
            self._handle_folder_or_subfolder_key(key, folder=False)

    def _handle_category_key(self, key: str) -> None:
        """Handle a keystroke at AWAIT_CATEGORY state.

        Passes the key to ``router.handle_category``.  On:
        - ``help_requested=True`` → show the help overlay, stay.
        - ``action==SKIP`` → record skip, advance to next note.
        - ``action==MOVE`` → record move, advance to next note.
        - ``state==AWAIT_FOLDER`` → store ``_prev``, update state, re-render.
        - No-op/unknown → re-render (ROUT-07).

        Args:
            key: Single-character keystroke string.
        """
        if self._router is None:
            return
        note = self._current_note()
        if note is None:
            return

        result = self._router.handle_category(key, note)

        if result.help_requested:
            self._show_help()
            return

        if result.action == RouteAction.SKIP:
            self._session.record_skip(note.id)
            logger.debug("Note %r skipped", note.id)
            # Signal to the app that a session is in progress (T-06-11 mitigation)
            self.app.sort_in_progress = True  # type: ignore[attr-defined]
            self._advance()
            return

        if result.action == RouteAction.MOVE and result.folder_path is not None:
            self._handle_move(note, result)
            return

        if result.state == RouterState.AWAIT_FOLDER:
            self._prev = result
            self._router_state = RouterState.AWAIT_FOLDER
            self._render_current_note()
            return

        logger.debug("SortScreen: no-op key %r at AWAIT_CATEGORY", key)

    def _handle_folder_or_subfolder_key(self, key: str, *, folder: bool) -> None:
        """Handle a numeric or Esc/B keystroke at AWAIT_FOLDER / AWAIT_SUBFOLDER.

        Numeric keys 1-9 call ``handle_folder`` or ``handle_subfolder`` with
        the 1-based index.  Out-of-range indices are no-ops (ROUT-07).

        Args:
            key: Keystroke string (e.g. ``"1"``, ``"escape"``).
            folder: ``True`` when in AWAIT_FOLDER; ``False`` for AWAIT_SUBFOLDER.
        """
        if self._router is None or self._prev is None:
            return

        note = self._current_note()
        if note is None:
            return

        if key.isdigit() and key != "0":
            index = int(key)
            if folder:
                result = self._router.handle_folder(index, self._prev, note)
            else:
                result = self._router.handle_subfolder(index, self._prev, note)

            if result.action == RouteAction.MOVE and result.folder_path is not None:
                self._handle_move(note, result)
                return

            if result.state == RouterState.AWAIT_SUBFOLDER:
                self._prev = result
                self._router_state = RouterState.AWAIT_SUBFOLDER
                self._render_current_note()
                return

            if result.state == RouterState.AWAIT_FOLDER:
                self._prev = result
                self._render_current_note()
                return

            self._render_current_note()
            return

        logger.debug(
            "SortScreen: no-op key %r at state %s",
            key,
            self._router_state.value,
        )

    def action_back(self) -> None:
        """Handle Esc / B: back one router level.

        - At AWAIT_SUBFOLDER → AWAIT_FOLDER (re-render folder options).
        - At AWAIT_FOLDER → AWAIT_CATEGORY (re-render PARA prompt).
        - At AWAIT_CATEGORY → pop_screen back to HomeScreen.
          If the session has recorded any moves/skips, this is the
          "session in progress" boundary seam — 06-04 will add a confirm
          dialog here.  For now we pop directly.
        """
        if self._inbox_empty:
            self.app.pop_screen()
            return

        if self._router_state == RouterState.AWAIT_CATEGORY:
            logger.info(
                "SortScreen: leaving with session=%s/%s/%s (moves/skips/errors)",
                self._session.moved,
                self._session.skipped,
                self._session.errors,
            )
            self.app.pop_screen()
            return

        if self._router is None or self._prev is None:
            self.app.pop_screen()
            return

        back_result = self._router.handle_back(self._router_state, self._prev)
        self._prev = back_result
        self._router_state = back_result.state
        self._render_current_note()

    def action_help(self) -> None:
        """Show the sort-screen PARA key legend as a temporary notification."""
        self._show_help()

    def _show_help(self) -> None:
        """Display the help overlay as a Textual notification."""
        self.notify(_HELP_TEXT, title="Sort Help", timeout=8.0)

    def _handle_move(self, note: Note, result: RouteResult) -> None:
        """Record a successful move, then advance (or defer advance to modal).

        Wraps the move in ``try/except NotesOSError`` so one failure does NOT
        abort the session (T-06-05 mitigation, mirrors T-04-10 in controller).

        After recording, calls :meth:`_after_move` which returns ``True`` when
        it pushed the ``TaskExtractScreen`` modal and will call ``_advance``
        via the dismiss callback.  On ``False`` (disabled path or no tasks),
        ``_advance`` is called immediately here.

        When an error occurs, advance is always immediate (no modal on error).

        Args:
            note: The note that was just moved.
            result: The ``RouteResult`` with ``action==MOVE`` and
                ``folder_path`` populated.
        """
        extraction_deferred = False
        try:
            if result.folder_path is not None:
                self._session.record_move(note.id, result.folder_path)
                logger.debug("Note %r moved to %s", note.id, result.display_path)
                # Signal to the app that a session is in progress (T-06-11 mitigation)
                self.app.sort_in_progress = True  # type: ignore[attr-defined]
                extraction_deferred = self._after_move(note)
        except NotesOSError as exc:
            self._session.record_error(note.id, str(exc))
            logger.warning("SortScreen: error moving note %r: %s", note.id, exc)
        if not extraction_deferred:
            self._advance()

    def _after_move(self, note: Note) -> bool:
        """Post-move hook: optionally show TaskExtractScreen, gated on config.

        SC1 / T-06-08 gate — FIRST LINE must be this check.  When
        ``task_extraction`` is ``False`` (M1 default) the method returns
        ``False`` immediately with zero side effects — no extractor, no writer,
        no screen access.  This keeps the disabled path byte-identical to 06-02.

        On the enabled path:
        1. Runs ``extract_tasks(note.preview)`` — pure, fast, non-blocking.
        2. If no tasks found, returns ``False`` (advance happens immediately).
        3. If tasks found, pushes ``TaskExtractScreen`` as a modal with a
           dismiss callback (:meth:`_on_tasks_resolved`).  Returns ``True`` so
           :meth:`_handle_move` does NOT call ``_advance`` immediately — the
           callback will call it after the user resolves the modal.

        Args:
            note: The note that was just moved.

        Returns:
            ``True`` when TaskExtractScreen was pushed (advance deferred to
            :meth:`_on_tasks_resolved`); ``False`` when advance should happen
            immediately (disabled, no tasks, or no preview).
        """
        # SC1 gate — must be first (T-06-08 mitigation)
        app: NotesOSApp = self.app  # type: ignore[assignment]
        if not app.app_config.features.task_extraction:
            return False

        tasks: list[ExtractedTask] = extract_tasks(note.preview or "")
        if not tasks:
            logger.debug("_after_move: no tasks found in note %r", note.id)
            return False

        # Lazy import — avoids cost on the disabled path
        from notes_os.sorter.extractor import TaskWriter

        writer = TaskWriter(app.app_config.features.extracted_tasks_dir)
        from notes_os.screens.task_extract import TaskExtractScreen

        logger.debug(
            "_after_move: pushing TaskExtractScreen with %d task(s) for note %r",
            len(tasks),
            note.id,
        )
        # Use app.call_after_refresh (NOT self.call_after_refresh) to defer the
        # push_screen call until AFTER the current key event has finished bubbling.
        # If push_screen() is called inline during on_key(), the routing keystroke
        # (e.g. 'x' for Archive) propagates to the newly mounted TaskExtractScreen
        # and triggers action_skip immediately.  Scheduling on the App's message
        # pump avoids this key-event collision: SortScreen's ScreenSuspend does not
        # prevent the App-level InvokeLater from firing.
        modal = TaskExtractScreen(tasks, writer)
        self.app.call_after_refresh(self.app.push_screen, modal, self._on_tasks_resolved)
        return True

    def _on_tasks_resolved(self, selected: list[ExtractedTask] | None) -> None:
        """Callback fired when TaskExtractScreen is dismissed.

        Called by Textual after the modal is dismissed with its result (the
        list of tasks the user chose to write — empty on Skip, ``None`` if the
        screen was dismissed without a result).  Advances the sort flow to the
        next note so the session continues.

        Args:
            selected: Tasks written by TaskExtractScreen (or empty/None on Skip).
                Used only for logging here; write already happened inside the screen.
        """
        count = len(selected) if selected else 0
        logger.debug(
            "_on_tasks_resolved: %d task(s) selected; advancing sort flow",
            count,
        )
        self._advance()

    def _advance(self) -> None:
        """Increment the note pointer and render the next note or finish.

        Resets ``_router_state`` to AWAIT_CATEGORY and clears ``_prev`` for the
        next note.  When all notes are processed, calls :meth:`_finish`.
        """
        self._index += 1
        self._router_state = RouterState.AWAIT_CATEGORY
        self._prev = None
        if self._index >= len(self._notes):
            self._finish()
        else:
            self._render_current_note()

    def _finish(self) -> None:
        """Render the session summary and write the audit log.

        Computes the :class:`~notes_os.sorter.session.SessionSummary`, renders
        it in the note-preview panel, writes the audit log via
        ``_session.write_log()``, and offers navigation back to HomeScreen.
        Resets ``app.sort_in_progress`` to ``False`` so a subsequent ``Q``
        quits directly (session is complete; T-06-11 guard no longer needed).
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        summary = self._session.summary()
        log_path = self._session.write_log(app.app_config.log_dir)
        # Reset quit-confirm guard — session is complete (T-06-11 mitigation)
        app.sort_in_progress = False
        logger.info("SortScreen: session complete — log written to %s", log_path)

        summary_text = (
            f"Session complete!\n\n"
            f"  Moved:   {summary.moved}\n"
            f"  Skipped: {summary.skipped}\n"
            f"  Errors:  {summary.errors}\n"
            f"  Total:   {summary.total}\n\n"
            f"Log: {log_path}\n\n"
            f"Press Esc or B to return home."
        )
        self.query_one("#note-title", Static).update("Sort Session Complete")
        self.query_one("#note-preview", Static).update(summary_text)
        self.query_one("#prompt", Static).update("")
        self.query_one("#progress", Static).update(f"Processed {summary.total} note(s).")
        self._inbox_empty = True

    def _current_note(self) -> Note | None:
        """Return the current note, or None if the index is out of range.

        Returns:
            The :class:`~notes_os.sorter.models.Note` at ``_index``, or
            ``None`` when the session is complete (past the last note).
        """
        if 0 <= self._index < len(self._notes):
            return self._notes[self._index]
        return None

    def _render_current_note(self) -> None:
        """Update the four Static widgets to reflect the current note and state."""
        note = self._current_note()
        if note is None:
            return

        total = len(self._notes)
        pos = self._index + 1
        self.query_one("#progress", Static).update(f"Note {pos} of {total}")
        self.query_one("#note-title", Static).update(note.title)
        self.query_one("#note-preview", Static).update(note.preview or "(no preview)")

        if self._router_state == RouterState.AWAIT_CATEGORY:
            self.query_one("#prompt", Static).update(_CATEGORY_PROMPT)
        elif self._router_state in (RouterState.AWAIT_FOLDER, RouterState.AWAIT_SUBFOLDER):
            self._render_options_prompt()

    def _render_options_prompt(self) -> None:
        """Render the numbered folder/subfolder option list in the prompt widget.

        Produces a prompt like::

            Choose folder (Esc/B back):
              1. General
              2. Web

        Only called when ``_prev`` is not None (i.e. AWAIT_FOLDER/AWAIT_SUBFOLDER).
        """
        if self._prev is None:
            return
        state_label = "folder" if self._router_state == RouterState.AWAIT_FOLDER else "subfolder"
        lines = [f"Choose {state_label} (Esc/B back):"]
        for i, name in enumerate(self._prev.options, start=1):
            lines.append(f"  {i}. {name}")
        self.query_one("#prompt", Static).update("\n".join(lines))

    def _render_empty_inbox(self) -> None:
        """Render the empty-inbox state widgets."""
        self.query_one("#note-title", Static).update("Inbox Empty")
        self.query_one("#note-preview", Static).update(
            "No notes in the inbox to sort.\n\nPress Esc or B to return home."
        )
        self.query_one("#prompt", Static).update("")
        self.query_one("#progress", Static).update("0 notes")
