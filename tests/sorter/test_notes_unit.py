"""Mocked unit tests for the notes_os.sorter.notes bridge module.

Covers every public function and error branch of AppleScriptNotesRepository,
the _HTMLStripper/_strip_html HTML-stripping cases, and a MockNotesRepository
Protocol read that proves no subprocess is ever called (SC1).

All subprocess.run calls are patched — no osascript process ever spawns.
"""

from __future__ import annotations

import subprocess
import types
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from notes_os.exceptions import FolderNotFoundError, NotesError, NotesMoveError, NotesOSError
from notes_os.sorter.models import BridgeConfig, Note, ParaStructure
from notes_os.sorter.notes import (
    _FIELD_SEP,
    _RECORD_SEP,
    AppleScriptNotesRepository,
    NotesRepositoryProtocol,
    _strip_html,
)


if TYPE_CHECKING:
    from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> types.SimpleNamespace:
    """Build a fake subprocess.run result namespace.

    Args:
        returncode: Exit code to return.
        stdout: Fake stdout text.
        stderr: Fake stderr text.

    Returns:
        A SimpleNamespace with returncode, stdout, stderr attributes.
    """
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _inbox_stdout(records: list[tuple[str, str, str]]) -> str:
    """Build fake get_inbox_notes osascript stdout from a list of (id, title, body) tuples.

    Uses the imported _FIELD_SEP and _RECORD_SEP constants — never hardcodes the char values.

    Args:
        records: List of (note_id, title, body_html) tuples.

    Returns:
        A fake stdout string in the format that get_inbox_notes expects.
    """
    return _RECORD_SEP.join(
        f"{note_id}{_FIELD_SEP}{title}{_FIELD_SEP}{body}" for note_id, title, body in records
    )


def _para_stdout(pairs: list[tuple[str, str | None]]) -> str:
    """Build fake get_para_structure osascript stdout.

    Args:
        pairs: List of (root_name, subfolder_name_or_None) pairs.
               Pass None as subfolder to emit a bare root record.

    Returns:
        A fake stdout string in the format get_para_structure expects.
    """
    records: list[str] = []
    for root, sub in pairs:
        if sub is None:
            records.append(root)
        else:
            records.append(f"{root}{_FIELD_SEP}{sub}")
    return _RECORD_SEP.join(records)


def _default_repo() -> AppleScriptNotesRepository:
    """Return an AppleScriptNotesRepository with default BridgeConfig."""
    return AppleScriptNotesRepository(BridgeConfig())


# ---------------------------------------------------------------------------
# HTML stripping — _strip_html
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "preview_length", "expected"),
    [
        # div tag stripped
        ("<div>hello world</div>", 250, "hello world"),
        # p tag stripped
        ("<p>paragraph text</p>", 250, "paragraph text"),
        # br tag: boundary injected between segments
        ("before<br/>after", 250, "before after"),
        # b and i inline tags stripped
        ("<b>bold</b> and <i>italic</i>", 250, "bold and italic"),
        # ul/li stripped, text preserved
        ("<ul><li>item one</li><li>item two</li></ul>", 250, "item one item two"),
        # named entity decoded
        ("<p>Bread &amp; butter</p>", 250, "Bread & butter"),
        # numeric entity decoded
        ("<p>&#169; 2024</p>", 250, "© 2024"),
        # rsquo named entity
        (
            "<p>Monday&rsquo;s meeting</p>",
            250,
            "Monday’s meeting",
        ),  # intentional: Unicode curly apostrophe expected output
        # truncation: limit 10 on a longer string
        ("Hello, this is a long string", 10, "Hello, thi"),
        # truncation AFTER stripping: tag chars don't count toward length
        ("<div>Hello world</div>", 5, "Hello"),
        # empty string
        ("", 250, ""),
        # whitespace only
        ("   \n\t  ", 250, ""),
        # plain text passthrough (no tags)
        ("Just plain text", 250, "Just plain text"),
        # Unicode passthrough
        ("Café notes", 250, "Café notes"),
        # multiple divs run together without stripping text
        ("<div>Line 1</div><div>Line 2</div>", 250, "Line 1 Line 2"),
    ],
)
def test_strip_html_parametrized(raw: str, preview_length: int, expected: str) -> None:
    """_strip_html strips tags, decodes entities, truncates to preview_length."""
    result = _strip_html(raw, preview_length)
    assert result == expected


