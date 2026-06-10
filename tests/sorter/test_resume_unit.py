"""Unit tests for the session-resume persistence layer (UX-03).

Covers the frozen :class:`SessionState` model and the :class:`ResumeStore`
save/load/clear contract:

- round-trip save → load returns an EQUAL SessionState (tuple note_ids + saved_at),
- ``load`` returns ``None`` on a missing file AND on a corrupt/schema-invalid file
  (never raises — threat T-15-01),
- ``save`` is atomic (temp file + ``Path.replace``) and leaves no torn/leftover file
  (threat T-15-02),
- ``save`` creates missing parent directories,
- ``clear`` removes the file and is a no-op when absent,
- ``matches`` enforces EXACT note_ids-tuple + inbox equality (threat T-15-03),
- the default path equals ``_DEFAULT_STATE_PATH`` (asserted WITHOUT touching the
  real home directory).

All stores are constructed with ``tmp_path`` — no unit test touches the real
``~/.notes-os/`` directory.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from notes_os.sorter.resume import _DEFAULT_STATE_PATH, ResumeStore, SessionState


if TYPE_CHECKING:
    from pathlib import Path


# A fixed timestamp so round-trip equality is deterministic (no wall-clock).
_FIXED_SAVED_AT = datetime(2026, 6, 9, 14, 30, 0)


def _make_state(
    *,
    inbox_folder: str = "Notes",
    note_ids: tuple[str, ...] = ("a", "b", "c"),
    index: int = 1,
    moved: int = 1,
    skipped: int = 0,
    errors: int = 0,
) -> SessionState:
    """Build a SessionState with sensible defaults for the tests."""
    return SessionState(
        inbox_folder=inbox_folder,
        note_ids=note_ids,
        index=index,
        moved=moved,
        skipped=skipped,
        errors=errors,
        saved_at=_FIXED_SAVED_AT,
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    """save(state) then load() returns an EQUAL SessionState."""

    def test_round_trip_returns_equal_state(self, tmp_path: Path) -> None:
        state = _make_state()
        store = ResumeStore(path=tmp_path / "s.json")

        store.save(state)
        loaded = store.load()

        assert loaded == state

    def test_round_trip_preserves_note_ids_as_tuple(self, tmp_path: Path) -> None:
        state = _make_state(note_ids=("x", "y", "z"))
        store = ResumeStore(path=tmp_path / "s.json")

        store.save(state)
        loaded = store.load()

        assert loaded is not None
        assert loaded.note_ids == ("x", "y", "z")
        assert isinstance(loaded.note_ids, tuple)

    def test_round_trip_preserves_saved_at(self, tmp_path: Path) -> None:
        state = _make_state()
        store = ResumeStore(path=tmp_path / "s.json")

        store.save(state)
        loaded = store.load()

        assert loaded is not None
        assert loaded.saved_at == _FIXED_SAVED_AT


# ---------------------------------------------------------------------------
# load None-safety (threat T-15-01)
# ---------------------------------------------------------------------------


class TestLoadNoneSafety:
    """load() degrades to None on a missing or corrupt file — never raises."""

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        store = ResumeStore(path=tmp_path / "absent.json")

        assert store.load() is None

    def test_load_missing_does_not_create_file(self, tmp_path: Path) -> None:
        path = tmp_path / "absent.json"
        store = ResumeStore(path=path)

        store.load()

        assert path.exists() is False

    def test_load_unparseable_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "torn.json"
        path.write_text("{ not json", encoding="utf-8")
        store = ResumeStore(path=path)

        assert store.load() is None

    def test_load_schema_invalid_json_returns_none(self, tmp_path: Path) -> None:
        # Syntactically valid JSON that fails the SessionState schema.
        path = tmp_path / "bad-schema.json"
        path.write_text('{"inbox_folder": 5}', encoding="utf-8")
        store = ResumeStore(path=path)

        assert store.load() is None


# ---------------------------------------------------------------------------
# Atomic write (threat T-15-02)
# ---------------------------------------------------------------------------


class TestAtomicSave:
    """save writes atomically and leaves no torn/leftover temp file."""

    def test_save_leaves_one_complete_state_file(self, tmp_path: Path) -> None:
        # Fresh subdir so a sibling test can never pollute the directory listing.
        target_dir = tmp_path / "atomic"
        target_dir.mkdir()
        path = target_dir / "s.json"
        store = ResumeStore(path=path)
        state = _make_state()

        store.save(state)

        # The directory holds exactly the one state file (no leftover *.tmp).
        contents = sorted(p.name for p in target_dir.iterdir())
        assert contents == ["s.json"]
        # ...and the single file parses as one complete SessionState.
        assert store.load() == state

    def test_save_leaves_no_tmp_file(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        store = ResumeStore(path=path)

        store.save(_make_state())

        leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_save_overwrites_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        store = ResumeStore(path=path)

        store.save(_make_state(moved=1))
        store.save(_make_state(moved=9))

        loaded = store.load()
        assert loaded is not None
        assert loaded.moved == 9

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "s.json"
        store = ResumeStore(path=path)

        store.save(_make_state())

        assert path.exists()
        assert store.load() == _make_state()


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    """clear removes the file and is a no-op when the file is absent."""

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        store = ResumeStore(path=path)
        store.save(_make_state())
        assert path.exists()

        store.clear()

        assert path.exists() is False

    def test_clear_absent_is_noop(self, tmp_path: Path) -> None:
        store = ResumeStore(path=tmp_path / "never-existed.json")

        # Must not raise on an absent file.
        store.clear()
        store.clear()

        assert (tmp_path / "never-existed.json").exists() is False


# ---------------------------------------------------------------------------
# matches — exact id-tuple + inbox equality (threat T-15-03)
# ---------------------------------------------------------------------------


class TestMatches:
    """matches() is True only on EXACT note_ids tuple + inbox equality."""

    def test_matches_exact(self) -> None:
        state = _make_state(inbox_folder="Notes", note_ids=("a", "b", "c"))

        assert state.matches("Notes", ("a", "b", "c")) is True

    def test_matches_removed_is_false(self) -> None:
        state = _make_state(note_ids=("a", "b", "c"))

        assert state.matches("Notes", ("a", "b")) is False

    def test_matches_reordered_is_false(self) -> None:
        state = _make_state(note_ids=("a", "b", "c"))

        assert state.matches("Notes", ("a", "c", "b")) is False

    def test_matches_added_is_false(self) -> None:
        state = _make_state(note_ids=("a", "b", "c"))

        assert state.matches("Notes", ("a", "b", "c", "d")) is False

    def test_matches_different_inbox_is_false(self) -> None:
        state = _make_state(inbox_folder="Notes", note_ids=("a", "b", "c"))

        assert state.matches("Archive", ("a", "b", "c")) is False


# ---------------------------------------------------------------------------
# Default path (no real-home I/O)
# ---------------------------------------------------------------------------


class TestDefaultPath:
    """ResumeStore() defaults to _DEFAULT_STATE_PATH without writing to home."""

    def test_default_path_value(self) -> None:
        # Assert the path VALUE only — never call save/load on the default store
        # (which would touch the real ~/.notes-os/ directory).
        assert ResumeStore().path == _DEFAULT_STATE_PATH

    def test_default_path_is_notes_os_sibling(self) -> None:
        assert _DEFAULT_STATE_PATH.name == "session-state.json"
        assert _DEFAULT_STATE_PATH.parent.name == ".notes-os"
