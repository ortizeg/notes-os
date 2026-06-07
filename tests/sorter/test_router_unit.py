"""Unit tests for the PARA router state machine (notes_os.sorter.router).

Covers all state transitions (ROUT-01..08) using MockNotesRepository — no
AppleScript, no terminal I/O.  Tests are grouped by transition type so each
requirement is exercised in isolation.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from notes_os.config import ArchiveConfig, SorterConfig
from notes_os.sorter.models import Note, ParaStructure
from notes_os.sorter.router import RouteAction, Router, RouteResult, RouterState
from tests.sorter.conftest import MockNotesRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(note_id: str = "id1") -> Note:
    """Return a minimal Note for testing."""
    return Note(id=note_id, title="Test Note", body="<p>body</p>", preview="body")


def _config(archive_base: str = "Archive") -> SorterConfig:
    """Return a SorterConfig with the given archive base folder name."""
    return SorterConfig(archive=ArchiveConfig(base_folder=archive_base))


# ---------------------------------------------------------------------------
# Task 1 tests: RouterState enum + RouteResult + category transition (ROUT-01, ROUT-07)
# ---------------------------------------------------------------------------


class TestRouterStateEnum:
    """RouterState has exactly the required states."""

    def test_all_states_exist(self) -> None:
        states = {s.name for s in RouterState}
        assert states == {
            "SHOW_NOTE",
            "AWAIT_CATEGORY",
            "AWAIT_FOLDER",
            "AWAIT_SUBFOLDER",
            "CONFIRM_MOVE",
        }

    def test_states_are_distinct(self) -> None:
        values = [s.value for s in RouterState]
        assert len(values) == len(set(values))


class TestRouteActionEnum:
    """RouteAction has MOVE, SKIP, NONE."""

    def test_all_actions_exist(self) -> None:
        actions = {a.name for a in RouteAction}
        assert actions == {"MOVE", "SKIP", "NONE"}


class TestRouteResultModel:
    """RouteResult is a frozen Pydantic model with required fields."""

    def test_minimal_construction(self) -> None:
        r = RouteResult(state=RouterState.AWAIT_CATEGORY)
        assert r.state == RouterState.AWAIT_CATEGORY
        assert r.action is None
        assert r.folder_path is None
        assert r.display_path is None
        assert r.options == ()
        assert r.help_requested is False

    def test_immutable(self) -> None:
        r = RouteResult(state=RouterState.AWAIT_CATEGORY)
        with pytest.raises(ValidationError):
            r.state = RouterState.SHOW_NOTE  # type: ignore[misc]


class TestAwaitCategoryTransition:
    """AWAIT_CATEGORY → P/A/R/X/S/?/invalid transitions (ROUT-01, ROUT-07)."""

    def setup_method(self) -> None:
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        self.repo = MockNotesRepository(notes=notes, structure=structure)
        self.cfg = _config()
        self.router = Router(
            repo=self.repo,
            config=self.cfg,
            year_provider=lambda: 2031,
        )
        self.note = _note("id1")

    def test_p_lower_moves_to_await_folder_projects(self) -> None:
        result = self.router.handle_category("p", self.note)
        assert result.state == RouterState.AWAIT_FOLDER
        assert result.action is None

    def test_P_upper_moves_to_await_folder_projects(self) -> None:
        result = self.router.handle_category("P", self.note)
        assert result.state == RouterState.AWAIT_FOLDER

    def test_p_selected_root_is_projects(self) -> None:
        result = self.router.handle_category("p", self.note)
        # The router must record which root was selected — check via selected_root attribute
        assert result.selected_root == "Projects"

    def test_a_lower_moves_directly_when_no_folders(self) -> None:
        """Areas has no sub-folders → router moves directly to root ('Areas',)."""
        result = self.router.handle_category("a", self.note)
        # Areas has no sub-folders in the fixture, so auto-move to root
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE
        assert result.folder_path == ("Areas",)

    def test_A_upper_moves_directly_when_no_folders(self) -> None:
        result = self.router.handle_category("A", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE
        assert result.folder_path == ("Areas",)

    def test_a_moves_to_await_folder_when_areas_has_subfolders(self) -> None:
        """When Areas has sub-folders, A goes to AWAIT_FOLDER."""
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Areas": ("Finance", "Health"),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        result = router.handle_category("a", self.note)
        assert result.state == RouterState.AWAIT_FOLDER
        assert result.selected_root == "Areas"

    def test_r_lower_moves_directly_when_no_folders(self) -> None:
        """Resources has no sub-folders → moves directly to root."""
        result = self.router.handle_category("r", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE
        assert result.folder_path == ("Resources",)

    def test_R_upper_moves_directly_when_no_folders(self) -> None:
        result = self.router.handle_category("R", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE
        assert result.folder_path == ("Resources",)

    def test_r_moves_to_await_folder_when_resources_has_subfolders(self) -> None:
        """When Resources has sub-folders, R goes to AWAIT_FOLDER."""
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General",),
                "Areas": (),
                "Resources": ("Books", "Tools"),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        result = router.handle_category("r", self.note)
        assert result.state == RouterState.AWAIT_FOLDER
        assert result.selected_root == "Resources"

    def test_s_lower_emits_skip_returns_show_note(self) -> None:
        result = self.router.handle_category("s", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.SKIP

    def test_S_upper_emits_skip(self) -> None:
        result = self.router.handle_category("S", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.SKIP

    def test_skip_does_not_call_repo(self) -> None:
        self.router.handle_category("s", self.note)
        assert len(self.repo.moves) == 0
        assert len(self.repo.created_folders) == 0

    def test_question_mark_sets_help_requested_state_unchanged(self) -> None:
        result = self.router.handle_category("?", self.note)
        assert result.state == RouterState.AWAIT_CATEGORY
        assert result.help_requested is True

    def test_invalid_key_z_state_unchanged(self) -> None:
        result = self.router.handle_category("z", self.note)
        assert result.state == RouterState.AWAIT_CATEGORY
        assert result.action is None or result.action == RouteAction.NONE

    def test_invalid_key_digit_state_unchanged(self) -> None:
        result = self.router.handle_category("1", self.note)
        assert result.state == RouterState.AWAIT_CATEGORY

    def test_invalid_key_does_not_call_repo(self) -> None:
        self.router.handle_category("z", self.note)
        assert len(self.repo.moves) == 0


# ---------------------------------------------------------------------------
# Task 2 tests: Archive auto-year (X) with injected year_provider (ROUT-02, ROUT-08)
# ---------------------------------------------------------------------------


class TestArchiveAutoYear:
    """X auto-resolves to (archive_base, year) — ROUT-02."""

    def setup_method(self) -> None:
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        self.repo = MockNotesRepository(notes=notes, structure=structure)
        self.cfg = _config()
        self.router = Router(
            repo=self.repo,
            config=self.cfg,
            year_provider=lambda: 2031,
        )
        self.note = _note("id1")

    def test_x_lower_returns_show_note_with_move(self) -> None:
        result = self.router.handle_category("x", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE

    def test_X_upper_returns_show_note_with_move(self) -> None:
        result = self.router.handle_category("X", self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE

    def test_x_folder_path_is_archive_year(self) -> None:
        result = self.router.handle_category("x", self.note)
        assert result.folder_path == ("Archive", "2031")

    def test_x_display_path_uses_separator(self) -> None:
        result = self.router.handle_category("x", self.note)
        assert result.display_path == "Archive › 2031"

    def test_x_ensure_folder_called_before_move(self) -> None:
        self.router.handle_category("x", self.note)
        # ensure_folder records in created_folders only if path was not already known
        assert ("Archive", "2031") in self.repo.created_folders
        assert len(self.repo.moves) == 1
        assert self.repo.moves[0] == ("id1", ("Archive", "2031"))

    def test_x_ensure_folder_called_before_move_ordering(self) -> None:
        """ensure_folder is invoked BEFORE move_note (critical order)."""
        call_order: list[str] = []
        original_ensure = self.repo.ensure_folder
        original_move = self.repo.move_note

        def tracked_ensure(path: tuple[str, ...]) -> None:
            call_order.append("ensure_folder")
            original_ensure(path)

        def tracked_move(note_id: str, path: tuple[str, ...]) -> None:
            call_order.append("move_note")
            original_move(note_id, path)

        self.repo.ensure_folder = tracked_ensure  # type: ignore[method-assign]
        self.repo.move_note = tracked_move  # type: ignore[method-assign]
        self.router.handle_category("x", self.note)
        assert call_order == ["ensure_folder", "move_note"]

    def test_x_custom_archive_base_folder(self) -> None:
        cfg = _config(archive_base="Archiv")
        router = Router(repo=self.repo, config=cfg, year_provider=lambda: 2031)
        result = router.handle_category("x", _note("id1"))
        assert result.folder_path == ("Archiv", "2031")
        assert result.display_path == "Archiv › 2031"

    def test_x_year_from_injected_provider(self) -> None:
        router = Router(repo=self.repo, config=self.cfg, year_provider=lambda: 1999)
        result = router.handle_category("x", self.note)
        assert result.folder_path == ("Archive", "1999")

    def test_default_year_provider_is_callable(self) -> None:
        """Router constructs without year_provider (uses datetime.now().year)."""
        router = Router(repo=self.repo, config=self.cfg)
        # Just verify it doesn't raise; year will be current year
        result = router.handle_category("x", _note("id1"))
        assert result.action == RouteAction.MOVE
        assert result.folder_path == ("Archive", str(datetime.datetime.now().year))


# ---------------------------------------------------------------------------
# Task 3 tests: Folder + subfolder selection, [B] back-out (ROUT-03..08)
# ---------------------------------------------------------------------------


class TestAwaitFolderTransition:
    """AWAIT_FOLDER: numbered selection + [B] back (ROUT-03, ROUT-04, ROUT-05, ROUT-06, ROUT-07)."""

    def setup_method(self) -> None:
        # Projects has subfolders (General, Web); Areas has none
        self.structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        self.repo = MockNotesRepository(notes=notes, structure=self.structure)
        self.cfg = _config()
        self.router = Router(repo=self.repo, config=self.cfg, year_provider=lambda: 2031)
        self.note = _note("id1")

    def test_projects_options_populated_on_p(self) -> None:
        result = self.router.handle_category("p", self.note)
        # options should be the folder list for Projects
        assert "General" in result.options
        assert "Web" in result.options

    def test_areas_has_no_folders_option_is_empty(self) -> None:
        result = self.router.handle_category("a", self.note)
        # Areas has no subfolders — options is empty
        assert result.options == ()

    def test_areas_no_subfolders_immediately_moves(self) -> None:
        """Selecting Areas (no subfolders) immediately issues the move to ("Areas",)."""
        # Areas has no subfolders — router should auto-move on folder selection
        # Actually per ROUT-05: "folders WITHOUT [subfolders] move immediately"
        # But "folder" here means the top-level PARA root — Areas has no sub-folders
        # So selecting Areas (via 'a') has no folders to choose from;
        # the router should handle this: if folder_list is empty, move directly to root.
        # Check: after handle_category('a'), if options is empty => move to ("Areas",)
        result = self.router.handle_category("a", self.note)
        if not result.options:
            # no folders to pick — move immediately
            assert result.state == RouterState.SHOW_NOTE
            assert result.action == RouteAction.MOVE
            assert result.folder_path == ("Areas",)

    def test_folder_with_subfolders_goes_to_await_subfolder(self) -> None:
        """Selecting folder 1 (General) under Projects (which has sub-subfolders) → AWAIT_SUBFOLDER."""
        # Need a 3-level structure: Projects → General → (Research, Docs)
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Projects/General": ("Research", "Docs"),  # sub-subfolders
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        cat_result = router.handle_category("p", self.note)
        assert cat_result.state == RouterState.AWAIT_FOLDER
        # Now select folder index 1 (General — General is first)
        result = router.handle_folder(1, cat_result, self.note)
        assert result.state == RouterState.AWAIT_SUBFOLDER

    def test_folder_without_subfolders_moves_immediately(self) -> None:
        """Selecting a folder with no children moves immediately (ROUT-05)."""
        # Areas root itself has no sub-subfolders; if we got there, move immediately
        # Use a structure where Projects→Web has no further children
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={"Projects": ("Web",), "Areas": (), "Resources": (), "Archive": ()},
        )
        # Web has no sub-subfolders — so selecting folder Web should move immediately
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        cat_result = router.handle_category("p", self.note)
        result = router.handle_folder(1, cat_result, self.note)
        assert result.state == RouterState.SHOW_NOTE
        assert result.action == RouteAction.MOVE
        assert result.folder_path == ("Projects", "Web")

    def test_folder_move_calls_ensure_then_move(self) -> None:
        """ensure_folder is called before move_note when moving to a folder (ROUT-05)."""
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={"Projects": ("Web",), "Areas": (), "Resources": (), "Archive": ()},
        )
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        call_order: list[str] = []
        original_ensure = repo.ensure_folder
        original_move = repo.move_note

        def tracked_ensure(path: tuple[str, ...]) -> None:
            call_order.append("ensure_folder")
            original_ensure(path)

        def tracked_move(note_id: str, path: tuple[str, ...]) -> None:
            call_order.append("move_note")
            original_move(note_id, path)

        repo.ensure_folder = tracked_ensure  # type: ignore[method-assign]
        repo.move_note = tracked_move  # type: ignore[method-assign]
        cat_result = router.handle_category("p", _note("id1"))
        router.handle_folder(1, cat_result, _note("id1"))
        assert call_order == ["ensure_folder", "move_note"]

    def test_back_from_await_folder_returns_to_await_category(self) -> None:
        """[B] from AWAIT_FOLDER → AWAIT_CATEGORY (ROUT-06)."""
        cat_result = self.router.handle_category("p", self.note)
        result = self.router.handle_back(RouterState.AWAIT_FOLDER, cat_result)
        assert result.state == RouterState.AWAIT_CATEGORY

    def test_invalid_index_zero_state_unchanged(self) -> None:
        """Index 0 (out of range for 1-based) → state unchanged (ROUT-07)."""
        cat_result = self.router.handle_category("p", self.note)
        result = self.router.handle_folder(0, cat_result, self.note)
        assert result.state == RouterState.AWAIT_FOLDER

    def test_invalid_index_too_large_state_unchanged(self) -> None:
        """Index beyond range → state unchanged."""
        cat_result = self.router.handle_category("p", self.note)
        result = self.router.handle_folder(999, cat_result, self.note)
        assert result.state == RouterState.AWAIT_FOLDER

    def test_display_path_uses_separator(self) -> None:
        """display_path uses ' › ' (ROUT-08)."""
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={"Projects": ("Web",), "Areas": (), "Resources": (), "Archive": ()},
        )
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        cat_result = router.handle_category("p", _note("id1"))
        result = router.handle_folder(1, cat_result, _note("id1"))
        assert result.display_path == "Projects › Web"


class TestGeneralFirstOrdering:
    """General subfolder is listed first in AWAIT_SUBFOLDER options (ROUT-05)."""

    def setup_method(self) -> None:
        # Projects has General + Web; General must appear first in options
        self.structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("Web", "General"),
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        self.repo = MockNotesRepository(notes=notes, structure=self.structure)
        self.cfg = _config()
        self.router = Router(repo=self.repo, config=self.cfg, year_provider=lambda: 2031)
        self.note = _note("id1")

    def test_general_is_first_in_await_folder_options(self) -> None:
        """General folder appears first in the options list (ROUT-05)."""
        result = self.router.handle_category("p", self.note)
        assert result.options[0] == "General"

    def test_non_general_folders_follow(self) -> None:
        result = self.router.handle_category("p", self.note)
        assert "Web" in result.options[1:]


class TestAwaitSubfolderTransition:
    """AWAIT_SUBFOLDER: numbered selection + [B] back (ROUT-05, ROUT-06, ROUT-07, ROUT-08)."""

    def setup_method(self) -> None:
        # Projects → General (has subfolders Research, Design) to test subfolder level
        # For simplicity, use the 2-level PARA: Projects→(General, Web)
        # We'll treat Projects→General→Research as a 3-level path
        # But per M1 the structure is 2 levels deep — let's keep it realistic:
        # Projects → (General, Web) where selecting "General" folder in Projects triggers AWAIT_SUBFOLDER
        # The "subfolders" of ("Projects", "General") come from a deeper structure
        # For this test, we'll use a structure where Projects itself is the root
        # and its folders include General, and General sub-subfolders are not in ParaStructure
        # (ParaStructure only stores root→subfolders).
        # Instead: let's build a structure where we navigate to AWAIT_SUBFOLDER
        # by selecting a folder that the router determines has subfolders.
        # Per the plan: "A folder 'has subfolders' only if ParaStructure shows children
        # under that (root, folder) path" — in M1 structure is 2 levels deep.
        # So we need a structure that has 3-level hierarchy.
        # Let's extend ParaStructure with a custom conftest that records sub-subfolders.
        # Actually per the plan: "if a selected folder itself has no recorded children,
        # MOVE to (root, folder) immediately (ROUT-05)". The router treats folders with
        # subfolders differently. In 2-level PARA, project roots have subfolders (e.g.
        # Projects → General, Web). Selecting General (which has no further subs) → MOVE.
        # But the plan says "From AWAIT_FOLDER (root 'Projects'): selecting folder index N
        # for a folder that HAS subfolders → AWAIT_SUBFOLDER".
        # For AWAIT_SUBFOLDER to trigger, we need a folder with children.
        # Solution: use a 3-level structure where ParaStructure records sub-subfolders
        # by encoding them via a different key convention, or use a richer fixture.
        # The plan mentions "structure.subfolders_for(root) is the folder list and
        # deeper nesting is represented; if a selected folder itself has no recorded
        # children..." — so the router may check subfolders_for("Projects", "General")
        # or equivalent. Since ParaStructure.subfolders_for only takes a root,
        # the router uses the structure to determine if a (root, folder) has children.
        # The simplest interpretation: folders listed in subfolders_for(root) ARE the
        # subfolder candidates; if a (root, folder) path's own subfolders list is
        # non-empty, show AWAIT_SUBFOLDER. But the current ParaStructure only stores
        # {root: [subfolder_names]}.
        # For M1: the router treats "folders with subfolders" as folders that themselves
        # appear as KEYS in the subfolders dict with non-empty values.
        # Extended fixture: "Projects" root has subfolders ("General", "Web"),
        # and "General" folder has subfolders too — encoded via a new key in subfolders.
        # Let's extend the conftest fixture for this test with a richer structure.
        self.structure_3level = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Projects/General": ("Research", "Design"),  # 3-level sub-subfolders
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        self.repo = MockNotesRepository(notes=notes, structure=self.structure_3level)
        self.cfg = _config()
        self.router = Router(repo=self.repo, config=self.cfg, year_provider=lambda: 2031)
        self.note = _note("id1")

    def test_subfolder_selection_moves_to_show_note(self) -> None:
        """Selecting a subfolder issues move and returns SHOW_NOTE (ROUT-05)."""
        cat_result = self.router.handle_category("p", self.note)
        folder_result = self.router.handle_folder(1, cat_result, self.note)
        assert folder_result.state == RouterState.AWAIT_SUBFOLDER
        # Now select subfolder 1
        sub_result = self.router.handle_subfolder(1, folder_result, self.note)
        assert sub_result.state == RouterState.SHOW_NOTE
        assert sub_result.action == RouteAction.MOVE

    def test_subfolder_folder_path_three_levels(self) -> None:
        cat_result = self.router.handle_category("p", self.note)
        folder_result = self.router.handle_folder(1, cat_result, self.note)
        sub_result = self.router.handle_subfolder(1, folder_result, self.note)
        # Path should be (root, folder, subfolder)
        assert len(sub_result.folder_path) == 3
        assert sub_result.folder_path[0] == "Projects"

    def test_subfolder_display_path_three_parts(self) -> None:
        cat_result = self.router.handle_category("p", self.note)
        folder_result = self.router.handle_folder(1, cat_result, self.note)
        sub_result = self.router.handle_subfolder(1, folder_result, self.note)
        # display_path uses ' › ' separator (ROUT-08)
        assert "›" in sub_result.display_path
        parts = sub_result.display_path.split(" › ")
        assert len(parts) == 3

    def test_back_from_await_subfolder_returns_to_await_folder(self) -> None:
        """[B] from AWAIT_SUBFOLDER → AWAIT_FOLDER (ROUT-06)."""
        cat_result = self.router.handle_category("p", self.note)
        folder_result = self.router.handle_folder(1, cat_result, self.note)
        assert folder_result.state == RouterState.AWAIT_SUBFOLDER
        result = self.router.handle_back(RouterState.AWAIT_SUBFOLDER, folder_result)
        assert result.state == RouterState.AWAIT_FOLDER

    def test_invalid_subfolder_index_state_unchanged(self) -> None:
        cat_result = self.router.handle_category("p", self.note)
        folder_result = self.router.handle_folder(1, cat_result, self.note)
        result = self.router.handle_subfolder(999, folder_result, self.note)
        assert result.state == RouterState.AWAIT_SUBFOLDER

    def test_subfolder_invalid_zero_state_unchanged(self) -> None:
        cat_result = self.router.handle_category("p", self.note)
        folder_result = self.router.handle_folder(1, cat_result, self.note)
        result = self.router.handle_subfolder(0, folder_result, self.note)
        assert result.state == RouterState.AWAIT_SUBFOLDER

    def test_subfolder_general_first_ordering(self) -> None:
        """General is listed first in subfolder options."""
        # Use structure where General is NOT first in the dict
        structure = ParaStructure(
            roots=("Projects", "Areas", "Resources", "Archive"),
            subfolders={
                "Projects": ("General", "Web"),
                "Projects/General": ("Beta", "General", "Alpha"),
                "Areas": (),
                "Resources": (),
                "Archive": (),
            },
        )
        notes = [_note("id1")]
        repo = MockNotesRepository(notes=notes, structure=structure)
        router = Router(repo=repo, config=self.cfg, year_provider=lambda: 2031)
        cat_result = router.handle_category("p", _note("id1"))
        folder_result = router.handle_folder(1, cat_result, _note("id1"))
        assert folder_result.state == RouterState.AWAIT_SUBFOLDER
        assert folder_result.options[0] == "General"