# ---------------------------------------------------------------------------
# get_inbox_notes — subprocess mocked
# ---------------------------------------------------------------------------


class TestGetInboxNotes:
    """Tests for AppleScriptNotesRepository.get_inbox_notes."""

    def test_well_formed_multi_record(self) -> None:
        """Well-formed multi-record stdout is parsed into a list of Notes."""
        repo = _default_repo()
        stdout = _inbox_stdout(
            [
                ("id1", "First Note", "<div>Hello</div>"),
                ("id2", "Second Note", "<p>World &amp; more</p>"),
            ]
        )
        result_ns = _make_run_result(stdout=stdout)
        with patch("notes_os.sorter.notes.subprocess.run", return_value=result_ns):
            notes = repo.get_inbox_notes()

        assert len(notes) == 2
        assert notes[0].id == "id1"
        assert notes[0].title == "First Note"
        assert notes[0].preview == "Hello"
        assert notes[1].id == "id2"
        assert notes[1].title == "Second Note"
        assert notes[1].preview == "World & more"

    def test_empty_stdout_returns_empty_list(self) -> None:
        """Empty stdout (empty inbox) returns an empty list."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=""),
        ):
            notes = repo.get_inbox_notes()
        assert notes == []

    def test_whitespace_only_stdout_returns_empty_list(self) -> None:
        """Whitespace-only stdout also returns an empty list."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout="   \n  "),
        ):
            notes = repo.get_inbox_notes()
        assert notes == []

    def test_note_with_empty_body(self) -> None:
        """A note with an empty body has preview == '' and is not skipped."""
        repo = _default_repo()
        # Trailing _FIELD_SEP marks the empty body; must NOT be stripped before split.
        stdout = f"id_empty{_FIELD_SEP}Empty Body Note{_FIELD_SEP}"
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            notes = repo.get_inbox_notes()

        assert len(notes) == 1
        assert notes[0].id == "id_empty"
        assert notes[0].title == "Empty Body Note"
        assert notes[0].body == ""
        assert notes[0].preview == ""

    def test_special_chars_in_title_survive_round_trip(self) -> None:
        """Apostrophes, quotes, and Unicode in titles survive the US/RS round-trip."""
        repo = _default_repo()
        title = "It’s Café Day — Notes"  # intentional: Unicode curly apostrophe in test title
        stdout = _inbox_stdout([("id_uni", title, "<p>body</p>")])
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            notes = repo.get_inbox_notes()

        assert len(notes) == 1
        assert notes[0].title == title

    def test_html_stripped_in_preview(self) -> None:
        """HTML in the note body is stripped in the preview."""
        repo = _default_repo()
        stdout = _inbox_stdout(
            [("id_html", "HTML Note", "<div>Buy <b>groceries</b> &amp; milk</div>")]
        )
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            notes = repo.get_inbox_notes()

        assert notes[0].preview == "Buy groceries & milk"
        assert notes[0].body == "<div>Buy <b>groceries</b> &amp; milk</div>"

    def test_non_zero_returncode_raises_notes_error(self) -> None:
        """Non-zero returncode raises NotesError."""
        repo = _default_repo()
        with (
            patch(
                "notes_os.sorter.notes.subprocess.run",
                return_value=_make_run_result(returncode=1, stderr="error occurred"),
            ),
            pytest.raises(NotesError),
        ):
            repo.get_inbox_notes()

    def test_permission_denied_stderr_raises_notes_error(self) -> None:
        """Permission-denied stderr on non-zero exit raises NotesError."""
        repo = _default_repo()
        with (
            patch(
                "notes_os.sorter.notes.subprocess.run",
                return_value=_make_run_result(
                    returncode=1,
                    stderr="Notes got an error: Not authorized to send Apple events",
                ),
            ),
            pytest.raises(NotesError, match="Not authorized"),
        ):
            repo.get_inbox_notes()

    def test_osascript_timeout_raises_notes_error(self) -> None:
        """A hung osascript (TimeoutExpired) is surfaced as NotesError, not a hang."""
        repo = _default_repo()
        with (
            patch(
                "notes_os.sorter.notes.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["osascript"], timeout=30.0),
            ),
            pytest.raises(NotesError, match="timed out"),
        ):
            repo.get_inbox_notes()

    def test_malformed_record_is_skipped(self) -> None:
        """A record missing the third field is skipped (logged, not raised)."""
        repo = _default_repo()
        # Only two fields: id + title, no body field separator
        malformed = f"id_bad{_FIELD_SEP}Title Only"
        good = _inbox_stdout([("id_good", "Good Note", "<p>ok</p>")])
        stdout = f"{malformed}{_RECORD_SEP}{good}"
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            notes = repo.get_inbox_notes()

        assert len(notes) == 1
        assert notes[0].id == "id_good"

    def test_preview_truncated_to_config_length(self) -> None:
        """Preview is truncated to BridgeConfig.preview_length."""
        cfg = BridgeConfig(preview_length=50)
        repo = AppleScriptNotesRepository(cfg)
        # Body produces more than 50 chars of plain text
        body = "A" * 200
        stdout = _inbox_stdout([("id1", "Long Note", body)])
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            notes = repo.get_inbox_notes()

        assert len(notes[0].preview) == 50


