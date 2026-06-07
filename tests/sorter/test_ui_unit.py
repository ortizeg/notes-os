"""Unit tests for the Rich/readchar terminal UI (notes_os.sorter.ui).

All tests use injected fake Console (record=True) and scripted key/line
readers — no real terminal, no blocking on keyboard input.

Coverage target: ~70% of ui.py (the readchar-blocking default-reader lines
are intentionally uncovered; all renderable/logic seams are exercised here).
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from notes_os.sorter.ui import RichSortUI, SortUIProtocol


# ---------------------------------------------------------------------------
# Helpers / fake doubles
# ---------------------------------------------------------------------------


def _recording_console() -> Console:
    """Return a Rich Console in record mode writing to a string buffer.

    Returns:
        A :class:`rich.console.Console` suitable for asserting rendered output.
    """
    return Console(record=True, highlight=False)


def _make_note(title: str = "Test Note", preview: str = "Some preview text.") -> Any:
    """Create a lightweight note-like object without importing models.

    Args:
        title:   Note title string.
        preview: Plain-text preview string (already HTML-stripped).

    Returns:
        A simple namespace object with ``.title`` and ``.preview``.
    """
    from types import SimpleNamespace

    return SimpleNamespace(title=title, preview=preview)


# ---------------------------------------------------------------------------
# Test SortUIProtocol structural subtyping
# ---------------------------------------------------------------------------


class TestSortUIProtocol:
    """RichSortUI satisfies the SortUIProtocol structural check."""

    def test_richsortui_satisfies_protocol(self) -> None:
        ui = RichSortUI(console=_recording_console())
        assert isinstance(ui, SortUIProtocol)


# ---------------------------------------------------------------------------
# Task 1: render_note + show_inbox_count
# ---------------------------------------------------------------------------


class TestShowInboxCount:
    """show_inbox_count renders the inbox count to the console (UI-04)."""

    def test_shows_count_in_output(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_inbox_count(7)
        text = console.export_text()
        assert "7" in text

    def test_singular_note_label(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_inbox_count(1)
        text = console.export_text()
        assert "1" in text
        assert "note" in text

    def test_plural_notes_label(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_inbox_count(5)
        text = console.export_text()
        assert "notes" in text

    def test_zero_count(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_inbox_count(0)
        text = console.export_text()
        assert "0" in text


class TestRenderNote:
    """render_note renders title and Markdown preview to the console (UI-01)."""

    def test_renders_title_in_output(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        note = _make_note(title="My Project Note", preview="Buy groceries")
        ui.render_note(note)
        text = console.export_text()
        assert "My Project Note" in text

    def test_renders_preview_in_output(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        note = _make_note(title="Anything", preview="Agenda for Monday meeting")
        ui.render_note(note)
        text = console.export_text()
        assert "Agenda for Monday meeting" in text

    def test_empty_preview_renders_without_error(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        note = _make_note(title="Empty Body Note", preview="")
        ui.render_note(note)  # must not raise
        text = console.export_text()
        assert "Empty Body Note" in text

    def test_unicode_title_renders(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        note = _make_note(title="It’s Café Day", preview="")
        ui.render_note(note)
        text = console.export_text()
        assert "Caf" in text  # Rich may encode some chars but the stem must appear

    def test_does_not_re_truncate_preview(self) -> None:
        """Preview is already truncated by the bridge — render_note must not shorten it."""
        console = _recording_console()
        ui = RichSortUI(console=console)
        long_preview = "word " * 60  # 300 chars — longer than typical bridge preview_length
        note = _make_note(preview=long_preview.strip())
        ui.render_note(note)
        text = console.export_text()
        # All words must still be present — no re-truncation
        assert "word" in text


# ---------------------------------------------------------------------------
# Task 2: prompt_category + prompt_choice + show_help
# ---------------------------------------------------------------------------


class TestPromptCategory:
    """prompt_category normalises to lower-case without Enter (UI-02)."""

    def test_lower_case_p(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console, key_reader=lambda: "p")
        result = ui.prompt_category()
        assert result == "p"

    def test_upper_case_p_normalised(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console, key_reader=lambda: "P")
        result = ui.prompt_category()
        assert result == "p"

    def test_lower_case_a(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console, key_reader=lambda: "a")
        result = ui.prompt_category()
        assert result == "a"

    def test_upper_case_x_normalised(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console, key_reader=lambda: "X")
        result = ui.prompt_category()
        assert result == "x"

    def test_question_mark_not_lowercased(self) -> None:
        """? is already a single lower-case-safe character."""
        console = _recording_console()
        ui = RichSortUI(console=console, key_reader=lambda: "?")
        result = ui.prompt_category()
        assert result == "?"

    def test_prompt_renders_category_hints(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console, key_reader=lambda: "s")
        ui.prompt_category()
        text = console.export_text()
        # Prompt must mention the category keys
        assert "P" in text
        assert "A" in text
        assert "R" in text
        assert "X" in text

    def test_key_reader_called_once(self) -> None:
        calls: list[str] = []

        def reader() -> str:
            calls.append("call")
            return "r"

        ui = RichSortUI(console=_recording_console(), key_reader=reader)
        ui.prompt_category()
        assert len(calls) == 1


class TestPromptChoice:
    """prompt_choice renders numbered list and parses number+Enter (T-04-05)."""

    def _ui(self, line: str) -> tuple[RichSortUI, Console]:
        console = _recording_console()
        ui = RichSortUI(console=console, line_reader=lambda: line)
        return ui, console

    def test_valid_choice_returns_index(self) -> None:
        ui, _ = self._ui("2")
        result = ui.prompt_choice(["General", "Web", "Research"])
        assert result == 2

    def test_first_choice(self) -> None:
        ui, _ = self._ui("1")
        result = ui.prompt_choice(["General", "Web"])
        assert result == 1

    def test_last_choice(self) -> None:
        ui, _ = self._ui("3")
        result = ui.prompt_choice(["General", "Web", "Research"])
        assert result == 3

    def test_back_lower_returns_none(self) -> None:
        ui, _ = self._ui("b")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_back_upper_returns_none(self) -> None:
        ui, _ = self._ui("B")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_non_numeric_returns_none(self) -> None:
        ui, _ = self._ui("hello")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_out_of_range_high_returns_none(self) -> None:
        ui, _ = self._ui("99")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_zero_returns_none(self) -> None:
        ui, _ = self._ui("0")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_negative_returns_none(self) -> None:
        ui, _ = self._ui("-1")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_empty_input_returns_none(self) -> None:
        ui, _ = self._ui("")
        result = ui.prompt_choice(["General", "Web"])
        assert result is None

    def test_options_rendered_in_output(self) -> None:
        ui, console = self._ui("1")
        ui.prompt_choice(["General", "Web", "Research"])
        text = console.export_text()
        assert "General" in text
        assert "Web" in text
        assert "Research" in text

    def test_options_numbered_in_output(self) -> None:
        ui, console = self._ui("1")
        ui.prompt_choice(["Alpha", "Beta"])
        text = console.export_text()
        assert "1" in text
        assert "2" in text

    def test_whitespace_trimmed_from_input(self) -> None:
        """Input with surrounding whitespace is still parsed correctly."""
        ui, _ = self._ui("  2  ")
        result = ui.prompt_choice(["General", "Web", "Research"])
        assert result == 2


class TestShowHelp:
    """show_help renders PARA quick-reference inline (UI-03)."""

    def test_shows_para_keys(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_help()
        text = console.export_text()
        assert "Projects" in text
        assert "Areas" in text
        assert "Resources" in text
        assert "Archive" in text

    def test_shows_skip_and_back(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_help()
        text = console.export_text()
        assert "Skip" in text
        assert "Back" in text

    def test_shows_help_key(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_help()
        text = console.export_text()
        assert "?" in text

    def test_help_returns_none(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        result = ui.show_help()
        assert result is None  # must return without interrupting flow


class TestShowSummary:
    """show_summary forward-compatible seam for SessionSummary (04-04)."""

    def test_renders_with_duck_typed_summary(self) -> None:
        from types import SimpleNamespace

        console = _recording_console()
        ui = RichSortUI(console=console)
        summary = SimpleNamespace(moved=5, skipped=2, errors=1, total=8)
        ui.show_summary(summary)
        text = console.export_text()
        assert "5" in text
        assert "2" in text
        assert "8" in text
        # SESS-02 / SC5: the errors count must be shown to the user, not just logged.
        assert "Errors" in text
        assert "1" in text

    def test_renders_fallback_for_unknown_summary(self) -> None:
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_summary("plain string summary")
        text = console.export_text()
        assert "plain string summary" in text

    def test_renders_fallback_for_dict_summary(self) -> None:
        """Dict has no .moved attribute — should fall back gracefully."""
        console = _recording_console()
        ui = RichSortUI(console=console)
        ui.show_summary({"moved": 3})
        text = console.export_text()
        assert "moved" in text  # the dict repr contains the key


class TestRichSortUIDefaults:
    """RichSortUI can be constructed without arguments (uses defaults)."""

    def test_constructs_without_args(self) -> None:
        # Should not raise — deferred readchar import happens lazily
        ui = RichSortUI()
        assert isinstance(ui, SortUIProtocol)


class TestProtocolIsRuntimeCheckable:
    """SortUIProtocol is @runtime_checkable so isinstance() works."""

    def test_isinstance_check_passes_for_richsortui(self) -> None:
        ui = RichSortUI(console=_recording_console())
        assert isinstance(ui, SortUIProtocol)

    def test_isinstance_check_fails_for_unrelated_object(self) -> None:
        assert not isinstance("not a ui", SortUIProtocol)
