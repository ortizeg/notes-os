"""Thin Rich/readchar terminal UI layer for the NotesOS PARA sorter.

Provides the :class:`SortUIProtocol` interface that the integration controller
(plan 04-05) and tests depend on, plus the :class:`RichSortUI` implementation
that renders to a Rich ``Console`` and captures keystrokes via ``readchar``.

Design constraints
------------------
- **No business logic here.** Routing decisions (which key maps to which PARA
  root, what a numeric choice means) belong to the router (plan 04-02).  This
  module only renders and captures.
- **Injectable I/O.** The ``Console``, single-key reader, and line reader are
  all constructor-injected so tests can supply fake implementations without
  blocking on a real terminal.
- **Zero ``print()``.**  All output goes through the injected ``Console``; all
  non-UI diagnostic output goes through the module ``logger``.
- **Coverage target ~70%.**  The thin ``readchar``-blocking lines are the only
  intentionally uncovered paths; all renderable/logic seams are covered via
  fake injected I/O in tests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SortUIProtocol(Protocol):
    """Interface for the PARA sorter terminal UI.

    The integration controller (plan 04-05) depends on this protocol so a
    :class:`FakeUI` can be injected in tests and in offline development.

    All methods return ``None`` unless they capture user input.  Methods that
    capture input are documented with their return type and failure semantics.
    """

    def show_inbox_count(self, count: int) -> None:
        """Display the number of notes in the inbox at session start (UI-04).

        Args:
            count: The number of notes in the inbox.
        """
        ...

    def render_note(self, note: Any) -> None:
        """Render a note's title and Markdown preview to the terminal (UI-01).

        The ``note.preview`` is already HTML-stripped and length-truncated by the
        bridge; this method renders it as Markdown using Rich without any further
        processing.

        Args:
            note: A :class:`~notes_os.sorter.models.Note` instance with
                ``.title: str`` and ``.preview: str`` attributes.
        """
        ...

    def prompt_category(self) -> str:
        """Capture a single category keystroke without requiring Enter (UI-02).

        Reads one key from the terminal, lower-cases it, and returns it.  The
        router interprets the returned character; this method imposes no routing
        semantics.

        Returns:
            A single lower-cased character string.
        """
        ...

    def prompt_choice(self, options: Sequence[str]) -> int | None:
        """Render a numbered list and read a number+Enter selection.

        Renders *options* as a 1-based numbered list, then reads a line from
        stdin.  Parses the input and returns the selected 1-based index, or
        ``None`` for a back request (``b``/``B``) or any invalid/out-of-range
        input so the controller can re-prompt or back out.

        Args:
            options: Ordered sequence of option labels to display.

        Returns:
            1-based index of the selected option, or ``None`` for back/invalid.
        """
        ...

    def show_help(self) -> None:
        """Render the inline PARA quick-reference overlay (UI-03).

        Displays the key bindings without leaving the sort flow — the caller
        re-prompts after this method returns.
        """
        ...

    def show_summary(self, summary: Any) -> None:
        """Render the session summary (seam for plan 04-04 SessionSummary).

        Plan 04-04 will define ``SessionSummary``; this seam accepts ``Any``
        so the controller can call ``ui.show_summary(session.summary)`` without
        coupling the UI module to the session module.  The ``RichSortUI``
        implementation renders the mapping/object's key attributes when
        available and falls back to a plain ``str()`` representation.

        Args:
            summary: A session summary object (duck-typed; will be
                ``SessionSummary`` in plan 04-04).
        """
        ...


# ---------------------------------------------------------------------------
# Help text constant
# ---------------------------------------------------------------------------

_HELP_TEXT = """\
[bold]Key Bindings[/bold]

  [bold cyan]P[/bold cyan]  Projects
  [bold cyan]A[/bold cyan]  Areas
  [bold cyan]R[/bold cyan]  Resources
  [bold cyan]X[/bold cyan]  Archive (auto-year)
  [bold cyan]S[/bold cyan]  Skip (leave in inbox)
  [bold cyan]B[/bold cyan]  Back
  [bold cyan]?[/bold cyan]  Show this help

