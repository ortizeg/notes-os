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
    2. ``_load_body_page(offset, count)`` (background bulk load): after refs
       land, bodies are paged into ``_note_cache`` via
       ``get_inbox_note_bodies(offset, count)``.  Inboxes at or below
       ``_BULK_THRESHOLD`` notes load in ONE silent call (no indicator);
       larger inboxes stream in pages of ``_BULK_PAGE_SIZE`` (first page
       first) with a non-blocking ``Loading previews… N/M`` indicator that
       counts notes loaded and clears on completion.  Pages merge into
       ``_note_cache`` keyed by ``note.id``; an out-of-order page self-
       corrects because the current-note re-render resolves the body by
       ``_note_cache[self._refs[self._index].id]`` (id-keyed, not positional).
    3. ``_load_note_body(ref_id, index)`` / ``_get_or_kick_note`` (by-id
       fallback): the single-note ``get_note(ref_id)`` path survives ONLY as
       the cache-miss fallback for a note reached before its bulk page lands
       (skip-faster-than-load — PERF-03).  There is no prefetch chain.

    The bulk body load runs on a ``@work(thread=True)`` worker and never sets
    ``_loading``; keystrokes stay live while bodies stream (T-06-07 preserved —
    the event loop is never blocked).  The Router and move operations only need
    ``note.id`` — moves are never blocked on body load.  Body load is cosmetic
    (preview display only).

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
  the BackingUpNotesRepository from 06-01's DI seam — a restore point is
  captured before the first write of each session (per-session cadence).
  ``_apply_inbox_refs`` re-arms the latch via ``begin_session`` once per visit
  (BKUP-07), since the repo is app-scoped and reused across visits.
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
from collections import deque
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from notes_os.backup import BackupResettable
from notes_os.exceptions import NotesOSError
from notes_os.sorter.extractor import extract_tasks
from notes_os.sorter.router import RouteAction, Router, RouteResult, RouterState
from notes_os.sorter.session import _KIND_MOVE, _KIND_SKIP, SortSession


if TYPE_CHECKING:
    from collections.abc import Callable

    from textual import events
    from textual.app import ComposeResult

    from notes_os.app import NotesOSApp
    from notes_os.sorter.extractor import ExtractedTask
    from notes_os.sorter.models import FolderPath, Note, NoteRef


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
  U        Undo last action
  Esc / B  Back one level (or return to Home)
  Q        Quit NotesOS
  ?        Show this help
