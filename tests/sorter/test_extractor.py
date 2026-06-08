"""Unit tests for notes_os.sorter.extractor — pure heuristic task extraction.

Covers all three LOCKED signal families (action phrases, named commitments,
inline dates), empty/no-match cases, and the determinism/purity contract.
No filesystem or network access — the extractor is a pure function.
"""

from __future__ import annotations

import pytest

from notes_os.sorter.extractor import ExtractedTask, extract_tasks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _texts(results: list[ExtractedTask]) -> list[str]:
    """Return the `.text` values from a list of ExtractedTask objects."""
    return [t.text for t in results]


# ---------------------------------------------------------------------------
# Signal family 1 — Action phrases
# ---------------------------------------------------------------------------

ACTION_PHRASE_CASES = [
    ("need to", "I need to call the client tomorrow"),
    ("follow up", "I should follow up with the team"),
    ("TODO", "TODO: fix the broken link"),
    ("schedule", "We need to schedule the meeting"),
    ("remind", "Please remind me to send the report"),
    ("I will", "I will prepare the slides tonight"),
    ("we should", "we should discuss the roadmap"),
]


@pytest.mark.parametrize(
    "phrase,text", ACTION_PHRASE_CASES, ids=[p for p, _ in ACTION_PHRASE_CASES]
)
def test_action_phrase_detected(phrase: str, text: str) -> None:
    """Each action phrase triggers at least one ExtractedTask."""
    results = extract_tasks(text)
    assert len(results) >= 1, f"Expected hit for phrase {phrase!r} in {text!r}"
    assert results[0].text != "", "ExtractedTask.text must be non-empty"


# ---------------------------------------------------------------------------
# Signal family 2 — Named commitments
# ---------------------------------------------------------------------------


def test_named_commitment_capitalized_name_will() -> None:
    """'[Capitalized name] will' pattern triggers a hit."""
    results = extract_tasks("Sarah will send the deck by tomorrow")
    assert len(results) >= 1
    assert results[0].text != ""


def test_named_commitment_i_promised() -> None:
    """'I promised' literal triggers a hit."""
    results = extract_tasks("I promised to review the contract before Friday")
    assert len(results) >= 1
    assert results[0].text != ""


def test_named_commitment_another_name() -> None:
    """Another capitalized name with 'will' also triggers a hit."""
    results = extract_tasks("Michael will handle the deployment next week")
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# Signal family 3 — Inline dates / deadlines
# ---------------------------------------------------------------------------

DATE_CASES = [
    ("by Friday", "Please submit the form by Friday"),
    ("next week", "Let us meet next week to review"),
    ("ISO date", "The deadline is due 2026-06-30"),
    ("numeric date mm/dd", "Submit before 6/30 at noon"),
]


@pytest.mark.parametrize("label,text", DATE_CASES, ids=[lbl for lbl, _ in DATE_CASES])
def test_inline_date_detected(label: str, text: str) -> None:
    """Each inline date form triggers at least one ExtractedTask."""
    results = extract_tasks(text)
    assert len(results) >= 1, f"Expected hit for date pattern {label!r} in {text!r}"
    assert results[0].text != ""


# ---------------------------------------------------------------------------
# Negative cases — no known patterns
# ---------------------------------------------------------------------------


def test_no_match_returns_empty_list() -> None:
    """Text without any known signal returns an empty list."""
    results = extract_tasks("The cat sat on the mat.")
    assert results == []


def test_purely_descriptive_text_no_match() -> None:
    """Generic descriptive prose without signal phrases returns []."""
    results = extract_tasks("The sky is blue and the grass is green.")
    assert results == []


# ---------------------------------------------------------------------------
# Empty / whitespace input
# ---------------------------------------------------------------------------


def test_empty_string_returns_empty_list() -> None:
    """Empty string input returns []."""
    assert extract_tasks("") == []


def test_whitespace_only_returns_empty_list() -> None:
    """Whitespace-only string returns []."""
    assert extract_tasks("   \n\t  ") == []


# ---------------------------------------------------------------------------
# Determinism / purity
# ---------------------------------------------------------------------------


def test_determinism_same_input_same_output() -> None:
    """Calling extract_tasks twice on identical input returns equal results."""
    text = "I will prepare the slides and Sarah will send the deck by Friday"
    result_a = extract_tasks(text)
    result_b = extract_tasks(text)
    assert result_a == result_b, "extract_tasks is not deterministic"


def test_result_text_field_is_str() -> None:
    """ExtractedTask.text is a non-empty str for positive input."""
    results = extract_tasks("I need to call the dentist")
    assert len(results) >= 1
    assert isinstance(results[0].text, str)
    assert results[0].text.strip() != ""


# ---------------------------------------------------------------------------
# De-duplication — multiple signals, no duplicate .text values
# ---------------------------------------------------------------------------


def test_no_duplicate_text_in_results() -> None:
    """Multiple distinct signals produce unique .text values."""
    text = "I need to review the budget. Sarah will send the report. Deadline is due 2026-07-01."
    results = extract_tasks(text)
    texts = _texts(results)
    assert len(texts) == len(set(texts)), f"Duplicate .text values found: {texts}"


def test_repeated_signal_in_text_deduped() -> None:
    """If the same fragment appears twice, it is emitted only once."""
    text = "I need to call Bob. I need to call Bob."
    results = extract_tasks(text)
    texts = _texts(results)
    assert texts.count("I need to call Bob") <= 1


# ---------------------------------------------------------------------------
# Multiple signals in one paragraph yield multiple distinct tasks
# ---------------------------------------------------------------------------


def test_multiple_signals_in_paragraph() -> None:
    """A paragraph with multiple signal types produces multiple tasks."""
    text = "I need to finish the proposal. Sarah will review it. Submit by Friday."
    results = extract_tasks(text)
    assert len(results) >= 2, f"Expected >= 2 tasks, got {len(results)}: {_texts(results)}"


# ---------------------------------------------------------------------------
# ExtractedTask model contract (frozen / hashable)
# ---------------------------------------------------------------------------


def test_extracted_task_is_frozen() -> None:
    """ExtractedTask raises an error when mutated (frozen Pydantic model)."""
    results = extract_tasks("I will prepare the agenda")
    assert len(results) >= 1
    task = results[0]
    with pytest.raises(Exception):  # noqa: B017 — ValidationError or TypeError from frozen model
        task.text = "modified"  # type: ignore[misc]


def test_extracted_task_equality() -> None:
    """Two ExtractedTask objects with the same text compare equal."""
    t1 = ExtractedTask(text="call the client")
    t2 = ExtractedTask(text="call the client")
    assert t1 == t2