# ---------------------------------------------------------------------------
# get_para_structure — subprocess mocked
# ---------------------------------------------------------------------------


class TestGetParaStructure:
    """Tests for AppleScriptNotesRepository.get_para_structure."""

    def test_all_four_roots_populated_with_subfolders(self) -> None:
        """All four PARA roots appear; subfolders mapped to correct parent."""
        repo = _default_repo()
        stdout = _para_stdout(
            [
                ("Projects", "General"),
                ("Projects", "Web"),
                ("Areas", None),
                ("Resources", None),
                ("Archive", None),
            ]
        )
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            structure = repo.get_para_structure()

        assert "Projects" in structure.roots
        assert "Areas" in structure.roots
        assert "Resources" in structure.roots
        assert "Archive" in structure.roots
        assert structure.subfolders_for("Projects") == ("General", "Web")
        assert structure.subfolders_for("Areas") == ()

    def test_subfolder_mapped_to_correct_parent(self) -> None:
        """Subfolders from one root are not assigned to another."""
        repo = _default_repo()
        stdout = _para_stdout(
            [
                ("Projects", "Alpha"),
                ("Archive", "2025"),
                ("Archive", "2026"),
                ("Areas", None),
                ("Resources", None),
            ]
        )
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            structure = repo.get_para_structure()

        assert structure.subfolders_for("Projects") == ("Alpha",)
        assert structure.subfolders_for("Archive") == ("2025", "2026")
        assert structure.subfolders_for("Areas") == ()

    def test_root_with_no_subfolders_is_present(self) -> None:
        """A root with no subfolders still appears in roots tuple with empty subfolders."""
        repo = _default_repo()
        # All roots bare (no subfolders)
        stdout = _para_stdout(
            [
                ("Projects", None),
                ("Areas", None),
                ("Resources", None),
                ("Archive", None),
            ]
        )
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            structure = repo.get_para_structure()

        for root in ("Projects", "Areas", "Resources", "Archive"):
            assert root in structure.roots
            assert structure.subfolders_for(root) == ()

    def test_childless_root_still_present_in_roots(self) -> None:
        """A root with no children still appears when other roots have subfolders."""
        repo = _default_repo()
        stdout = _para_stdout(
            [
                ("Projects", "Web"),
                ("Areas", None),
                ("Resources", None),
                ("Archive", None),
            ]
        )
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            structure = repo.get_para_structure()

        assert "Areas" in structure.roots
        assert structure.subfolders_for("Areas") == ()

    def test_non_zero_returncode_raises_notes_error(self) -> None:
        """Non-zero returncode raises NotesError."""
        repo = _default_repo()
        with (
            patch(
                "notes_os.sorter.notes.subprocess.run",
                return_value=_make_run_result(returncode=1, stderr="permission denied"),
            ),
            pytest.raises(NotesError),
        ):
            repo.get_para_structure()

    def test_config_roots_always_present_regardless_of_output(self) -> None:
        """Config roots are always present even if not mentioned in stdout."""
        repo = _default_repo()
        # Only Projects appears in stdout; other roots must still be in structure
        stdout = _para_stdout([("Projects", "Alpha")])
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            structure = repo.get_para_structure()

        assert set(structure.roots) == {"Projects", "Areas", "Resources", "Archive"}

    def test_empty_stdout_returns_all_roots_empty(self) -> None:
        """Empty stdout returns structure with all config roots and empty subfolders."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=""),
        ):
            structure = repo.get_para_structure()

        assert set(structure.roots) == {"Projects", "Areas", "Resources", "Archive"}
        for root in structure.roots:
            assert structure.subfolders_for(root) == ()


# ---------------------------------------------------------------------------
# SC1: Protocol read via MockNotesRepository — subprocess.run never called
# ---------------------------------------------------------------------------


class TestProtocolReadViaMock:
    """SC1 proof: reading via NotesRepositoryProtocol using MockNotesRepository calls no AppleScript."""

    def test_mock_repo_read_does_not_call_subprocess(
        self,
        mock_repo: MockNotesRepository,
        sample_notes: list[Note],
    ) -> None:
        """get_inbox_notes via MockNotesRepository returns seeded notes; subprocess.run not called."""
        # Type the variable as the protocol to prove structural compatibility.
        repo: NotesRepositoryProtocol = mock_repo  # type: ignore[assignment]

        with patch("notes_os.sorter.notes.subprocess.run") as mock_run:
            notes = repo.get_inbox_notes()
            mock_run.assert_not_called()

        assert len(notes) == len(sample_notes)
        assert {n.id for n in notes} == {n.id for n in sample_notes}

    def test_mock_repo_is_protocol_instance(self, mock_repo: MockNotesRepository) -> None:
        """MockNotesRepository is an instance of NotesRepositoryProtocol (structural subtyping)."""
        assert isinstance(mock_repo, NotesRepositoryProtocol)

    def test_mock_repo_get_para_structure_does_not_call_subprocess(
        self,
        mock_repo: MockNotesRepository,
        sample_structure: ParaStructure,
    ) -> None:
        """get_para_structure via MockNotesRepository returns seed; no subprocess called."""
        with patch("notes_os.sorter.notes.subprocess.run") as mock_run:
            structure = mock_repo.get_para_structure()
            mock_run.assert_not_called()

        assert structure.roots == sample_structure.roots


# ---------------------------------------------------------------------------
# Coverage gap helpers — lines 332 and 420 (empty record skip branches)
# ---------------------------------------------------------------------------


class TestCoverageGaps:
    """Additional tests to hit coverage-gap branches in get_inbox_notes and get_para_structure."""

    def test_get_inbox_notes_skips_empty_records_in_multi_record_stdout(self) -> None:
        """Empty records interspersed in stdout are skipped (line 332 branch)."""
        repo = _default_repo()
        # A trailing _RECORD_SEP creates an empty trailing record
        good = f"id1{_FIELD_SEP}Title{_FIELD_SEP}body"
        stdout = good + _RECORD_SEP  # trailing separator → empty record at end
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            notes = repo.get_inbox_notes()

        assert len(notes) == 1
        assert notes[0].id == "id1"

    def test_get_para_structure_skips_empty_records_in_stdout(self) -> None:
        """Empty records (from trailing separator) are skipped in get_para_structure (line 420 branch)."""
        repo = _default_repo()
        stdout = f"Projects{_FIELD_SEP}Web{_RECORD_SEP}"  # trailing sep → empty record
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(stdout=stdout),
        ):
            structure = repo.get_para_structure()

        assert "Projects" in structure.roots
        assert structure.subfolders_for("Projects") == ("Web",)


# ---------------------------------------------------------------------------
# move_note — subprocess mocked
# ---------------------------------------------------------------------------


class TestMoveNote:
    """Tests for AppleScriptNotesRepository.move_note."""

    def test_2_level_path_success(self) -> None:
        """move_note with a 2-level path calls osascript and succeeds."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run", return_value=_make_run_result()
        ) as mock_run:
            repo.move_note("note-id-123", ("Projects", "Web"))

        assert mock_run.call_count == 1
        # The script arg is the third element of the osascript call list
        script = mock_run.call_args[0][0][2]  # ["osascript", "-e", script]
        assert 'folder "Web" of folder "Projects"' in script

    def test_3_level_path_success(self) -> None:
        """move_note with a 3-level path builds the correct nested folder reference."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run", return_value=_make_run_result()
        ) as mock_run:
            repo.move_note("note-id-456", ("Projects", "Web", "Research"))

        script = mock_run.call_args[0][0][2]
        assert 'folder "Research" of folder "Web" of folder "Projects"' in script

    def test_success_returns_none(self) -> None:
        """move_note returns None on success."""
        repo = _default_repo()
        with patch("notes_os.sorter.notes.subprocess.run", return_value=_make_run_result()):
            result = repo.move_note("note-id", ("Projects",))

        assert result is None

    def test_folder_not_found_sentinel_raises_folder_not_found_error(self) -> None:
        """FOLDER_NOT_FOUND sentinel in osascript error → FolderNotFoundError."""
        repo = _default_repo()
        # Patch _run_osascript to raise NotesError with the sentinel token
        with (
            patch.object(
                AppleScriptNotesRepository,
                "_run_osascript",
                side_effect=NotesError("Notes got an error: FOLDER_NOT_FOUND"),
            ),
            pytest.raises(FolderNotFoundError),
        ):
            repo.move_note("note-id", ("Projects", "NonExistent"))

    def test_note_not_found_sentinel_raises_notes_move_error(self) -> None:
        """NOTE_NOT_FOUND sentinel in osascript error → NotesMoveError."""
        repo = _default_repo()
        with (
            patch.object(
                AppleScriptNotesRepository,
                "_run_osascript",
                side_effect=NotesError("Notes got an error: NOTE_NOT_FOUND"),
            ),
            pytest.raises(NotesMoveError),
        ):
            repo.move_note("bad-note-id", ("Projects",))

    def test_other_non_zero_raises_notes_error(self) -> None:
        """A non-zero exit for reasons other than sentinels raises plain NotesError."""
        repo = _default_repo()
        with (
            patch(
                "notes_os.sorter.notes.subprocess.run",
                return_value=_make_run_result(returncode=1, stderr="unexpected error"),
            ),
            pytest.raises(NotesError),
        ):
            repo.move_note("note-id", ("Projects",))

    def test_move_note_does_not_call_ensure_folder(self) -> None:
        """move_note must NOT call ensure_folder internally."""
        repo = _default_repo()
        with (
            patch("notes_os.sorter.notes.subprocess.run", return_value=_make_run_result()),
            patch.object(AppleScriptNotesRepository, "ensure_folder") as mock_ensure,
        ):
            repo.move_note("note-id", ("Projects",))
            mock_ensure.assert_not_called()

    def test_folder_not_found_error_is_notes_os_error_subclass(self) -> None:
        """FolderNotFoundError is a NotesOSError so callers can catch the root type."""
        repo = _default_repo()
        with (
            patch.object(
                AppleScriptNotesRepository,
                "_run_osascript",
                side_effect=NotesError("FOLDER_NOT_FOUND"),
            ),
            pytest.raises(NotesOSError),
        ):
            repo.move_note("note-id", ("Archive",))

    def test_notes_move_error_is_notes_os_error_subclass(self) -> None:
        """NotesMoveError is a NotesOSError so callers can catch the root type."""
        repo = _default_repo()
        with (
            patch.object(
                AppleScriptNotesRepository,
                "_run_osascript",
                side_effect=NotesError("NOTE_NOT_FOUND"),
            ),
            pytest.raises(NotesOSError),
        ):
            repo.move_note("note-id", ("Projects",))


# ---------------------------------------------------------------------------
# ensure_folder — subprocess mocked
# ---------------------------------------------------------------------------


class TestEnsureFolder:
    """Tests for AppleScriptNotesRepository.ensure_folder."""

    def test_creates_missing_top_level_folder(self) -> None:
        """ensure_folder calls osascript with a make-folder script for a missing folder."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run", return_value=_make_run_result()
        ) as mock_run:
            repo.ensure_folder(("Archive",))

        script = mock_run.call_args[0][0][2]
        assert "Archive" in script
        assert "make new folder" in script

    def test_idempotent_no_op_when_folder_exists(self) -> None:
        """ensure_folder succeeds without error when the folder already exists (mocked as OK)."""
        repo = _default_repo()
        # osascript returns success regardless (the 'if not exists' guard is in AppleScript)
        with patch(
            "notes_os.sorter.notes.subprocess.run",
            return_value=_make_run_result(),
        ) as mock_run:
            repo.ensure_folder(("Projects",))
            repo.ensure_folder(("Projects",))

        # Called twice (two calls → two osascript invocations, both succeed)
        assert mock_run.call_count == 2

    def test_nested_folder_path(self) -> None:
        """ensure_folder for a 2-level path produces a script with nested make-folder statements."""
        repo = _default_repo()
        with patch(
            "notes_os.sorter.notes.subprocess.run", return_value=_make_run_result()
        ) as mock_run:
            repo.ensure_folder(("Archive", "2026"))

        script = mock_run.call_args[0][0][2]
        assert "Archive" in script
        assert "2026" in script
        assert "make new folder" in script

    def test_non_zero_returncode_raises_notes_error(self) -> None:
        """Non-zero returncode from osascript raises NotesError."""
        repo = _default_repo()
        with (
            patch(
                "notes_os.sorter.notes.subprocess.run",
                return_value=_make_run_result(returncode=1, stderr="access denied"),
            ),
            pytest.raises(NotesError),
        ):
            repo.ensure_folder(("Archive",))