"""

_CATEGORY_PROMPT = "[P]rojects  [A]reas  [R]esources  [X] archive  [S]kip  Esc/B back  ? help"

# Brief hint shown via ``notify`` when ``U`` is pressed but the undo stack is
# empty (nothing left to reverse).  Named constant per CLAUDE.md no-magic-strings;
# the tests import it to assert the no-op hint was surfaced (UX-02).
_NOTHING_TO_UNDO: str = "Nothing to undo."

# Inbox sizes at or below this many notes load all bodies in ONE silent bulk call
# (no streaming indicator); larger inboxes page their bodies in.  Locked default
# from SPEC §6 (CLAUDE.md no-magic-numbers).
_BULK_THRESHOLD: int = 250
# Page size (in notes) used to stream bodies for an inbox larger than
# ``_BULK_THRESHOLD``.  First page first so the note in view lands soonest.
# Locked default from SPEC §6.
_BULK_PAGE_SIZE: int = 200

# Dim, multi-line skeleton placeholder rendered into ``#note-preview`` while the
# current note's body is not yet cached (UX-01).  A few short lines of a block
# glyph read as "coming," not "stuck" — it replaces the old single-note loading
# text placeholder.  Rendered as literal text (the Static is ``markup=False``);
# the dim appearance is CSS-driven via the ``preview-loading`` class, not in this
# string.  Named constant per CLAUDE.md no-magic-strings; the test imports it.
_PREVIEW_SKELETON: str = "░░░░░░░░░░░░░░░░\n░░░░░░░░░░░░\n░░░░░░░░░░░░░░"
# CSS class toggled on the ``#note-preview`` Static: added while the skeleton
# shows, removed once the real preview lands so a loaded note is never dim.
# Named constant so the class string is not duplicated between the add/remove
# call sites; keyed to the ``#note-preview.preview-loading`` rule in app.tcss.
_PREVIEW_SKELETON_CLASS: str = "preview-loading"


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

    Body loading is a background paged bulk load (see the module docstring):
    after refs land, ``_load_body_page`` streams bodies into ``_note_cache``.
    When the screen renders a note whose body is not yet cached it shows the dim
    :data:`_PREVIEW_SKELETON` placeholder (with the ``preview-loading`` CSS class)
    and falls back to a single-note ``get_note`` fetch via
    :meth:`_get_or_kick_note`, swapping in the real preview (and removing the
    class) when that fetch completes.

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
        Binding("u", "undo", "Undo", show=True),
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
        # Background bulk-body-load streaming state (notes fraction for the
        # "Loading previews… N/M" indicator).  Distinct from ``_loading``,
        # which gates ``on_key`` on refs only — body streaming never blocks keys.
        self._previews_total: int = 0  # M — total notes (== len(self._refs))
        self._previews_loaded: int = 0  # N — notes whose bodies have landed
        self._previews_streaming: bool = False  # True only while paged load runs
        # Off-thread write plumbing (Phase 13-02, PERF-04/05).  A move advances
        # the UI optimistically; the actual ensure_folder + move_note (+ the
        # per-session backup) runs on a SINGLE serialized background drainer so
        # the Phase-12 backup latch and move ordering are never corrupted by
        # concurrency.  The names below are reused by Phase 14 (Undo/move-back)
        # and Phase 15 (Resume) which enqueue through the same path.
        #
        # FIFO of pending writes (note_id, folder_path, display).  Appended on
        # the main thread in _enqueue_write; popped (left) by the single drainer.
        self._write_queue: deque[tuple[str, FolderPath, str]] = deque()
        # Single-drainer guard.  Read/written ONLY on the main thread (in
        # _enqueue_write and _on_writer_drained); the worker NEVER touches it.
        # True while a _drain_write_queue worker is in flight → at most ONE writer.
        self._writer_active: bool = False
        # "Needs attention" list of (note_id, display, message) for writes that
        # FAILED off-thread — surfaced in the session summary (PERF-05).
        self._failed_moves: list[tuple[str, str, str]] = []
        # Set when _advance reaches the end while writes are still in flight; the
        # drainer triggers the real finish once the queue empties (drain-before-summary).
        self._finish_pending: bool = False

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

        # defer_writes=True (the 13-01 seam): the router RESOLVES the move
        # (folder_path + display_path) but performs NO ensure_folder / move_note /
        # backup on the event loop — SortScreen owns the serialized off-thread
        # write so a move never freezes the UI (PERF-04).  The CLI SortController
        # leaves defer_writes at its False default and still writes synchronously.
        self._router = Router(
            repo=app.repo,
            config=app.app_config,
            year_provider=self._year_provider,
            defer_writes=True,
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

        Re-arms the per-session backup latch here (BKUP-07): this runs exactly
        once per SortScreen visit, before any move can occur.  ``app.repo`` is
        app-scoped (constructed once) and reused across visits, so an explicit
        per-visit reset is required for each visit to capture its own restore
        point.  A plain repo without ``begin_session`` (e.g. an injected
        ``MockNotesRepository``) is safely skipped via the ``BackupResettable``
        guard.

        Args:
            refs: The inbox refs returned by ``get_inbox_note_refs()``.
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        if isinstance(app.repo, BackupResettable):
            app.repo.begin_session()

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
        self._start_bulk_body_load()

    # ------------------------------------------------------------------
    # Background bulk body load (paged)
    # ------------------------------------------------------------------

    def _start_bulk_body_load(self) -> None:
        """Kick off the background bulk body load after refs are applied.

        Inboxes at or below :data:`_BULK_THRESHOLD` notes load all bodies in
        ONE silent background page (``_previews_streaming`` stays ``False`` so
        no indicator is shown).  Larger inboxes start streaming the FIRST page
        of :data:`_BULK_PAGE_SIZE` notes; subsequent pages are chained from
        :meth:`_apply_body_page` (first page first) and a non-blocking
        ``Loading previews… N/M`` indicator counts notes up.

        The body load never sets ``_loading`` — keystrokes stay live while
        bodies stream (T-06-07: the event loop is never blocked).
        """
        total = len(self._refs)
        self._previews_total = total
        self._previews_loaded = 0
        if total <= _BULK_THRESHOLD:
            self._previews_streaming = False
            self._load_body_page(0, total)
        else:
            self._previews_streaming = True
            self._load_body_page(0, _BULK_PAGE_SIZE)

    @work(thread=True)
    def _load_body_page(self, offset: int, count: int) -> None:
        """Fetch one page of note bodies off the event-loop thread.

        Calls ``app.repo.get_inbox_note_bodies(offset, count)`` and marshals
        the resulting page back to the main thread via ``call_from_thread``.
        A failed page is logged and swallowed (it must not crash the session);
        any note whose page failed is still resolvable via the by-id
        ``get_note`` cache-miss fallback (PERF-03 / T-10-06).

        Args:
            offset: 0-based start index of the page within ``_refs``.
            count: Number of notes to fetch starting at *offset*.
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        try:
            notes = app.repo.get_inbox_note_bodies(offset, count)
        except Exception:
            logger.warning(
                "SortScreen: failed to bulk-load body page offset=%d count=%d",
                offset,
                count,
                exc_info=True,
            )
            return
        self.app.call_from_thread(self._apply_body_page, notes, offset)

    def _apply_body_page(self, notes: list[Note], offset: int) -> None:
        """Merge a landed body page into the cache and continue streaming.

        Called on the main thread via ``call_from_thread``.  Merges each note
        into ``_note_cache`` keyed by ``note.id``; updates the streaming
        indicator (a notes fraction — N increments by ``len(notes)``); re-
        renders the current note ONLY when its body just arrived (its index
        falls inside this page) using an id-keyed lookup so an out-of-order
        page self-corrects (T-10-07); then chains the next page or, when no
        pages remain, clears the streaming indicator.

        Args:
            notes: The page of fully-loaded notes returned by the worker.
            offset: The 0-based start index of *notes* within ``_refs``.
        """
        for note in notes:
            self._note_cache[note.id] = note

        if self._previews_streaming:
            self._previews_loaded += len(notes)

        # Re-render the current note ONLY if its body just arrived in this page.
        # Resolve id-keyed (not positional) so a page returned out of order
        # still renders the RIGHT note — the phase's #1 named risk.
        if offset <= self._index < offset + len(notes):
            current_ref = self._refs[self._index]
            cached = self._note_cache.get(current_ref.id)
            if cached is not None:
                self._current_note = cached
        self._render_current_note()

        if self._previews_streaming:
            next_offset = offset + _BULK_PAGE_SIZE
            if next_offset < len(self._refs):
                self._load_body_page(next_offset, _BULK_PAGE_SIZE)
            else:
                self._previews_streaming = False
                self._render_progress()

    # ------------------------------------------------------------------
    # Lazy body loading (by-id cache-miss fallback)
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
        :meth:`_load_note_body` (the cache-miss fallback).  Caches the note
        unconditionally, then re-renders the preview only when the user is
        still viewing the same note position (stale-index guard).

        Args:
            note: The fully-loaded note (id, title, body, preview).
            index: The inbox position this note corresponds to.
        """
        self._note_cache[note.id] = note
        if self._index == index:
            self._current_note = note
            # Re-render to show the now-loaded preview
            self._render_current_note()

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
        # In a real terminal the Enter key arrives with character="\r" (a truthy
        # carriage return) which would shadow event.key="enter" above and break
        # folder selection. Normalize named navigation keys off event.key so the
        # handlers see "enter"/"up"/"down" regardless of the control character.
        if event.key in ("enter", "up", "down"):
            key = event.key

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
            # Capture the undo index BEFORE _advance steps _index forward (UX-02):
            # an undo of this skip steps the pointer back to exactly this note.
            undo_index = self._index
            self._session.record_skip(note.id, index=undo_index)
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

    # ------------------------------------------------------------------
    # Undo (UX-02)
    # ------------------------------------------------------------------

    def _inbox_folder_path(self) -> FolderPath:
        """Return the inbox folder path — the captured move-back origin (UX-02).

        The source ``FolderPath`` a moved note came from (M1: the configured
        inbox folder).  Captured onto the :class:`~notes_os.sorter.session.UndoEntry`
        at move time so an undo move-back targets the TRUE origin rather than a
        recomputed/guessed path; a future phase capturing a subfolder source would
        carry a different path on the entry without changing the move-back code.

        Returns:
            A single-element :class:`~notes_os.sorter.models.FolderPath` naming the
            configured inbox folder (``("Notes",)`` by default).
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        return (app.app_config.bridge.inbox_folder,)

    def action_undo(self) -> None:
        """Handle ``U``/``u``: undo the most-recent reversible action (UX-02).

        Driven ONLY by the footer ``Binding`` (there is NO ``on_key`` branch for
        ``u``/``U`` — that would double-fire), mirroring the ``escape``/``b`` →
        :meth:`action_back` precedent.  Because Textual ``action_*`` methods fire
        regardless of router state, this guards before dispatching: it is a no-op
        while ``_loading`` (inbox refs not yet fetched), while ``_inbox_empty``
        (empty inbox AND the post-:meth:`_complete_finish` summary state, which
        sets ``_inbox_empty = True``), and at any router state other than
        ``AWAIT_CATEGORY`` (mid folder/subfolder navigation — ``U`` is not an undo
        there).  Only when every guard passes does it delegate to
        :meth:`_handle_undo`.
        """
        if self._loading or self._inbox_empty:
            return
        if self._router_state is not RouterState.AWAIT_CATEGORY:
            return
        self._handle_undo()

    def _handle_undo(self) -> None:
        """Pop and apply the most-recent reversible action on screen (UX-02).

        Pops :meth:`~notes_os.sorter.session.SortSession.pop_undo` (which already
        reversed the counter LIFO with ``> 0`` guards).  When the stack is empty
        the pop returns ``None`` — surface the :data:`_NOTHING_TO_UNDO` hint and
        return with zero index/counter change (the no-op + hint).

        Otherwise branch on the entry kind:

        - SKIP: step ``_index`` back to the entry's index, reset router state to
          ``AWAIT_CATEGORY``, clear ``_prev``/``_current_note``, and re-render.  NO
          write — the skipped note was never removed from ``_refs``, so stepping
          back re-shows it.
        - MOVE: enqueue a move-back of the note to the captured source folder
          through the EXISTING Phase-13 serialized write queue
          (:meth:`_enqueue_write` → ``ensure_folder``-before-``move_note`` on the
          single backup-latch-safe drainer), then step ``_index`` back and
          re-render.  A move-back that fails off-thread flows through the existing
          :meth:`_on_write_failed` path (no bespoke handling) so counts stay
          non-negative and the TUI never crashes (T-14-05).
        """
        entry = self._session.pop_undo()
        if entry is None:
            self.notify(_NOTHING_TO_UNDO)
            return

        if entry.kind == _KIND_MOVE:
            # Move-back to the captured source (defensively fall back to the
            # configured inbox if the entry carried no source path).
            dest = entry.source_path if entry.source_path is not None else self._inbox_folder_path()
            display = " > ".join(dest)
            # Reuse the Phase-13 serialized off-thread drainer — never a
            # synchronous on-event-loop write (backup-latch + FIFO safe).
            self._enqueue_write(entry.note_id, dest, display)
            self.notify("undid move ✓")
        elif entry.kind != _KIND_SKIP:
            # Unknown kind — leave state untouched (defensive; should not occur).
            logger.warning("SortScreen: unknown undo kind %r — ignoring", entry.kind)
            return

        # Step the pointer back to the undone note and re-render at AWAIT_CATEGORY
        # (shared by both move-undo and skip-undo).
        self._index = entry.index
        self._router_state = RouterState.AWAIT_CATEGORY
        self._prev = None
        self._current_note = None
        self._render_current_note()

    def _show_help(self) -> None:
        """Display the help overlay as a Textual notification."""
        self.notify(_HELP_TEXT, title="Sort Help", timeout=8.0)

    def _handle_move(self, note: Note, result: RouteResult) -> None:
        """Optimistically record + confirm + advance a move; write off-thread.

        OPTIMISTIC ADVANCE (PERF-04): a move now feels as instant as a skip.
        The router resolved the destination with ``defer_writes=True`` (no I/O on
        the event loop), so this method does ONLY fast, local work synchronously —
        it records the move, shows a non-blocking confirmation, enqueues the actual
        ``ensure_folder`` + ``move_note`` (+ the per-session backup) onto a single
        serialized off-thread drainer, and advances to the next note IMMEDIATELY.
        The old per-move ~1 s freeze is gone: AppleScript/backup never runs on the
        event loop here.

        Order is load-bearing (T-13-10 — no advance/worker race): ``note.id`` +
        ``folder_path`` + ``display`` are captured into LOCALS and enqueued BEFORE
        :meth:`_advance` changes ``_index`` / ``_current_note``, so the in-flight
        write can never be mis-targeted by a later index change.

        ``record_move`` counts the move OPTIMISTICALLY; if the off-thread write
        later fails, :meth:`_on_write_failed` reconciles the count
        (move → error) and the note is retained in the inbox (PERF-05).

        After enqueueing, :meth:`_after_move` runs exactly as before: extraction
        is OFF by default (returns ``False`` → advance immediately); when enabled
        and tasks are found it pushes the modal and ``_advance`` fires via
        :meth:`_on_tasks_resolved` (T-06-08 path preserved byte-for-byte).

        The ``try/except NotesOSError`` guards ONLY the pure local steps
        (``record_move`` / ``_after_move``); the write itself is off-thread and
        can no longer raise synchronously here.

        Args:
            note: The note that was just moved.
            result: The ``RouteResult`` with ``action==MOVE`` and
                ``folder_path`` populated.
        """
        if result.folder_path is None:
            return
        # Capture into locals BEFORE advancing (T-13-10 no advance/worker race).
        note_id = note.id
        folder_path = result.folder_path
        display = result.display_path or ""
        # Capture the undo source + index BEFORE _advance changes _index (UX-02):
        # an undo move-back targets the captured SOURCE folder (the inbox) and
        # steps the pointer back to exactly this note's position.
        undo_index = self._index
        source = self._inbox_folder_path()

        extraction_deferred = False
        try:
            self._session.record_move(
                note_id, folder_path, source_path=source, index=undo_index
            )  # optimistic count
            logger.debug("Note %r optimistically moved to %s", note_id, display)
            # Signal to the app that a session is in progress (T-06-11 mitigation).
            self.app.sort_in_progress = True  # type: ignore[attr-defined]
            # Non-blocking toast confirmation — does NOT gate the next-note render.
            self.notify(f"moved ✓ → {display}")
            # Dispatch the actual ensure_folder + move_note (+ backup) off-thread.
            self._enqueue_write(note_id, folder_path, display)
            # Use the cached note for extraction (has preview); fall back to ref note.
            note_for_extraction = self._note_cache.get(note_id, note)
            extraction_deferred = self._after_move(note_for_extraction)
        except NotesOSError as exc:
            self._session.record_error(note_id, str(exc))
            logger.warning("SortScreen: error preparing move for note %r: %s", note_id, exc)
        if not extraction_deferred:
            self._advance()

    # ------------------------------------------------------------------
    # Serialized off-thread write drainer (PERF-04 / PERF-05)
    # ------------------------------------------------------------------

    def _enqueue_write(self, note_id: str, folder_path: FolderPath, display: str) -> None:
        """Enqueue a pending write and arm the single drainer if idle.

        Appends ``(note_id, folder_path, display)`` to :attr:`_write_queue` and,
        iff no drainer is currently running, sets :attr:`_writer_active` and starts
        :meth:`_drain_write_queue`.  Both the append and the flag mutation happen on
        the main/event-loop thread, so this producer / single-consumer guard is
        race-free and guarantees at most ONE in-flight writer (keeps the Phase-12
        backup latch and move ordering safe — T-13-05 / T-13-06).

        Reusable by Phase 14 (Undo) for move-back writes through the same path.

        Args:
            note_id: The opaque note id whose write is pending.
            folder_path: The resolved destination path the worker will write to.
            display: The human-readable destination (for failure messages).
        """
        self._write_queue.append((note_id, folder_path, display))
        if not self._writer_active:
            self._writer_active = True
            self._drain_write_queue()

    @work(thread=True)
    def _drain_write_queue(self) -> None:
        """Drain the FIFO write queue one item at a time off the event-loop thread.

        Exactly ONE instance is ever in flight (guarded by :attr:`_writer_active`,
        set on the main thread before the worker starts), so only this single
        thread ever calls ``move_note`` / ``ensure_folder`` (and thus the
        non-thread-safe Phase-12 backup latch) — T-13-05.  ``ensure_folder`` is
        always issued BEFORE ``move_note`` so the destination exists.

        FIFO ordering (``popleft`` in enqueue order) means moves execute in the
        order the user issued them (T-13-06).  ``deque.append`` / ``deque.popleft``
        are individually atomic under the GIL; the producer (main thread) only
        appends, this single consumer only pops, so no lock is needed.

        A write that raises :class:`~notes_os.exceptions.NotesOSError` (covering
        ``BackupError`` / ``NotesMoveError`` / ``FolderNotFoundError``) is caught
        PER ITEM and marshalled to :meth:`_on_write_failed` on the main thread; the
        drain continues so one bad move never aborts the session (PERF-05 / T-06-05).
        When the queue empties, :meth:`_on_writer_drained` is marshalled back to the
        main thread to clear the flag and re-check for a lost wakeup (T-13-09).
        """
        app: NotesOSApp = self.app  # type: ignore[assignment]
        while self._write_queue:
            note_id, folder_path, display = self._write_queue.popleft()
            try:
                app.repo.ensure_folder(folder_path)
                app.repo.move_note(note_id, folder_path)
            except NotesOSError as exc:
                self.app.call_from_thread(self._on_write_failed, note_id, display, str(exc))
            else:
                logger.debug("Off-thread write complete: note %r → %s", note_id, display)
        # Queue drained — hand control back to the main thread to clear the flag,
        # re-check for a lost wakeup, and complete a pending finish if any.
        self.app.call_from_thread(self._on_writer_drained)

    def _on_writer_drained(self) -> None:
        """Clear the drainer flag, re-check for a lost wakeup, finish if pending.

        Runs on the MAIN thread (via ``call_from_thread``).  Ordering is critical
        (T-13-09 lost-wakeup guard): clear :attr:`_writer_active` FIRST, THEN
        re-check :attr:`_write_queue`.  An item enqueued in the gap between the
        worker's empty-check and this clear would otherwise never be written —
        re-arming a fresh drainer here closes that window.  Both the producer
        (:meth:`_enqueue_write`) and this flag mutation run on the main thread, so
        the guard is race-free.

        If a finish was deferred while writes were in flight (:attr:`_finish_pending`)
        and the queue is now fully drained, the real finish completes here so the
        summary reflects landed failures (drain-before-summary — T-13-08).
        """
        self._writer_active = False
        if self._write_queue:
            # Lost-wakeup recovery: an item arrived after the worker's last check.
            self._writer_active = True
            self._drain_write_queue()
            return
        if self._finish_pending:
            self._finish_pending = False
            self._complete_finish()

    def _on_write_failed(self, note_id: str, display: str, message: str) -> None:
        """Surface + record + retain a write that failed off-thread (PERF-05).

        Runs on the MAIN thread (via ``call_from_thread``).  Reconciles the
        optimistic move into an error via
        :meth:`~notes_os.sorter.session.SortSession.record_move_failure`
        (move → error), tracks the failure in :attr:`_failed_moves` for the
        summary's "Needs attention" section, and shows a non-blocking
        :meth:`notify` naming the note that stayed in the inbox.

        The note physically STAYED in the inbox — the worker's ``move_note``
        raised before any removal, so the note is retained, never silently
        dropped (PERF-05 / T-06-05).  This does NOT advance or block: the user
        already advanced past this note optimistically.

        Args:
            note_id: The opaque note id whose off-thread write failed.
            display: The human-readable intended destination of the move.
            message: The failure description from the caught exception.
        """
        self._session.record_move_failure(note_id, message)
        self._failed_moves.append((note_id, display, message))
        self.notify(
            f"⚠ Move failed — '{display}' note stayed in your inbox: {message}",
            severity="warning",
        )
        logger.warning("SortScreen: off-thread move failed for note %r: %s", note_id, message)

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
        """Finalize the session — DRAINING any in-flight writes first (T-13-08).

        Reached from :meth:`_advance` when the last note is processed.  If a write
        is still in flight (:attr:`_writer_active`) or queued (:attr:`_write_queue`
        non-empty), the finish is DEFERRED: :attr:`_finish_pending` is set and the
        drainer's :meth:`_on_writer_drained` completes the finish once the queue
        empties, so the summary reflects landed failures (drain-before-summary).

        While writes are pending, ``app.sort_in_progress`` stays ``True`` so the
        ConfirmQuitModal guard still fires on Q (it is cleared only in
        :meth:`_complete_finish`, after the drain).  When no writes are pending the
        finish completes immediately.
        """
        if self._writer_active or self._write_queue:
            self._finish_pending = True
            logger.debug("SortScreen: finish deferred until off-thread writes drain")
            return
        self._complete_finish()

    def _complete_finish(self) -> None:
        """Render the session summary and write the audit log (post-drain).

        Computes the :class:`~notes_os.sorter.session.SessionSummary` AFTER the
        write queue has drained so landed failures are reflected in the counts,
        renders it in the note-preview panel (appending a "Needs attention"
        section listing :attr:`_failed_moves` when non-empty), writes the audit
        log via ``_session.write_log()``, and offers navigation back to
        HomeScreen.  Resets ``app.sort_in_progress`` to ``False`` so a subsequent
        ``Q`` quits directly (session is complete; T-06-11 guard no longer needed).
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
        if self._failed_moves:
            attention_lines = "\n".join(
                f"  • {display} — {message}" for _note_id, display, message in self._failed_moves
            )
            summary_text = (
                f"{summary_text}\n\n"
                f"Needs attention (these notes stayed in your inbox):\n{attention_lines}"
            )
        self.query_one("#note-title", Static).update("Sort Session Complete")
        self.query_one("#note-preview", Static).update(summary_text)
        self.query_one("#prompt", Static).update("")
        self.query_one("#progress", Static).update(f"Processed {summary.total} note(s).")
        self._inbox_empty = True

    def _render_progress(self) -> None:
        """Compose and write the ``#progress`` panel text.

        Always shows the per-note line ``Note {pos} of {total}``.  While the
        background bulk body load is streaming (``_previews_streaming``), a
        second line ``Loading previews… {N}/{M}`` is appended, where N is the
        notes-loaded count and M is the total note count (a notes fraction,
        never a pages/notes mix).  The previews line disappears on completion.

        Composing both lines here means neither the per-note render nor the
        page-merge clobbers the other while pages are still loading.
        """
        total = len(self._refs)
        pos = self._index + 1
        text = f"Note {pos} of {total}"
        if self._previews_streaming:
            text = f"{text}\nLoading previews… {self._previews_loaded}/{self._previews_total}"
        self.query_one("#progress", Static).update(text)

    def _render_current_note(self) -> None:
        """Update the four Static widgets to reflect the current note and state.

        Shows the note title from the ref (always available immediately) and
        the preview from the full Note if loaded, or the dim
        :data:`_PREVIEW_SKELETON` placeholder while the body-load worker is
        running.  While the skeleton shows, the ``#note-preview`` Static carries
        the :data:`_PREVIEW_SKELETON_CLASS` (``preview-loading``) CSS class so it
        renders muted; the moment the real preview lands the class is removed so a
        loaded note is never dim.  Also kicks off the body-load worker if this is
        the first render for the current note.
        """
        ref = self._current_ref()
        if ref is None:
            return

        self._render_progress()
        self.query_one("#note-title", Static).update(ref.title)

        # Try to get the full body from cache (or kick off a load)
        if self._current_note is None:
            self._current_note = self._get_or_kick_note(ref.id, self._index)

        preview = self.query_one("#note-preview", Static)
        if self._current_note is not None:
            # Body cached — show the real preview and drop the dim skeleton class.
            preview.remove_class(_PREVIEW_SKELETON_CLASS)
            preview.update(self._current_note.preview or "(no preview)")
        else:
            # Body not yet cached — show the dim skeleton placeholder.
            preview.add_class(_PREVIEW_SKELETON_CLASS)
            preview.update(_PREVIEW_SKELETON)

        # UX-04 INVARIANT: the category prompt MUST render unconditionally here —
        # OUTSIDE the `_current_note` body-cache branch above — so the action line
        # is live from first paint and is never gated on body load (only
        # `#note-preview` may show the skeleton; `#prompt` never does). Moving this
        # under the body-cache branch would regress UX-04 (see
        # test_category_prompt_live_while_body_streams).
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