Enter a number + Enter to select a folder.
"""


# ---------------------------------------------------------------------------
# RichSortUI implementation
# ---------------------------------------------------------------------------


class RichSortUI:
    """Rich/readchar implementation of :class:`SortUIProtocol`.

    Renders to an injected :class:`rich.console.Console` and captures
    keystrokes via an injected key-reader callable (default
    ``readchar.readkey``) and line-reader callable (default ``input``).  All
    I/O is therefore substitutable in tests — no test needs a real terminal.

    Args:
        console:     The :class:`rich.console.Console` to render to.  Defaults
                     to a new ``Console()`` writing to stdout.
        key_reader:  Zero-argument callable that blocks until a key is pressed
                     and returns it as a string.  Defaults to
                     ``readchar.readkey`` (no Enter required).
        line_reader: Zero-argument callable that blocks until a line is entered
                     and returns it (without the trailing newline).  Defaults to
                     the built-in ``input`` with an empty prompt.
    """

    def __init__(
        self,
        console: Console | None = None,
        key_reader: Callable[[], str] | None = None,
        line_reader: Callable[[], str] | None = None,
    ) -> None:
        """Initialise RichSortUI with injectable I/O dependencies.

        Args:
            console:     Rich Console to render to (default: ``Console()``).
            key_reader:  Single-key reader callable (default: ``readchar.readkey``).
            line_reader: Line reader callable (default: ``input``).
        """
        self._console: Console = console if console is not None else Console()

        if key_reader is not None:
            self._key_reader: Callable[[], str] = key_reader
        else:
            import readchar  # deferred so module imports without readchar in test envs

            self._key_reader = readchar.readkey

        if line_reader is not None:
            self._line_reader: Callable[[], str] = line_reader
        else:
            self._line_reader = lambda: input("")  # default line reader: real terminal only

    # ------------------------------------------------------------------
    # SortUIProtocol implementation
    # ------------------------------------------------------------------

    def show_inbox_count(self, count: int) -> None:
        """Display the inbox note count at session start (UI-04).

        Args:
            count: Number of notes in the inbox.
        """
        label = "note" if count == 1 else "notes"
        self._console.print(f"[bold]Inbox:[/bold] {count} {label}")
        logger.debug("Session start — inbox has %d %s", count, label)

    def render_note(self, note: Any) -> None:
        """Render a note's title and Markdown preview (UI-01).

        Prints a Panel containing the note title and a ``rich.markdown.Markdown``
        renderable of ``note.preview``.  The preview is already HTML-stripped
        and truncated by the bridge; this method does NOT re-strip or re-truncate.

        Args:
            note: Object with ``.title: str`` and ``.preview: str``.
        """
        title_text = Text(str(note.title), style="bold blue")
        self._console.print()
        self._console.print(Panel(title_text, expand=False, border_style="blue"))
        if note.preview:
            self._console.print(Markdown(note.preview))
        logger.debug("Rendered note %r", note.title)

    def prompt_category(self) -> str:
        """Capture a single PARA category keystroke (UI-02).

        Reads one keystroke without Enter, lower-cases it, and returns the
        normalized character.  No routing logic; the router interprets the result.

        Returns:
            A single lower-cased character string.
        """
        self._console.print(
            "\n[dim]Category:[/dim] "
            "[[bold cyan]P[/bold cyan]]rojects  "
            "[[bold cyan]A[/bold cyan]]reas  "
            "[[bold cyan]R[/bold cyan]]esources  "
            "[[bold cyan]X[/bold cyan]]-archive  "
            "[[bold cyan]S[/bold cyan]]kip  "
            "[bold cyan]?[/bold cyan] Help",
            end="",
        )
        key = self._key_reader()
        self._console.print()  # newline after captured key
        normalized = key.lower() if len(key) == 1 else key
        logger.debug("Category keystroke captured: %r → %r", key, normalized)
        return normalized

    def prompt_choice(self, options: Sequence[str]) -> int | None:
        """Render a numbered list and read a number+Enter selection.

        Renders *options* as a 1-based numbered list, reads a line, and parses
        the result.  Returns ``None`` for ``b``/``B`` (back) or any
        invalid/out-of-range entry so the controller can re-prompt or back out.
        This is a defensive parse — non-numeric or out-of-range input never
        raises; it always returns ``None`` (T-04-05 mitigation).

        Args:
            options: Ordered sequence of option labels to display.

        Returns:
            1-based index of the selected option, or ``None`` for back/invalid.
        """
        self._console.print()
        for i, label in enumerate(options, start=1):
            self._console.print(f"  [bold]{i}.[/bold] {label}")
        self._console.print("\n[dim]Enter number or [b]ack:[/dim] ", end="")
        raw = self._line_reader().strip()
        self._console.print()
        if raw.lower() == "b":
            logger.debug("prompt_choice: back requested")
            return None
        try:
            choice = int(raw)
        except ValueError:
            logger.debug("prompt_choice: non-numeric input %r → None", raw)
            return None
        if choice < 1 or choice > len(options):
            logger.debug("prompt_choice: out-of-range %d → None", choice)
            return None
        logger.debug("prompt_choice: selected %d", choice)
        return choice

    def show_help(self) -> None:
        """Render the inline PARA quick-reference overlay (UI-03).

        Renders the key binding table inside a Panel and returns; the caller
        re-prompts after this method returns without interrupting the sort flow.
        """
        self._console.print(Panel(_HELP_TEXT, title="Help", border_style="yellow", expand=False))
        logger.debug("Help overlay shown")

    def show_summary(self, summary: Any) -> None:
        """Render the end-of-session summary (forward-compatible seam for 04-04).

        Attempts to render ``summary`` using common ``SessionSummary`` attribute
        names (``moved``, ``skipped``, ``total``); falls back to ``str(summary)``
        if those attributes are absent.  Plan 04-04 will refine this rendering
        once ``SessionSummary`` is defined.

        Args:
            summary: Session summary object (duck-typed; ``SessionSummary`` from
                plan 04-04 or any mapping with ``moved``/``skipped``/``total``).
        """
        self._console.print()
        try:
            moved = summary.moved
            skipped = summary.skipped
            errors = summary.errors
            total = summary.total
            self._console.print(
                f"[bold]Session complete.[/bold]  "
                f"Moved: [green]{moved}[/green]  "
                f"Skipped: [yellow]{skipped}[/yellow]  "
                f"Errors: [red]{errors}[/red]  "
                f"Total: {total}"
            )
        except AttributeError:
            self._console.print(f"[bold]Session complete.[/bold]  {summary!s}")
        logger.debug("Summary shown: %r", summary)
