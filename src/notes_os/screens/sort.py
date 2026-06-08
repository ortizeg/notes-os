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

Lazy-loading architecture (performance fix for large inboxes):
    Previously ``_load_inbox`` called ``get_inbox_notes()`` which fetches all
    HTML bodies upfront — O(N) Apple Events, slow on a large inbox.  The new
    approach:

    1. ``_load_inbox_refs`` (fast): calls ``get_inbox_note_refs()`` — two
       Apple Events total, returns id+title only.
    2. ``_load_note_body(ref_id, index)`` (lazy per-note): calls
       ``get_note(ref_id)`` — one Apple Event per note, fired on demand.
    3. Prefetch: when a note body is loaded, the NEXT note's body is also
       prefetched into ``_note_cache`` in the background (cache-warm for
       instant next-note render).

    The Router and move operations only need ``note.id`` — moves are never
    blocked on body load.  Body load is cosmetic (preview display only).

State the screen holds (mirrors SortController call-stack context):
- ``_router`` — the stateless PARA state machine; stateless between calls.
- ``_session`` — accumulates moves/skips/errors for this screen visit.
- ``_refs`` — snapshot of inbox refs taken in ``_load_inbox_refs`` (fast worker).
- ``_index`` — pointer into ``_refs``; advances after each note is done.
- ``_note_cache`` — dict mapping ref.id → full Note (body + preview loaded).
- ``_current_note`` — full Note for the current ref (None if body not loaded yet).
- ``_router_state`` — current state-machine state (AWAIT_CATEGORY etc.).
- ``_prev`` — last ``RouteResult`` carrying folder/subfolder context.
- ``_loading`` — ``True`` while inbox refs are being fetched off-thread;
  ``on_key`` is a safe no-op while this flag is set.

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
- T-06-07 (blocking event loop): ``get_inbox_note_refs()`` is called in
  ``_load_inbox_refs`` (a ``@work(thread=True)`` worker) off the event-loop
  thread; ``on_key`` is guarded by ``_loading`` until the worker completes.
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

from textual import work
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
    from notes_os.sorter.models import Note, NoteRef


logger = logging.getLogger(__name__)

