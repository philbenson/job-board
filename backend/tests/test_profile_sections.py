"""The sections' own rules, checked on their models; the route tests check the answers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from job_board.profile_sections import Pay, Places, TitleRange

TITLE_RANGE = {"nearby_titles": ["Designer"], "lower_level_ok": False}
PLACES = {
    "remote_ok": True,
    "offices": [{"city": "Lisbon", "days_a_week": 2}],
    "states": ["NY"],
    "will_relocate": False,
    "relocate_for": ["Example Company"],
}
PAY = {"floor_usd": 120_000, "ask_usd": 150_000}


def saved(model: type[BaseModel], sent: dict[str, Any]) -> dict[str, Any]:
    return model.model_validate(sent).model_dump(mode="json")


def at(dumped: Any, loc: tuple[str | int, ...]) -> Any:
    for step in loc:
        dumped = dumped[step]
    return dumped


def refusal(model: type[BaseModel], sent: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ValidationError) as raised:
        model.model_validate(sent)
    (error,) = raised.value.errors()
    return dict(error)


@dataclass(frozen=True)
class Text:
    """One kind of text in a section: where it sits, its noun and its limit."""

    model: type[BaseModel]
    body: dict[str, Any]
    put: Callable[[str], dict[str, Any]]  # the body with this text in its place
    loc: tuple[str | int, ...]
    noun: str
    limit: int


TEXTS = {
    "nearby title": Text(
        TitleRange,
        TITLE_RANGE,
        lambda text: {**TITLE_RANGE, "nearby_titles": ["Designer", text]},
        ("nearby_titles", 1),
        "A nearby title",
        100,
    ),
    "city": Text(
        Places,
        PLACES,
        lambda text: {**PLACES, "offices": [{"city": text, "days_a_week": 1}]},
        ("offices", 0, "city"),
        "A city",
        100,
    ),
    "company to move for": Text(
        Places,
        PLACES,
        lambda text: {**PLACES, "relocate_for": [text]},
        ("relocate_for", 0),
        "A company",
        100,
    ),
}


@pytest.mark.parametrize("text", TEXTS.values(), ids=TEXTS.keys())
def test_each_text_takes_its_limit_and_refuses_past_it_or_blank(text: Text) -> None:
    longest = text.put("é" * text.limit)
    too_long = refusal(text.model, text.put("é" * (text.limit + 1)))
    blank = refusal(text.model, text.put(" ​ "))

    assert at(saved(text.model, longest), text.loc) == "\u00e9" * text.limit
    assert (too_long["msg"], too_long["loc"]) == (
        f"{text.noun} can be at most {text.limit} characters",
        text.loc,
    )
    assert (blank["msg"], blank["loc"]) == (f"{text.noun} cannot be blank", text.loc)


@dataclass(frozen=True)
class Listed:
    """One list in a section: how to make its items and its repeats, and its cap."""

    model: type[BaseModel]
    body: dict[str, Any]
    field: str
    item: Callable[[int], Any]  # the nth distinct item
    repeat: Callable[[int], Any]  # a repeat of the nth item, spelled differently
    cap: int | None  # None where the choices are fewer than any cap
    plural: str
    broken: Any  # an item that breaks a rule, to show the sent limit is checked first


# The fifty states and the District of Columbia.
US_STATES = [
    "AK",
    "AL",
    "AR",
    "AZ",
    "CA",
    "CO",
    "CT",
    "DC",
    "DE",
    "FL",
    "GA",
    "HI",
    "IA",
    "ID",
    "IL",
    "IN",
    "KS",
    "KY",
    "LA",
    "MA",
    "MD",
    "ME",
    "MI",
    "MN",
    "MO",
    "MS",
    "MT",
    "NC",
    "ND",
    "NE",
    "NH",
    "NJ",
    "NM",
    "NV",
    "NY",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VA",
    "VT",
    "WA",
    "WI",
    "WV",
    "WY",
]

LISTS = {
    "nearby titles": Listed(
        TitleRange,
        TITLE_RANGE,
        "nearby_titles",
        lambda n: f"Title {n}",
        lambda n: f"TITLE {n} ",
        20,
        "nearby titles",
        "   ",
    ),
    "offices": Listed(
        Places,
        PLACES,
        "offices",
        lambda n: {"city": f"City {n}", "days_a_week": 2},
        lambda n: {"city": f"CITY {n}", "days_a_week": 5},
        20,
        "offices",
        {},
    ),
    "states": Listed(
        Places,
        PLACES,
        "states",
        lambda n: US_STATES[n],
        lambda n: US_STATES[n].lower(),
        None,
        "states",
        "ZZ",
    ),
    "companies to move for": Listed(
        Places,
        PLACES,
        "relocate_for",
        lambda n: f"Company {n}",
        lambda n: f"company {n}",
        20,
        "companies",
        "   ",
    ),
}


@pytest.mark.parametrize("listed", LISTS.values(), ids=LISTS.keys())
def test_each_list_drops_repeats_keeping_the_first_spelling(listed: Listed) -> None:
    sent = [listed.item(0), listed.repeat(0), listed.item(1), listed.repeat(1)]
    once = [listed.item(0), listed.item(1)]

    assert (
        saved(listed.model, {**listed.body, listed.field: sent})[listed.field]
        == saved(listed.model, {**listed.body, listed.field: once})[listed.field]
    )


CAPPED = {name: listed for name, listed in LISTS.items() if listed.cap is not None}


@pytest.mark.parametrize("listed", CAPPED.values(), ids=CAPPED.keys())
def test_each_cap_counts_the_list_after_repeats_are_dropped(listed: Listed) -> None:
    assert listed.cap is not None
    full = [listed.item(n) for n in range(listed.cap)]
    with_repeats = [*full, listed.repeat(0), listed.repeat(listed.cap - 1)]
    over = refusal(listed.model, {**listed.body, listed.field: [*full, listed.item(listed.cap)]})

    assert len(saved(listed.model, {**listed.body, listed.field: with_repeats})[listed.field]) == (
        listed.cap
    )
    assert (over["msg"], over["loc"]) == (
        f"You can list at most {listed.cap} {listed.plural}",
        (listed.field,),
    )


@pytest.mark.parametrize("listed", LISTS.values(), ids=LISTS.keys())
def test_each_list_past_ten_times_its_cap_is_refused_before_any_item_is_checked(
    listed: Listed,
) -> None:
    most = 10 * (listed.cap if listed.cap is not None else len(US_STATES))
    error = refusal(listed.model, {**listed.body, listed.field: [listed.broken] * (most + 1)})

    assert (error["type"], error["loc"]) == ("too_long", (listed.field,))


@pytest.mark.parametrize(
    ("model", "put", "loc", "lowest", "highest"),
    [
        (
            Places,
            lambda days: {**PLACES, "offices": [{"city": "Lisbon", "days_a_week": days}]},
            ("offices", 0, "days_a_week"),
            1,
            5,
        ),
        (Pay, lambda floor: {"floor_usd": floor, "ask_usd": 10_000_000}, ("floor_usd",), 0, 10**7),
        (Pay, lambda ask: {"floor_usd": 0, "ask_usd": ask}, ("ask_usd",), 0, 10**7),
    ],
    ids=["days in the office", "pay floor", "pay ask"],
)
def test_each_number_takes_its_range_and_refuses_past_either_end(
    model: type[BaseModel],
    put: Callable[[int], dict[str, Any]],
    loc: tuple[str | int, ...],
    lowest: int,
    highest: int,
) -> None:
    assert at(saved(model, put(lowest)), loc) == lowest
    assert at(saved(model, put(highest)), loc) == highest
    assert refusal(model, put(lowest - 1))["loc"] == loc
    assert refusal(model, put(highest + 1))["loc"] == loc


def test_places_stores_states_in_upper_case_and_refuses_any_other_code() -> None:
    unknown = refusal(Places, {**PLACES, "states": ["ny", "Dc", "PR"]})

    assert saved(Places, {**PLACES, "states": ["ny", "Dc", "ca"]})["states"] == ["NY", "DC", "CA"]
    assert (unknown["msg"], unknown["loc"]) == (
        "A state must be the two-letter postal code of a US state or DC",
        ("states", 2),
    )


def test_places_refuses_a_state_spelled_with_letters_that_only_upper_case_to_one() -> None:
    # Dotless i upper-cases to I, so dotless i and l would otherwise pass as Illinois.
    assert refusal(Places, {**PLACES, "states": ["\u0131l"]})["loc"] == ("states", 0)


def test_places_refuses_companies_to_move_for_from_someone_who_would_move_anyway() -> None:
    error = refusal(Places, {**PLACES, "will_relocate": True})

    assert saved(Places, {**PLACES, "will_relocate": True, "relocate_for": []})["will_relocate"]
    assert (error["msg"], error["loc"]) == (
        "List companies you would move for only if you would not move otherwise",
        ("relocate_for",),
    )


def test_pay_refuses_an_ask_below_the_floor_and_takes_an_ask_at_it() -> None:
    error = refusal(Pay, {"floor_usd": 150_000, "ask_usd": 149_999})

    assert saved(Pay, {"floor_usd": 150_000, "ask_usd": 150_000})["ask_usd"] == 150_000
    assert (error["msg"], error["loc"]) == ("The ask cannot be below the floor", ("ask_usd",))
