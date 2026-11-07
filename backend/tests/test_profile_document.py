from typing import Any

import pytest
from pydantic import ValidationError

from job_board.profiles import MAX_SENT_TITLES, MAX_TARGET_TITLES, Profile, TargetTitles


def titles_of(sent: list[Any]) -> list[str]:
    return TargetTitles.model_validate({"titles": sent}).titles


def refusal(sent: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ValidationError) as raised:
        TargetTitles.model_validate(sent)
    (error,) = raised.value.errors()
    return dict(error)


def test_trims_each_title_and_keeps_the_order_given() -> None:
    assert titles_of(["  Staff engineer ", "\tData analyst\n", "Designer"]) == [
        "Staff engineer",
        "Data analyst",
        "Designer",
    ]


def test_drops_repeats_without_regard_to_case_keeping_the_first_spelling() -> None:
    sent = ["Product Manager", "designer", "product manager", " PRODUCT MANAGER ", "Designer"]

    assert titles_of(sent) == ["Product Manager", "designer"]


def test_takes_an_empty_list_as_none_chosen() -> None:
    assert titles_of([]) == []


def test_takes_twenty_titles_and_repeats_beyond_them() -> None:
    twenty = [f"Title {number}" for number in range(MAX_TARGET_TITLES)]

    assert MAX_TARGET_TITLES == 20
    assert titles_of([*twenty, "title 0", "TITLE 19"]) == twenty


def test_takes_a_title_of_one_hundred_characters() -> None:
    assert titles_of(["x" * 100]) == ["x" * 100]


def test_keeps_each_title_in_its_composed_form() -> None:
    assert titles_of(["Cafe\u0301 manager"]) == ["Caf\u00e9 manager"]


def test_composed_and_decomposed_forms_of_one_title_keep_one() -> None:
    assert titles_of(["Caf\u00e9 manager", "cafe\u0301 MANAGER"]) == ["Caf\u00e9 manager"]
    assert titles_of(["Cafe\u0301 manager", "caf\u00e9 manager"]) == ["Caf\u00e9 manager"]


def test_a_title_differing_only_in_case_once_composed_is_a_repeat() -> None:
    # Folding the case of these two composed letters gives two sequences that
    # compose to one letter, iota with dialytika and tonos.
    assert titles_of(["\u0390", "\u03aa\u0301"]) == ["\u0390"]


def test_counts_the_length_of_the_composed_form() -> None:
    # A hundred accented letters, each sent as a letter and a combining accent.
    assert titles_of(["e\u0301" * 100]) == ["\u00e9" * 100]


def test_keeps_a_zero_width_joiner_inside_a_title() -> None:
    # The joiner binds the two emoji into one; emoji sequences depend on it.
    title = "\U0001f469\u200d\U0001f4bb engineer"

    assert titles_of([title]) == [title]


@pytest.mark.parametrize(
    ("title", "rule"),
    [
        ("", "A target title cannot be blank"),
        ("   ", "A target title cannot be blank"),
        ("x" * 101, "A target title can be at most 100 characters"),
        ("Data\tanalyst", "A target title cannot contain control characters"),
        ("Data\x00analyst", "A target title cannot contain control characters"),
        ("Data\x85analyst", "A target title cannot contain control characters"),
        ("e\u0301" * 101, "A target title can be at most 100 characters"),
        ("Engineer \ud800", "A target title must be valid text"),
        ("\u200b", "A target title cannot be blank"),
        (" \u200b\u0301\u200d ", "A target title cannot be blank"),
        ("\u202eenigne", "A target title cannot contain text direction controls"),
        ("Data \u2066analyst\u2069", "A target title cannot contain text direction controls"),
    ],
    ids=[
        "empty",
        "only spaces",
        "too long",
        "a tab inside",
        "a null",
        "a C1 control",
        "too long once composed",
        "a lone surrogate",
        "a zero-width space alone",
        "only invisible marks",
        "a right-to-left override",
        "a directional isolate",
    ],
)
def test_refuses_a_title_naming_the_rule_and_echoing_only_that_title(title: str, rule: str) -> None:
    error = refusal({"titles": ["Designer", title, "Writer"]})

    assert error["msg"] == rule
    assert error["loc"] == ("titles", 1)
    assert error["input"] == title


def test_refuses_more_than_twenty_after_repeats_are_dropped() -> None:
    error = refusal({"titles": [f"Title {number}" for number in range(MAX_TARGET_TITLES + 1)]})

    assert error["msg"] == "You can list at most 20 target titles"
    assert error["loc"] == ("titles",)


def test_refuses_a_list_past_its_raw_bound_before_checking_any_title() -> None:
    with pytest.raises(ValidationError) as raised:
        TargetTitles.model_validate({"titles": ["   "] * (MAX_SENT_TITLES + 1)})

    # One refusal for the list, not one for each of its blank titles.
    (error,) = raised.value.errors()
    assert MAX_SENT_TITLES == 200
    assert error["type"] == "too_long"
    assert error["loc"] == ("titles",)


def test_takes_a_list_at_its_raw_bound_whose_repeats_leave_one_title() -> None:
    assert titles_of(["Designer"] * MAX_SENT_TITLES) == ["Designer"]


@pytest.mark.parametrize(
    "sent",
    [{}, {"titles": "Designer"}, {"titles": [7]}, {"titles": [], "salary": 1}],
    ids=["no titles", "not a list", "not text", "another key"],
)
def test_refuses_a_body_of_another_shape(sent: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TargetTitles.model_validate(sent)


def test_a_stored_document_without_the_section_reads_as_none_chosen() -> None:
    assert Profile.model_validate({}).target_titles == []


def test_a_stored_document_with_keys_it_does_not_know_still_reads() -> None:
    stored = {"target_titles": ["Designer"], "a_later_section": {"anything": True}}

    assert Profile.model_validate(stored) == Profile(target_titles=["Designer"])
