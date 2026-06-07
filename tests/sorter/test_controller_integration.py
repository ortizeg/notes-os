"""Full-loop integration test for SortController (SC2-SC5).

Exercises ``SortController`` end-to-end using a ``FakeUI`` (scripted
keystrokes/choices, records all calls) and the ``MockNotesRepository``
(in-memory, no AppleScript).  Proves:

- SC2: P/A/R/X/S and [B] back-out all route correctly through the controller.
- SC3: Numbered folder / subfolder selection flows work.
- SC4: Moves land on the correct resolved FolderPath (backup-then-move wiring
  verified at the controller level — FakeUI + MockRepo means no real backup;
  the controller-level logic is proven here; production wiring proven by the
  build_default_controller factory in controller.py).
- SC5: Session summary counts are correct; write_log creates a correctly named
  file under tmp_path with the expected counts.

No ``@pytest.mark.integration`` — all I/O is faked; no AppleScript, no
terminal, no real filesystem except a ``tmp_path`` for log_dir.  Runs in CI.
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING, Any

import pytest

from notes_os.config import ArchiveConfig, SorterConfig
from notes_os.sorter.controller import SortController
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.router import Router
from notes_os.sorter.session import SortSession
from tests.sorter.conftest import MockNotesRepository


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# FakeUI — scripted SortUIProtocol implementation
# ---------------------------------------------------------------------------


class FakeUI:
    """Scripted implementation of :class:`~notes_os.sorter.ui.SortUIProtocol`.

    Feeds pre-programmed keystrokes (for ``prompt_category``) and choice
    indices (for ``prompt_choice``) from a queue.  Records every call for
    post-test assertions.

    Args:
        category_keys: Sequence of strings to return from successive
            ``prompt_category`` calls (FIFO).
        choices: Sequence of ``int | None`` to return from successive
            ``prompt_choice`` calls (FIFO). ``None`` signals back/invalid.
    """

    def __init__(
        self,
        category_keys: list[str],
        choices: list[int | None],
    ) -> None:
        """Initialise FakeUI with pre-programmed inputs.

        Args:
            category_keys: Ordered list of category keystrokes to return.
            choices: Ordered list of numeric choices (or ``None`` for back).
        """
        self._category_keys: deque[str] = deque(category_keys)
        self._choices: deque[int | None] = deque(choices)

        # Call-recording attributes
        self.inbox_count_arg: int | None = None
        self.rendered_titles: list[str] = []
        self.show_help_count: int = 0
        self.show_summary_arg: Any = None

    # ------------------------------------------------------------------
    # SortUIProtocol methods
    # ------------------------------------------------------------------

    def show_inbox_count(self, count: int) -> None:
        """Record the inbox count passed at session start (UI-04).

        Args:
            count: Number of notes in the inbox.
        """
        self.inbox_count_arg = count

    def render_note(self, note: Any) -> None:
        """Record the title of each rendered note (UI-01).

        Args:
            note: Note object with a ``.title`` attribute.
        """
        self.rendered_titles.append(note.title)

    def prompt_category(self) -> str:
        """Return the next scripted keystroke from the queue (UI-02).

        Returns:
            Next pre-programmed keystroke string.

        Raises:
            IndexError: If the queue is exhausted before the test ends.
        """
        return self._category_keys.popleft()

    def prompt_choice(self, options: Any) -> int | None:
        """Return the next scripted choice from the queue.

        Args:
            options: The option list displayed (not inspected — test controls
                which index to return).

        Returns:
            Next pre-programmed int choice (1-based) or ``None`` for back.

        Raises:
            IndexError: If the queue is exhausted before the test ends.
        """
        return self._choices.popleft()

    def show_help(self) -> None:
        """Record that help was shown (UI-03)."""
        self.show_help_count += 1

    def show_summary(self, summary: Any) -> None:
        """Record the summary object passed at session end (SESS-02).

        Args:
            summary: Session summary (``SessionSummary`` in production).
        """
        self.show_summary_arg = summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def structure_with_subs() -> ParaStructure:
    """Return a ParaStructure with a 3-level hierarchy under Projects/General.

    Projects:
      - General (leaf — no sub-subfolders for most tests)
      - Web
        - Research  ← sub-subfolder; triggers AWAIT_SUBFOLDER
    Areas, Resources, Archive: no subfolders (auto-move to root).

    Returns:
        A :class:`~notes_os.sorter.models.ParaStructure` with the above layout.
    """
    return ParaStructure(
        roots=("Projects", "Areas", "Resources", "Archive"),
        subfolders={
            "Projects": ("General", "Web"),
            "Areas": (),
            "Resources": (),
            "Archive": (),
            # Sub-subfolder key: "Projects/Web" has one child "Research"
            "Projects/Web": ("Research",),
        },
    )


@pytest.fixture()
def three_notes() -> list[Note]:
    """Three notes representing the scripted triage session.

    Returns:
        A list of three ``Note`` instances.
    """
    return [
        Note(id="n1", title="Project Note", body="", preview=""),
        Note(id="n2", title="To Be Skipped", body="", preview=""),
        Note(id="n3", title="Archive Me", body="", preview=""),
    ]


@pytest.fixture()
def mock_repo_subs(
    three_notes: list[Note],
    structure_with_subs: ParaStructure,
) -> MockNotesRepository:
    """Mock repo seeded with three notes and the sub-subfolder structure.

    Args:
        three_notes: The ``three_notes`` fixture.
        structure_with_subs: The ``structure_with_subs`` fixture.

    Returns:
        A :class:`~tests.sorter.conftest.MockNotesRepository` for the integration test.
    """
    return MockNotesRepository(notes=three_notes, structure=structure_with_subs)


def _build_config(log_dir: Path) -> SorterConfig:
    """Build a minimal SorterConfig with *log_dir* and archive='Archive'.

    Args:
        log_dir: Directory to write audit logs during the test.

    Returns:
        A frozen :class:`~notes_os.config.SorterConfig` instance.
    """
    return SorterConfig(
        archive=ArchiveConfig(base_folder="Archive", auto_year=True), log_dir=log_dir
    )


# ---------------------------------------------------------------------------
# Full-loop test
# ---------------------------------------------------------------------------


class TestFullLoopSortSession:
    """End-to-end SortController test proving SC2-SC5 via FakeUI + MockRepo."""

    def test_move_skip_archive_back_help_invalid(
        self,
        mock_repo_subs: MockNotesRepository,
        structure_with_subs: ParaStructure,
        tmp_path: Path,
    ) -> None:
        """Full loop: move n1 to Projects/Web/Research (back-out + re-select),
        skip n2, archive n3 (X). Include help re-prompt and one invalid key.

        Script for note n1 (Project → subfolder path, with back-out):
          Category:  '?'  → help overlay, re-prompt
          Category:  'z'  → invalid key, re-prompt (ROUT-07 no-op)
          Category:  'p'  → Projects → AWAIT_FOLDER (options: General, Web)
          Choice 1:  2    → Web selected → AWAIT_SUBFOLDER (options: Research)
              (back-out here to test ROUT-06 [B]):
          Choice 2:  None → back to AWAIT_FOLDER
          Choice 3:  2    → Web again → AWAIT_SUBFOLDER
          Choice 4:  1    → Research → MOVE n1 to (Projects, Web, Research)

        Script for note n2 (Skip):
          Category:  's'  → SKIP

        Script for note n3 (Archive/X):
          Category:  'x'  → MOVE to (Archive, 2031)

        Asserts:
          - show_inbox_count called with 3
          - show_help called exactly once
          - mock_repo.moves contains n1 to (Projects, Web, Research) and n3 to (Archive, 2031)
          - mock_repo.created_folders contains (Archive, 2031)
          - session summary: moved=2, skipped=1, errors=0
          - write_log created a YYYY-MM-DD_HH-MM-SS.log in tmp_path with counts
        """
        config = _build_config(tmp_path)

        # Script: n1 → ?, z (no-op), p → AWAIT_FOLDER → subfolder flow
        #         n2 → s (skip); n3 → x (archive)
        category_keys = ["?", "z", "p", "s", "x"]

        # prompt_choice calls for n1:
        #   2 → Web (AWAIT_FOLDER); None → back; 2 → Web again; 1 → Research (AWAIT_SUBFOLDER)
        choices: list[int | None] = [2, None, 2, 1]

        fake_ui = FakeUI(category_keys=category_keys, choices=choices)
        session = SortSession()
        router = Router(
            repo=mock_repo_subs,
            config=config,
            year_provider=lambda: 2031,  # deterministic archive year
        )
        controller = SortController(
            repo=mock_repo_subs,
            ui=fake_ui,
            session=session,
            router=router,
            config=config,
        )

        controller.run()

        # --- UI assertions ---
        assert fake_ui.inbox_count_arg == 3, "show_inbox_count must be called with 3 (UI-04)"
        assert fake_ui.show_help_count == 1, "show_help called exactly once for '?' (UI-03)"
        assert fake_ui.rendered_titles == [
            "Project Note",
            "To Be Skipped",
            "Archive Me",
        ], "All three notes rendered in inbox order (UI-01)"
        assert fake_ui.show_summary_arg is not None, "show_summary must be called (SESS-02)"

        # --- Move assertions (SC2/SC3/SC4) ---
        assert len(mock_repo_subs.moves) == 2, "Exactly two notes moved"
        move_ids = [m[0] for m in mock_repo_subs.moves]
        move_paths = [m[1] for m in mock_repo_subs.moves]
        assert "n1" in move_ids, "n1 (Project note) was moved"
        assert "n3" in move_ids, "n3 (Archive note) was moved"
        assert ("Projects", "Web", "Research") in move_paths, (
            "n1 resolved to 3-level Projects/Web/Research path (SC3)"
        )
        assert ("Archive", "2031") in move_paths, "n3 archived to Archive/2031 (ROUT-02)"

        # n2 stays in inbox (skip)
        remaining = mock_repo_subs.get_inbox_notes()
        assert len(remaining) == 1
        assert remaining[0].id == "n2", "Skipped note n2 remains in inbox (SC2)"

        # ensure_folder was called for (Archive, 2031) — archive year auto-created
        assert ("Archive", "2031") in mock_repo_subs.created_folders, (
            "ensure_folder(Archive, 2031) called before archive move (SC4)"
        )

        # --- Session summary (SESS-01/02) ---
        summary = session.summary()
        assert summary.moved == 2, "Session records 2 moves"
        assert summary.skipped == 1, "Session records 1 skip"
        assert summary.errors == 0, "Session records 0 errors"
        assert summary.total == 3, "total == moved + skipped + errors"

        # show_summary received the SessionSummary
        assert fake_ui.show_summary_arg.moved == 2
        assert fake_ui.show_summary_arg.skipped == 1

        # --- Log file (SESS-03) ---
        log_files = list(tmp_path.iterdir())
        assert len(log_files) == 1, "Exactly one log file written"
        log_file = log_files[0]
        assert re.match(
            r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log",
            log_file.name,
        ), f"Log filename must match YYYY-MM-DD_HH-MM-SS.log format; got {log_file.name!r}"

        log_text = log_file.read_text(encoding="utf-8")
        assert "Moved:   2" in log_text, "Log records 2 moves"
        assert "Skipped: 1" in log_text, "Log records 1 skip"
        assert "Errors:  0" in log_text, "Log records 0 errors"
        assert "Total:   3" in log_text, "Log records total 3"


class TestSortControllerEdgeCases:
    """Additional focused tests for controller edge cases."""

    def test_help_reprompt_does_not_advance_note(
        self,
        tmp_path: Path,
        structure_with_subs: ParaStructure,
    ) -> None:
        """'?' triggers show_help and re-prompts without advancing to next note.

        Sends multiple help keys before a valid 's' (skip) to verify that each
        '?' increments show_help_count while the note position stays the same.
        """
        note = Note(id="h1", title="Help Test", body="", preview="")
        repo = MockNotesRepository(notes=[note], structure=structure_with_subs)
        config = _build_config(tmp_path)
        # Three '?' then 's' to skip
        fake_ui = FakeUI(category_keys=["?", "?", "?", "s"], choices=[])
        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2031)
        controller = SortController(
            repo=repo, ui=fake_ui, session=session, router=router, config=config
        )

        controller.run()

        assert fake_ui.show_help_count == 3, "show_help called three times (one per '?')"
        assert session.summary().skipped == 1, "Note was eventually skipped"
        assert session.summary().moved == 0

    def test_invalid_key_is_noop(
        self,
        tmp_path: Path,
        structure_with_subs: ParaStructure,
    ) -> None:
        """An unrecognised key at AWAIT_CATEGORY is a no-op (ROUT-07).

        Sends 'z', 'm', '9' before a valid 'x' (archive) to verify no state
        changes and no errors.
        """
        note = Note(id="z1", title="Invalid Key Test", body="", preview="")
        repo = MockNotesRepository(notes=[note], structure=structure_with_subs)
        config = _build_config(tmp_path)
        fake_ui = FakeUI(category_keys=["z", "m", "9", "x"], choices=[])
        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2031)
        controller = SortController(
            repo=repo, ui=fake_ui, session=session, router=router, config=config
        )

        controller.run()

        assert session.summary().moved == 1, "Note eventually archived"
        assert session.summary().errors == 0

    def test_error_does_not_abort_session(
        self,
        tmp_path: Path,
        structure_with_subs: ParaStructure,
    ) -> None:
        """A NotesOSError on one note is recorded and the session continues.

        Uses two notes.  The first note selects a folder that is NOT in the
        known_paths of the mock — causing MockNotesRepository.move_note to raise
        ``FolderNotFoundError`` (a NotesOSError subclass).  The second note is
        then skipped successfully, proving the loop continued (T-04-10).
        """
        from notes_os.exceptions import NotesOSError

        class FailingRepo(MockNotesRepository):
            """MockNotesRepository that raises on the first move_note call."""

            def __init__(self, notes: list[Note], structure: ParaStructure) -> None:
                """Delegate to parent; set failure flag.

                Args:
                    notes: Seed notes.
                    structure: Seed structure.
                """
                super().__init__(notes=notes, structure=structure)
                self._fail_next_move = True

            def move_note(self, note_id: str, folder_path: tuple[str, ...]) -> None:
                """Raise NotesOSError on first call; succeed on subsequent calls.

                Args:
                    note_id: Note identifier.
                    folder_path: Destination folder path.

                Raises:
                    NotesOSError: On the first call only.
                """
                if self._fail_next_move:
                    self._fail_next_move = False
                    raise NotesOSError("simulated write failure")
                super().move_note(note_id, folder_path)

        note1 = Note(id="e1", title="Will Error", body="", preview="")
        note2 = Note(id="e2", title="Will Skip", body="", preview="")
        repo = FailingRepo(notes=[note1, note2], structure=structure_with_subs)
        config = _build_config(tmp_path)
        # note1: 'x' → archive → move_note fails → error recorded
        # note2: 's' → skip
        fake_ui = FakeUI(category_keys=["x", "s"], choices=[])
        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2031)
        controller = SortController(
            repo=repo, ui=fake_ui, session=session, router=router, config=config
        )

        controller.run()

        summary = session.summary()
        assert summary.errors == 1, "Error from note1 recorded"
        assert summary.skipped == 1, "note2 still skipped — session continued (T-04-10)"
        assert summary.moved == 0

    def test_back_from_await_folder_returns_to_category(
        self,
        tmp_path: Path,
        structure_with_subs: ParaStructure,
    ) -> None:
        """[B] at AWAIT_FOLDER returns to AWAIT_CATEGORY and re-prompts (ROUT-06).

        Script: 'p' → AWAIT_FOLDER; back (None) → AWAIT_CATEGORY;
        's' → skip.  Verifies no move happened.
        """
        note = Note(id="b1", title="Back Test", body="", preview="")
        repo = MockNotesRepository(notes=[note], structure=structure_with_subs)
        config = _build_config(tmp_path)
        # category: p, then after back re-prompts: s
        fake_ui = FakeUI(category_keys=["p", "s"], choices=[None])  # None = back at AWAIT_FOLDER
        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2031)
        controller = SortController(
            repo=repo, ui=fake_ui, session=session, router=router, config=config
        )

        controller.run()

        assert session.summary().moved == 0, "No move after back-out"
        assert session.summary().skipped == 1, "Note skipped after back-out to category"

    def test_empty_inbox(
        self,
        tmp_path: Path,
        structure_with_subs: ParaStructure,
    ) -> None:
        """An empty inbox calls show_inbox_count(0) and writes an empty-log immediately.

        No ``prompt_category`` calls should be made for an empty inbox.
        """
        repo = MockNotesRepository(notes=[], structure=structure_with_subs)
        config = _build_config(tmp_path)
        fake_ui = FakeUI(category_keys=[], choices=[])
        session = SortSession()
        router = Router(repo=repo, config=config, year_provider=lambda: 2031)
        controller = SortController(
            repo=repo, ui=fake_ui, session=session, router=router, config=config
        )

        controller.run()

        assert fake_ui.inbox_count_arg == 0
        assert session.summary().total == 0
        log_files = list(tmp_path.iterdir())
        assert len(log_files) == 1, "Log written even for empty session"
