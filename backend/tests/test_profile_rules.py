from collections.abc import Callable
from typing import Any

import pytest
from pydantic_core import PydanticCustomError

from job_board.profile_rules import checked_text, distinct_and_capped, fold, sent_limit


def broken_rule(check: Callable[[Any], Any], sent: Any) -> tuple[str, str]:
    with pytest.raises(PydanticCustomError) as raised:
        check(sent)
    return raised.value.type, raised.value.message()


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (" ​ ", "An industry cannot be blank"),
        ("x" * 31, "An industry can be at most 30 characters"),
        ("é" * 31, "An industry can be at most 30 characters"),
        ("Retail\nbanking", "An industry cannot contain control characters"),
        ("Retail ⁦banking⁩", "An industry cannot contain text direction controls"),
        ("Retail \ud800", "An industry must be valid text"),
    ],
    ids=["blank", "too long", "too long once composed", "a control", "a direction", "not text"],
)
def test_a_text_rule_names_its_own_noun_and_limit(text: str, rule: str) -> None:
    _, message = broken_rule(checked_text("an industry", 30), text)

    assert message == rule


def test_a_text_rule_trims_composes_and_takes_its_limit() -> None:
    check = checked_text("a rule", 30)

    assert check("​ Café ") == "Café"
    assert check("é" * 30) == "é" * 30


def test_a_refusal_type_names_the_noun_without_its_article() -> None:
    assert broken_rule(checked_text("a trade-off", 10), "")[0] == "trade_off_blank"
    assert broken_rule(checked_text("a target title", 10), "")[0] == "target_title_blank"


def test_a_list_of_objects_drops_repeats_by_its_key_keeping_the_first() -> None:
    offices: list[dict[str, Any]] = [
        {"city": "Lisbon", "days": 2},
        {"city": "Porto"},
        {"city": "LISBON", "days": 5},
    ]

    def city(office: dict[str, Any]) -> str:
        return fold(office["city"])

    distinct = distinct_and_capped("offices", 2, city)

    assert distinct(offices) == [{"city": "Lisbon", "days": 2}, {"city": "Porto"}]


def test_a_list_cap_counts_what_is_left_and_names_the_plural() -> None:
    distinct = distinct_and_capped("industries", 2, fold)

    assert distinct(["Retail", "retail", "Banking", "BANKING"]) == ["Retail", "Banking"]
    assert broken_rule(distinct, ["Retail", "Banking", "Mining"]) == (
        "industries_too_many",
        "You can list at most 2 industries",
    )


def test_folding_ignores_case_and_composition() -> None:
    assert fold("CAFÉ") == fold("café")
    assert fold("ΐ") == fold("Ϊ́")


def test_a_list_may_carry_ten_times_its_cap_before_any_item_is_checked() -> None:
    assert sent_limit(20) == 200
    assert sent_limit(51) == 510