_HELP_TEXT = """\
Key legend - Sort Screen
  P        Projects (navigate folder list)
  A        Areas
  R        Resources
  X        Archive (auto-year)
  S        Skip this note
  ↑↓/j/k   Move highlight in folder/subfolder list
  1-9      Jump-highlight to numbered folder (then Enter to select)
  Enter    Select highlighted folder/subfolder
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

    ``on_mount`` sets a transient "Loading inbox…" state immediately, then
    starts :meth:`_load_inbox_refs` (a ``@work(thread=True)`` worker) to
    fetch the inbox refs (id+title only, NO bodies) off the event-loop
    thread.  ``on_key`` is guarded by ``_loading`` and is a safe no-op
    while the worker is running.

    Per-note body loading is lazy: when the screen renders a note, if the
    full body is not yet in ``_note_cache`` it shows "Loading preview…" and
    starts a background worker to fetch just that note's body.  A prefetch
    worker also fetches the NEXT note's body in the background so the user
    typically sees an instant render when they advance.

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

        Router, session, refs snapshot, and navigation state are all
        initialised here as sentinel values and populated in
        ``_load_inbox_refs`` (the background thread worker started by
        ``on_mount``) after the app is attached and ``self.app.repo`` is
        available.

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
        # Lightweight refs — id+title only (populated by _load_inbox_refs)
        self._refs: list[NoteRef] = []
        # Full Note cache — populated lazily as notes are viewed
        self._note_cache: dict[str, Note] = {}
        # Full Note for current position (None if body not yet loaded)
        self._current_note: Note | None = None
        self._index: int = 0
        self._router_state: RouterState = RouterState.AWAIT_CATEGORY
        self._prev: RouteResult | None = None
        self._inbox_empty: bool = False
        self._loading: bool = True  # True until _load_inbox_refs worker completes
        self._highlight: int = 0  # 0-based highlight index for AWAIT_FOLDER/SUBFOLDER

    def compose(self) -> ComposeResult:
        """Lay out the sort-screen widgets.

        Yields a Header, note-title Static, note-preview Static, prompt
        Static (PARA keys or numbered folder list), progress Static, and
        a Footer.

        Yields:
            Header, four Static content panels, Footer.
        """
        yield Header(show_clock=False)
        # markup=False: these Statics render literal text — the category prompt's
        # "[P]rojects [A]reas …" shortcuts and arbitrary note title/preview content
        # (which may contain "[" brackets). Textual console markup would otherwise
        # parse "[P]" etc. as tags and strip them, eating the first letter.
        yield Static("", id="note-title", markup=False)
        yield Static("", id="note-preview", markup=False)
        yield Static("", id="prompt", markup=False)
        yield Static("", id="progress", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        """Render a transient loading state and kick off inbox ref loading off-thread.

        Router and SortSession are initialised synchronously (cheap, no I/O).
        ``get_inbox_note_refs()`` — the bulk AppleScript fetch — is deferred
        to :meth:`_load_inbox_refs` (a ``@work(thread=True)`` worker) so
        Textual can paint the screen before any AppleScript call completes.
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]

        self._router = Router(
            repo=app.repo,
            config=app.app_config,
            year_provider=self._year_provider,
        )
        self._session = SortSession()

        # Show a transient loading state while the inbox refs are fetched off-thread.
        self.query_one("#note-title", Static).update("Loading inbox…")
        self.query_one("#note-preview", Static).update("")
        self.query_one("#prompt", Static).update("")
        self.query_one("#progress", Static).update("")

        # Start the background worker; on_key is guarded by _loading=True.
        self._load_inbox_refs()

    @work(thread=True, exclusive=True)
    def _load_inbox_refs(self) -> None:
        """Fetch inbox note refs (id+title only) off the event-loop thread.

        Calls ``app.repo.get_inbox_note_refs()`` — two Apple Events total,
        no HTML bodies.  Once refs are available, marshals state back to the
        main thread via ``self.app.call_from_thread`` and renders the first
        note (or the empty-inbox state).

        ``_loading`` is reset to ``False`` inside ``call_from_thread`` so
        ``on_key`` only becomes active after the inbox state is fully applied.
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        refs = app.repo.get_inbox_note_refs()
        self.app.call_from_thread(self._apply_inbox_refs, refs)

    def _apply_inbox_refs(self, refs: list[NoteRef]) -> None:
        """Apply the inbox refs fetched by the thread worker.

        Called on the main thread via ``call_from_thread``.  Sets all
        navigation state fields and renders the first note (kicking off its
        body-load worker) or the empty-inbox state, then clears ``_loading``
        to enable ``on_key``.

        Args:
            refs: The inbox refs returned by ``get_inbox_note_refs()``.
        """
        self._refs = refs
        self._index = 0
        self._router_state = RouterState.AWAIT_CATEGORY
        self._prev = None
        self._current_note = None
        self._loading = False

        if not self._refs:
            self._inbox_empty = True
            self._render_empty_inbox()
            return

        self._render_current_note()

    # ------------------------------------------------------------------
    # Lazy body loading
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_note_body(self, ref_id: str, index: int) -> None:
        """Fetch a single note's full body off the event-loop thread.

        Args:
            ref_id: The note id to fetch.
            index: The inbox position this fetch is for.  Used to guard
                against stale updates when the user has already moved on.
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        try:
            note = app.repo.get_note(ref_id)
        except Exception:
            logger.warning(
                "SortScreen: failed to load body for note %r",
                ref_id,
                exc_info=True,
            )
            return
        self.app.call_from_thread(self._apply_note_body, note, index)

    def _apply_note_body(self, note: Note, index: int) -> None:
        """Cache the fetched note body and refresh the preview if still current.

        Called on the main thread via ``call_from_thread`` from
        :meth:`_load_note_body`.  Caches the note unconditionally (for
        prefetch use), then re-renders the preview only when the user is
        still viewing the same note position.

        Args:
            note: The fully-loaded note (id, title, body, preview).
            index: The inbox position this note corresponds to.
        """
        self._note_cache[note.id] = note
        if self._index == index:
            self._current_note = note
            # Re-render to show the now-loaded preview
            self._render_current_note()
            # Prefetch the next note while the user reads this one
            self._prefetch_next(index)

    def _prefetch_next(self, current_index: int) -> None:
        """Start a background body-fetch for the note at ``current_index + 1``.

        Called after a note's body loads (so the NEXT note is warm in the
        cache when the user advances).  No-ops when already cached or at
        the end of the inbox.

        Args:
            current_index: The currently-displayed note's inbox position.
        """
        next_index = current_index + 1
        if next_index >= len(self._refs):
            return
        next_ref = self._refs[next_index]
        if next_ref.id not in self._note_cache:
            self._load_note_body(next_ref.id, next_index)

    def _get_or_kick_note(self, ref_id: str, index: int) -> Note | None:
        """Return the cached Note for *ref_id*, or start a background load.

        If the note body is already in ``_note_cache`` returns it immediately.
        Otherwise returns ``None`` and starts :meth:`_load_note_body` so the
        preview will be updated when the fetch completes.

        Args:
            ref_id: The note id to look up.
            index: The inbox index for the stale-update guard.

        Returns:
            The cached :class:`~notes_os.sorter.models.Note`, or ``None``
            if the body has not been fetched yet.
        """
        if ref_id in self._note_cache:
            return self._note_cache[ref_id]
        # Not cached — kick off a background fetch and show placeholder
        self._load_note_body(ref_id, index)
        return None

    # ------------------------------------------------------------------
    # Note accessor helpers
    # ------------------------------------------------------------------

    def _current_ref(self) -> NoteRef | None:
        """Return the current NoteRef, or None if the index is out of range.

        Returns:
            The :class:`~notes_os.sorter.models.NoteRef` at ``_index``, or
            ``None`` when past the end of the inbox.
        """
        if 0 <= self._index < len(self._refs):
            return self._refs[self._index]
        return None

    def _note_for_move(self) -> Note | None:
        """Return a Note suitable for the Router move operations.

        The Router's ``handle_*`` methods only use ``note.id`` and
        ``note.preview`` (the latter for task extraction).  If the full body
        is cached, return it.  If not yet loaded, construct a minimal Note
        from the current ref (id + title; empty body/preview) — this is safe
        because ``move_note`` only needs ``note.id``, and task extraction
        falls back to an empty preview gracefully.

        Returns:
            A :class:`~notes_os.sorter.models.Note` for the current inbox
            position, or ``None`` if past the end of the inbox.
        """
        ref = self._current_ref()
        if ref is None:
            return None
        # Prefer the fully-loaded note from the cache
        if self._current_note is not None:
            return self._current_note
        if ref.id in self._note_cache:
            return self._note_cache[ref.id]
        # Body not loaded yet — build a minimal Note from the ref.
        # move_note only needs id; task extraction will use empty preview.
        from notes_os.sorter.models import Note

        return Note(id=ref.id, title=ref.title, body="", preview="")

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        """Translate Textual key events into Router transitions.

        No-ops silently while ``_loading`` is ``True`` (inbox refs not yet
        fetched).  Keystrokes work even when the current note's body is still
        loading — moves only need the note id which is in the ref.

        Dispatches based on the current ``_router_state`` once loaded:
        - ``AWAIT_CATEGORY``: category keys (P/A/R/X/S/?), or Esc/B back.
        - ``AWAIT_FOLDER``: numeric keys 1-9, or Esc/B back.
        - ``AWAIT_SUBFOLDER``: numeric keys 1-9, or Esc/B back.

        Unknown keys are silently ignored (re-renders current state).
        ROUT-07 — Router also no-ops on invalid keys.

        Args:
            event: The Textual :class:`~textual.events.Key` event.
        """
        if self._loading:
            return

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

    def _router_call(self, note: Note, call: Callable[[], RouteResult]) -> RouteResult | None:
        """Run a router transition that may perform a move, isolating failures.

        The archive (``[X]``) path and immediate folder/subfolder selections
        perform the move INSIDE the router (``ensure_folder`` / ``move_note`` /
        the pre-write backup), so a backup or AppleScript failure raises here —
        not in :meth:`_handle_move`.  Per BRDG-06 / BKUP-06, a failed write is a
        warning the session survives, never a crash: record the error, surface
        it, and keep the (un-moved) note in view at AWAIT_CATEGORY so the user
        can retry, skip, or quit.

        Args:
            note: The note the failed transition was acting on.
            call: A zero-arg callable invoking the router transition.

        Returns:
            The ``RouteResult`` on success, or ``None`` when a
            :class:`~notes_os.exceptions.NotesOSError` was caught and handled.
        """
        try:
            return call()
        except NotesOSError as exc:
            logger.warning("SortScreen: move failed for note %r: %s", note.id, exc)
            self._session.record_error(note.id, str(exc))
            self.app.sort_in_progress = True  # type: ignore[attr-defined]
            self._router_state = RouterState.AWAIT_CATEGORY
            self._prev = None
            self._show_move_error(str(exc))
            return None

    def _show_move_error(self, message: str) -> None:
        """Render a move/backup failure in the prompt and keep the note in view.

        Args:
            message: The error text from the caught exception.
        """
        self.query_one("#prompt", Static).update(
            f"⚠ Could not move this note — it stays in your inbox:\n{message}\n\n{_CATEGORY_PROMPT}"
        )

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
        note = self._note_for_move()
        if note is None:
            return

        result = self._router_call(note, lambda: self._router.handle_category(key, note))  # type: ignore[union-attr]
        if result is None:
            return

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
            self._highlight = 0
            self._render_current_note()
            return

        logger.debug("SortScreen: no-op key %r at AWAIT_CATEGORY", key)

    def _handle_folder_or_subfolder_key(self, key: str, *, folder: bool) -> None:
        """Handle navigation/selection keystrokes at AWAIT_FOLDER / AWAIT_SUBFOLDER.

        Arrow keys (↑↓) and vim-style (j/k) move the highlight.  Digit keys
        1-9 jump-highlight to that numbered option without selecting.  Enter
        confirms the highlighted selection by calling ``handle_folder`` or
        ``handle_subfolder`` with the 1-based index.

        This design lets users reach folders 10 and above via arrow navigation
        (a single digit would be out-of-range for 10+).  A lone digit key never
        moves a note — Enter is always required to confirm (ROUT-07).

        Args:
            key: Keystroke string (e.g. ``"up"``, ``"down"``, ``"1"``,
                ``"enter"``).
            folder: ``True`` when in AWAIT_FOLDER; ``False`` for AWAIT_SUBFOLDER.
        """
        if self._router is None or self._prev is None:
            return
        options = self._prev.options
        if not options:
            return

        if key in ("up", "k"):
            self._highlight = max(0, self._highlight - 1)
            self._render_options_prompt()
            return

        if key in ("down", "j"):
            self._highlight = min(len(options) - 1, self._highlight + 1)
            self._render_options_prompt()
            return

        if key.isdigit() and key != "0":
            d = int(key)
            if 1 <= d <= len(options):
                self._highlight = d - 1
                self._render_options_prompt()
            return

        if key == "enter":
            note = self._note_for_move()
            if note is None:
                return
            index = self._highlight + 1
            router, prev = self._router, self._prev  # locals: non-None per the guard above
            if folder:
                result = self._router_call(note, lambda: router.handle_folder(index, prev, note))
            else:
                result = self._router_call(note, lambda: router.handle_subfolder(index, prev, note))
            if result is None:
                return

            if result.action == RouteAction.MOVE and result.folder_path is not None:
                self._handle_move(note, result)
                return

            if result.state == RouterState.AWAIT_SUBFOLDER:
                self._prev = result
                self._router_state = RouterState.AWAIT_SUBFOLDER
                self._highlight = 0
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
        # Reset highlight when landing on any folder/subfolder list (back nav)
        if back_result.state in (RouterState.AWAIT_FOLDER, RouterState.AWAIT_SUBFOLDER):
            self._highlight = 0
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

        Per-move operations (``router.handle_*`` → ``ensure_folder`` /
        ``move_note`` / backup) block the event loop for ~1 s each on the real
        AppleScript backend.  This is acceptable in M1 — a brief per-move pause
        is visible but the app remains correct and the UX is usable.  Making
        these async/threaded is left as future work (would require refactoring
        the Router and BackingUpNotesRepository interfaces).

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
                # Use cached note for extraction (has preview); fall back to whatever we have
                note_for_extraction = self._note_cache.get(note.id, note)
                extraction_deferred = self._after_move(note_for_extraction)
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
            note: The note that was just moved (prefer the cached full note for
                accurate preview-based task extraction).

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

        Resets ``_router_state`` to AWAIT_CATEGORY and clears ``_prev`` and
        ``_current_note`` for the next note.  When all notes are processed,
        calls :meth:`_finish`.
        """
        self._index += 1
        self._router_state = RouterState.AWAIT_CATEGORY
        self._prev = None
        self._current_note = None
        if self._index >= len(self._refs):
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

    def _render_current_note(self) -> None:
        """Update the four Static widgets to reflect the current note and state.

        Shows the note title from the ref (always available immediately) and
        the preview from the full Note if loaded, or a "Loading preview…"
        placeholder while the body-load worker is running.  Also kicks off
        the body-load worker if this is the first render for the current note.
        """
        ref = self._current_ref()
        if ref is None:
            return

        total = len(self._refs)
        pos = self._index + 1
        self.query_one("#progress", Static).update(f"Note {pos} of {total}")
        self.query_one("#note-title", Static).update(ref.title)

        # Try to get the full body from cache (or kick off a load)
        if self._current_note is None:
            self._current_note = self._get_or_kick_note(ref.id, self._index)

        if self._current_note is not None:
            preview_text = self._current_note.preview or "(no preview)"
        else:
            preview_text = "Loading preview…"
        self.query_one("#note-preview", Static).update(preview_text)

        if self._router_state == RouterState.AWAIT_CATEGORY:
            self.query_one("#prompt", Static).update(_CATEGORY_PROMPT)
        elif self._router_state in (RouterState.AWAIT_FOLDER, RouterState.AWAIT_SUBFOLDER):
            self._render_options_prompt()

    def _render_options_prompt(self) -> None:
        """Render the numbered folder/subfolder option list with an arrow highlight.

        Produces a prompt like (markup=False — all literal text)::

            Select a folder (↑↓ move · Enter select · Esc back):
                1. General
              ▸ 2. Web

        The highlighted row (``self._highlight``) is prefixed with "▸ "; all
        other rows with two spaces so they align.  The highlight index is
        clamped defensively to ``[0, len(options)-1]`` before rendering.

        Only called when ``_prev`` is not None (i.e. AWAIT_FOLDER/AWAIT_SUBFOLDER).
        """
        if self._prev is None:
            return
        state_label = "folder" if self._router_state == RouterState.AWAIT_FOLDER else "subfolder"
        options = self._prev.options
        if options:
            self._highlight = max(0, min(self._highlight, len(options) - 1))
        lines = [f"Select a {state_label} (↑↓ move · Enter select · Esc back):"]
        for i, name in enumerate(options, start=1):
            prefix = "▸ " if (i - 1) == self._highlight else "  "
            lines.append(f"  {prefix}{i}. {name}")
        self.query_one("#prompt", Static).update("\n".join(lines))

    def _render_empty_inbox(self) -> None:
        """Render the empty-inbox state widgets."""
        self.query_one("#note-title", Static).update("Inbox Empty")
        self.query_one("#note-preview", Static).update(
            "No notes in the inbox to sort.\n\nPress Esc or B to return home."
        )
        self.query_one("#prompt", Static).update("")
        self.query_one("#progress", Static).update("0 notes")
