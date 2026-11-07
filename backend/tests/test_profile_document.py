from typing import Any

import pytest
from pydantic import ValidationError

from job_board.profiles import MAX_TARGET_TITLES, Profile, TargetTitles


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


@pytest.mark.parametrize(
    ("title", "rule"),
    [
        ("", "A target title cannot be blank"),
        ("   ", "A target title cannot be blank"),
        ("x" * 101, "A target title can be at most 100 characters"),
        ("Data\tanalyst", "A target title cannot contain control characters"),
        ("Data\x00analyst", "A target title cannot contain control characters"),
        ("Data\x85analyst", "A target title cannot contain control characters"),
    ],
    ids=["empty", "only spaces", "too long", "a tab inside", "a null", "a C1 control"],
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
