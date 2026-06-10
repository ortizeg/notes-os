"""SortController — wires config, repo, router, UI, and session into the sort loop.

``SortController`` is the orchestration layer for one NotesOS triage session.
It drives the full inbox-sort loop: fetching notes, rendering each one,
routing user keystrokes through the :class:`~notes_os.sorter.router.Router`,
performing moves or skips through the :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`,
recording every outcome in the :class:`~notes_os.sorter.session.SortSession`, and
writing the audit log at the end.

All collaborators are DEPENDENCY-INJECTED so the controller is fully unit-testable
with a :class:`~notes_os.sorter.ui.SortUIProtocol` fake and a
``MockNotesRepository`` — no AppleScript required.

``build_default_controller(config)`` constructs the production wiring:
:class:`~notes_os.sorter.notes.AppleScriptNotesRepository` wrapped in
:class:`~notes_os.backup.BackingUpNotesRepository` so that a restore point is
captured before the first write of each session (per-session backup cadence).

Threat mitigations
------------------
- T-04-09: every write path goes through BackingUpNotesRepository, which captures
  a restore point before the first write of each session (per-session cadence);
  ``SortController.run`` re-arms the latch via ``begin_session`` at session start
  (BKUP-07) — wired in ``build_default_controller``.
- T-04-10: each note's move is wrapped in ``try/except NotesOSError`` so one failure
  does NOT abort the whole session; the error is recorded and the loop continues.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from notes_os.backup import BackupResettable
from notes_os.exceptions import NotesOSError
from notes_os.sorter.router import RouteAction, RouteResult, RouterState
from notes_os.sorter.session import SortSession


if TYPE_CHECKING:
    from collections.abc import Callable

    from notes_os.config import SorterConfig
    from notes_os.sorter.extractor import ExtractedTask, TaskWriter
    from notes_os.sorter.models import Note
    from notes_os.sorter.notes import NotesRepositoryProtocol
    from notes_os.sorter.router import Router
    from notes_os.sorter.ui import SortUIProtocol


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SortController
# ---------------------------------------------------------------------------


class SortController:
    """Orchestrator for a single NotesOS triage session.

    Drives the inbox-sort loop end to end:

    1. Fetches all inbox notes via the injected *repo*.
    2. Calls ``ui.show_inbox_count(len(notes))`` so the user knows how many to
       expect (UI-04).
    3. For each note: renders it, prompts for a category key, runs the note
       through the :class:`~notes_os.sorter.router.Router` state machine,
       performs the resolved action (move or skip), and records the outcome in
       the :class:`~notes_os.sorter.session.SortSession`.
    4. After the loop: displays the session summary (SESS-02) and writes the
       audit log to ``config.log_dir`` (SESS-03).

    All collaborators are injected so the controller is testable without any
    AppleScript, terminal I/O, or filesystem access.

    Args:
        repo:    Repository implementation supplying inbox notes and write ops.
        ui:      Terminal UI implementation for rendering and user input.
        session: Mutable session accumulator for tracking triage outcomes.
        router:  Stateless PARA routing state machine.
        config:  Frozen application configuration (used for ``log_dir``).
    """

    def __init__(
        self,
        repo: NotesRepositoryProtocol,
        ui: SortUIProtocol,
        session: SortSession,
        router: Router,
        config: SorterConfig,
        extractor: Callable[[str], list[ExtractedTask]] | None = None,
        writer: TaskWriter | None = None,
    ) -> None:
        """Initialise the controller with its injected dependencies.

        The *extractor* and *writer* parameters are optional.  When both are
        ``None`` (the default), the extraction path is completely inactive
        regardless of ``config.features.task_extraction`` — this preserves
        byte-identical Phase-4 behaviour for all existing call sites that
        pass nothing (SC1 backward-compat).

        Args:
            repo:      :class:`~notes_os.sorter.notes.NotesRepositoryProtocol`
                       implementation (real or mock) for inbox / write ops.
            ui:        :class:`~notes_os.sorter.ui.SortUIProtocol` implementation
                       for rendering and input.
            session:   :class:`~notes_os.sorter.session.SortSession` accumulator.
            router:    :class:`~notes_os.sorter.router.Router` for state transitions.
            config:    :class:`~notes_os.config.SorterConfig` for ``log_dir`` and
                       feature flags.
            extractor: Optional callable ``(str) -> list[ExtractedTask]`` that
                       scans a note's preview text for action items.  Defaults to
                       ``None`` (extraction disabled for this session).
            writer:    Optional :class:`~notes_os.sorter.extractor.TaskWriter` that
                       persists selected tasks to the daily Markdown file.
                       Defaults to ``None`` (no writes).
        """
        self._repo = repo
        self._ui = ui
        self._session = session
        self._router = router
        self._config = config
        self._extractor = extractor
        self._writer = writer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the full inbox-sort loop for one triage session.

        Fetches the inbox, displays the count, and for each note drives the
        router state machine until the note is either moved or skipped.  Every
        move attempt is wrapped in a ``try/except NotesOSError`` so a single
        failure does NOT abort the session (T-04-10 mitigation).  After the
        loop the session summary is shown and the audit log is written.

        Arms the per-session backup latch at session start (BKUP-07): the
        backup-decorating repo captures one restore point before this session's
        first write.  Re-arming here (and on every ``run``) ensures a fresh
        restore point per session even if the same repo instance is reused.

        Returns:
            None.  Side effects: notes moved in Apple Notes (via repo), audit
            log written under ``config.log_dir``.
        """
        # Arm the once-per-session backup latch (BKUP-07).  A plain repo without
        # begin_session (and thus without the backup decorator) is safely skipped.
        if isinstance(self._repo, BackupResettable):
            self._repo.begin_session()

        notes = self._repo.get_inbox_notes()
        self._ui.show_inbox_count(len(notes))
        logger.info("Sort session started — %d notes in inbox", len(notes))

        for note in notes:
            self._ui.render_note(note)
            self._sort_one_note(note)

        summary = self._session.summary()
        self._ui.show_summary(summary)

        log_path = self._session.write_log(self._config.log_dir)
        logger.info("Session log written to %s", log_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sort_one_note(self, note: Note) -> None:
        """Drive the router state machine for a single note until done.

        Loops on ``AWAIT_CATEGORY`` (re-prompting on help or invalid keys) then
        handles ``AWAIT_FOLDER`` / ``AWAIT_SUBFOLDER`` sub-loops until the router
        issues a MOVE or SKIP action.

        Any :class:`~notes_os.exceptions.NotesOSError` raised during the write
        is caught here — the error is recorded in the session and the method
        returns so the outer loop advances to the next note (T-04-10 mitigation).

        Args:
            note: The :class:`~notes_os.sorter.models.Note` to sort.
        """
        try:
            result = self._await_category(note)
            if result.action == RouteAction.SKIP:
                self._session.record_skip(note.id)
                logger.debug("Note %r skipped", note.id)
                return
            if result.action == RouteAction.MOVE and result.folder_path is not None:
                self._session.record_move(note.id, result.folder_path)
                logger.debug("Note %r moved to %s", note.id, result.display_path)
                self._maybe_extract_tasks(note)
        except NotesOSError as exc:
            self._session.record_error(note.id, str(exc))
            logger.warning("Error sorting note %r: %s", note.id, exc)

    def _maybe_extract_tasks(self, note: Note) -> None:
        """Attempt task extraction after a successful move when enabled.

        SC1 short-circuit: returns IMMEDIATELY if
        ``config.features.task_extraction`` is ``False`` (the default).  This
        is the very first check — no extractor, UI, or writer access occurs on
        the disabled path, preserving byte-identical Phase-4 behaviour.

        Also returns immediately when ``_extractor`` or ``_writer`` is ``None``
        (i.e. the controller was constructed without injection — e.g. older
        call sites from Phase 4 tests).

        On the enabled path:

        1. Calls ``_extractor(note.preview)`` to scan for action items.
        2. If tasks found, calls ``ui.prompt_task_selection(tasks)`` for the
           user to choose which to keep.
        3. If the user selected any tasks, calls ``_writer.write(selected)``
           to append them to the daily Markdown file.

        Args:
            note: The :class:`~notes_os.sorter.models.Note` that was just moved.
        """
        # SC1 gate — must be the first line; no other references before this
        if not self._config.features.task_extraction:
            return
        if self._extractor is None or self._writer is None:
            return

        text = note.preview
        tasks = self._extractor(text)
        if not tasks:
            logger.debug("_maybe_extract_tasks: no tasks found in note %r", note.id)
            return

        selected = self._ui.prompt_task_selection(tasks)
        if selected:
            self._writer.write(selected)
            logger.info(
                "_maybe_extract_tasks: wrote %d task(s) for note %r",
                len(selected),
                note.id,
            )
        else:
            logger.debug("_maybe_extract_tasks: user skipped tasks for note %r", note.id)

    def _await_category(self, note: Note) -> RouteResult:
        """Loop at AWAIT_CATEGORY until the router issues MOVE or SKIP.

        Calls ``ui.prompt_category()`` and ``router.handle_category()`` in a
        loop.  On ``help_requested`` calls ``ui.show_help()`` and re-prompts.
        On ``AWAIT_FOLDER`` delegates to :meth:`_await_folder`.

        Args:
            note: The :class:`~notes_os.sorter.models.Note` being sorted.

        Returns:
            A ``RouteResult`` with ``action`` set to ``MOVE`` or ``SKIP``.

        Raises:
            NotesOSError: If the underlying repo raises during a move.
        """
        while True:
            key = self._ui.prompt_category()
            result = self._router.handle_category(key, note)

            if result.help_requested:
                self._ui.show_help()
                continue  # re-prompt without advancing

            if result.action in (RouteAction.MOVE, RouteAction.SKIP):
                return result

            if result.state == RouterState.AWAIT_FOLDER:
                return self._await_folder(result, note)

            # NONE / invalid key — no-op; re-prompt (ROUT-07)
            logger.debug("Invalid or no-op key %r — re-prompting", key)

    def _await_folder(self, prev: RouteResult, note: Note) -> RouteResult:
        """Loop at AWAIT_FOLDER until the user picks a folder (or backs out).

        Calls ``ui.prompt_choice(prev.options)`` and feeds the result to the
        router.  ``None`` from ``prompt_choice`` means back or invalid —
        delegates to :meth:`_handle_back` which re-enters AWAIT_CATEGORY.

        Args:
            prev: The ``RouteResult`` from the preceding ``handle_category`` call.
            note: The :class:`~notes_os.sorter.models.Note` being sorted.

        Returns:
            A ``RouteResult`` with ``action`` set to ``MOVE`` or ``SKIP``.

        Raises:
            NotesOSError: If the underlying repo raises during a move.
        """
        while True:
            choice = self._ui.prompt_choice(prev.options)
            if choice is None:
                # Back requested — return to AWAIT_CATEGORY
                return self._handle_back(RouterState.AWAIT_FOLDER, prev, note)

            result = self._router.handle_folder(choice, prev, note)

            if result.action == RouteAction.MOVE:
                return result

            if result.state == RouterState.AWAIT_SUBFOLDER:
                return self._await_subfolder(result, note)

            # Invalid index — router returned AWAIT_FOLDER; re-prompt
            prev = result

    def _await_subfolder(self, prev: RouteResult, note: Note) -> RouteResult:
        """Loop at AWAIT_SUBFOLDER until the user picks a subfolder (or backs out).

        Calls ``ui.prompt_choice(prev.options)`` and feeds the result to the
        router.  ``None`` returns to AWAIT_FOLDER via :meth:`_handle_back`.

        Args:
            prev: The ``RouteResult`` from the preceding ``handle_folder`` call.
            note: The :class:`~notes_os.sorter.models.Note` being sorted.

        Returns:
            A ``RouteResult`` with ``action`` set to ``MOVE`` or ``SKIP``.

        Raises:
            NotesOSError: If the underlying repo raises during a move.
        """
        while True:
            choice = self._ui.prompt_choice(prev.options)
            if choice is None:
                # Back to AWAIT_FOLDER
                back_result = self._handle_back(RouterState.AWAIT_SUBFOLDER, prev, note)
                if back_result.state == RouterState.AWAIT_FOLDER:
                    return self._await_folder(back_result, note)
                return back_result

            result = self._router.handle_subfolder(choice, prev, note)

            if result.action == RouteAction.MOVE:
                return result

            # Invalid index — re-prompt
            prev = result

    def _handle_back(
        self,
        current_state: RouterState,
        prev: RouteResult,
        note: Note,
    ) -> RouteResult:
        """Delegate [B] back-out to the router and re-enter the appropriate loop.

        Back from AWAIT_FOLDER re-enters the category loop (AWAIT_CATEGORY
        state).  Back from AWAIT_SUBFOLDER returns AWAIT_FOLDER so the caller
        can re-enter the folder loop.

        Args:
            current_state: The state the UI is currently in.
            prev: The current ``RouteResult`` carrying context.
            note: The :class:`~notes_os.sorter.models.Note` being sorted.

        Returns:
            A ``RouteResult`` representing the backed-out state, or the final
            MOVE/SKIP result if the user made a selection after backing out.

        Raises:
            NotesOSError: If the underlying repo raises during a move.
        """
        back_result = self._router.handle_back(current_state, prev)
        if back_result.state == RouterState.AWAIT_CATEGORY:
            return self._await_category(note)
        # AWAIT_FOLDER — return for caller to loop
        return back_result


# ---------------------------------------------------------------------------
# Production factory
# ---------------------------------------------------------------------------


def build_default_controller(config: SorterConfig) -> SortController:
    """Construct a production-wired :class:`SortController` from *config*.

    Wires:

    1. :class:`~notes_os.sorter.notes.AppleScriptNotesRepository` (the real
       Apple Notes bridge) constructed with ``config.bridge``.
    2. Wraps it in :class:`~notes_os.backup.BackingUpNotesRepository` with a
       :class:`~notes_os.backup.BackupManager` built from ``config.backup`` — so
       a backup fires BEFORE every ``move_note`` / ``ensure_folder`` call
       (SC4 backup-then-move, T-04-09 mitigation).
    3. Creates a :class:`~notes_os.sorter.router.Router` with the backing-up
       repo and ``config``, and a :class:`~notes_os.sorter.ui.RichSortUI` for
       the terminal, and a fresh :class:`~notes_os.sorter.session.SortSession`.

    Args:
        config: Frozen :class:`~notes_os.config.SorterConfig` driving all
                production dependencies (bridge, backup, archive, log_dir).

    Returns:
        A fully wired :class:`SortController` ready for ``.run()``.
    """
    from notes_os.backup import BackingUpNotesRepository, BackupManager
    from notes_os.sorter.extractor import TaskWriter, extract_tasks
    from notes_os.sorter.notes import AppleScriptNotesRepository
    from notes_os.sorter.router import Router
    from notes_os.sorter.ui import RichSortUI

    inner = AppleScriptNotesRepository(config.bridge)
    manager = BackupManager(config.backup)
    repo = BackingUpNotesRepository(inner, manager, config.backup)

    router = Router(repo=repo, config=config)
    ui = RichSortUI()
    session = SortSession()
    writer = TaskWriter(config.features.extracted_tasks_dir)

    logger.info(
        "Production controller built — backup dir: %s, log dir: %s",
        config.backup.backup_dir,
        config.log_dir,
    )
    return SortController(
        repo=repo,
        ui=ui,
        session=session,
        router=router,
        config=config,
        extractor=extract_tasks,
        writer=writer,
    )