# ---------------------------------------------------------------------------
# SC4: Failing-stub resilience — NotesOSError-catchable
# ---------------------------------------------------------------------------


class TestFailingStubResilience:
    """SC4 proof: a failing osascript stub raises typed errors catchable as NotesOSError."""

    @staticmethod
    def _failing_run(*args: object, **kwargs: object) -> types.SimpleNamespace:
        """Always returns a non-zero result simulating a complete osascript failure."""
        return types.SimpleNamespace(returncode=1, stdout="", stderr="simulated failure")

    def test_notes_error_is_notes_os_error_subclass(self) -> None:
        """NotesError is a NotesOSError subclass so the caller can use a single except clause."""
        assert issubclass(NotesError, NotesOSError)

    def test_folder_not_found_error_hierarchy(self) -> None:
        """FolderNotFoundError inherits from NotesError and NotesOSError."""
        assert issubclass(FolderNotFoundError, NotesError)
        assert issubclass(FolderNotFoundError, NotesOSError)

    def test_notes_move_error_hierarchy(self) -> None:
        """NotesMoveError inherits from NotesError and NotesOSError."""
        assert issubclass(NotesMoveError, NotesError)
        assert issubclass(NotesMoveError, NotesOSError)

    def test_failing_osascript_raises_typed_error_and_session_continues(self) -> None:
        """A failing osascript raises NotesOSError; catching it allows the session to continue (SC4)."""
        repo = _default_repo()
        session_continued = False

        with patch("notes_os.sorter.notes.subprocess.run", side_effect=self._failing_run):
            try:
                repo.get_inbox_notes()
            except NotesOSError:
                session_continued = True

        assert session_continued, "Session must continue after catching NotesOSError"

    def test_move_note_failure_catchable_as_notes_os_error(self) -> None:
        """move_note failure (non-zero) is catchable as NotesOSError; session continues."""
        repo = _default_repo()
        session_continued = False

        with patch("notes_os.sorter.notes.subprocess.run", side_effect=self._failing_run):
            try:
                repo.move_note("any-id", ("Projects",))
            except NotesOSError:
                session_continued = True

        assert session_continued

    def test_ensure_folder_failure_catchable_as_notes_os_error(self) -> None:
        """ensure_folder failure is catchable as NotesOSError; session continues."""
        repo = _default_repo()
        session_continued = False

        with patch("notes_os.sorter.notes.subprocess.run", side_effect=self._failing_run):
            try:
                repo.ensure_folder(("Archive",))
            except NotesOSError:
                session_continued = True

        assert session_continued

    def test_folder_not_found_catchable_via_notes_os_error(self) -> None:
        """FolderNotFoundError from move_note is catchable as NotesOSError (SC4 typed hierarchy)."""
        repo = _default_repo()
        caught_type: type | None = None

        with patch.object(
            AppleScriptNotesRepository,
            "_run_osascript",
            side_effect=NotesError("FOLDER_NOT_FOUND"),
        ):
            try:
                repo.move_note("note-id", ("NonExistent",))
            except NotesOSError as exc:
                caught_type = type(exc)

        assert caught_type is FolderNotFoundError
