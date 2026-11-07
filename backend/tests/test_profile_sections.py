"""The sections' own rules, checked on their models; the route tests check the answers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from job_board import profile_sections
from job_board.profile_sections import (
    Application,
    Companies,
    DealBreakers,
    Gaps,
    Office,
    OwnRules,
    Pace,
    Pay,
    Places,
    Skill,
    Skills,
    TargetTitles,
    TitleRange,
)
from job_board.profiles import Profile

TITLE_RANGE = {"nearby_titles": ["Designer"], "lower_level_ok": False}
PLACES = {
    "remote_ok": True,
    "offices": [{"city": "Lisbon", "days_a_week": 2}],
    "states": ["NY"],
    "will_relocate": False,
    "relocate_for": ["Example Company"],
}
PAY = {"floor_usd": 120_000, "ask_usd": 150_000}
SKILLS = {"skills": [{"name": "Python", "years": 5}]}
GAPS = {"apply_with": ["No degree"], "trade_offs": ["A longer commute"]}
DEAL_BREAKERS = {"industries": ["Gambling"], "company_sizes": ["1-10"], "no_agencies": True}
COMPANIES = {
    "watch": ["Example Company"],
    "applied": [{"company": "Example Company", "title": "Designer"}],
}
PACE = {"leads_per_day": 10, "brief_from_score": 4}
OWN_RULES = {"rules": ["No roles that need a car"]}
COMPANY_SIZES = [
    "1-10",
    "11-50",
    "51-200",
    "201-500",
    "501-1000",
    "1001-5000",
    "5001-10000",
    "10001+",
]


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
    "skill": Text(
        Skills,
        SKILLS,
        lambda text: {"skills": [{"name": text, "years": 1}]},
        ("skills", 0, "name"),
        "A skill",
        60,
    ),
    "gap": Text(
        Gaps, GAPS, lambda text: {**GAPS, "apply_with": [text]}, ("apply_with", 0), "A gap", 200
    ),
    "trade-off": Text(
        Gaps,
        GAPS,
        lambda text: {**GAPS, "trade_offs": [text]},
        ("trade_offs", 0),
        "A trade-off",
        200,
    ),
    "industry": Text(
        DealBreakers,
        DEAL_BREAKERS,
        lambda text: {**DEAL_BREAKERS, "industries": [text]},
        ("industries", 0),
        "An industry",
        100,
    ),
    "watched company": Text(
        Companies,
        COMPANIES,
        lambda text: {**COMPANIES, "watch": [text]},
        ("watch", 0),
        "A company",
        100,
    ),
    "company applied to": Text(
        Companies,
        COMPANIES,
        lambda text: {**COMPANIES, "applied": [{"company": text, "title": "Designer"}]},
        ("applied", 0, "company"),
        "A company",
        100,
    ),
    "job title applied for": Text(
        Companies,
        COMPANIES,
        lambda text: {**COMPANIES, "applied": [{"company": "Example Company", "title": text}]},
        ("applied", 0, "title"),
        "A job title",
        100,
    ),
    "rule": Text(OwnRules, OWN_RULES, lambda text: {"rules": [text]}, ("rules", 0), "A rule", 300),
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
    cap: int
    plural: str
    broken: Any  # an item that breaks a rule, to show the sent limit is checked first
    choices_only: bool = False  # every allowed value fits under the cap, so it is never reached


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
        51,
        "states",
        "ZZ",
        choices_only=True,
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
    "skills": Listed(
        Skills,
        SKILLS,
        "skills",
        lambda n: {"name": f"Skill {n}", "years": 1},
        lambda n: {"name": f"SKILL {n}", "years": 9},
        100,
        "skills",
        {},
    ),
    "gaps": Listed(
        Gaps, GAPS, "apply_with", lambda n: f"Gap {n}", lambda n: f"gap {n}", 20, "gaps", " "
    ),
    "trade-offs": Listed(
        Gaps,
        GAPS,
        "trade_offs",
        lambda n: f"Trade-off {n}",
        lambda n: f"TRADE-OFF {n}",
        20,
        "trade-offs",
        " ",
    ),
    "industries": Listed(
        DealBreakers,
        DEAL_BREAKERS,
        "industries",
        lambda n: f"Industry {n}",
        lambda n: f"industry {n}",
        30,
        "industries",
        " ",
    ),
    "company sizes": Listed(
        DealBreakers,
        DEAL_BREAKERS,
        "company_sizes",
        lambda n: COMPANY_SIZES[n],
        lambda n: COMPANY_SIZES[n],
        8,
        "company sizes",
        "huge",
        choices_only=True,
    ),
    "watched companies": Listed(
        Companies,
        COMPANIES,
        "watch",
        lambda n: f"Company {n}",
        lambda n: f"COMPANY {n}",
        30,
        "companies",
        " ",
    ),
    "jobs applied to": Listed(
        Companies,
        COMPANIES,
        "applied",
        lambda n: {"company": f"Company {n}", "title": "Designer"},
        lambda n: {"company": f"company {n} ", "title": "DESIGNER"},
        50,
        "jobs applied to",
        {},
    ),
    "rules": Listed(
        OwnRules, OWN_RULES, "rules", lambda n: f"Rule {n}", lambda n: f"RULE {n}", 20, "rules", " "
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


CAPPED = {name: listed for name, listed in LISTS.items() if not listed.choices_only}


@pytest.mark.parametrize("listed", CAPPED.values(), ids=CAPPED.keys())
def test_each_cap_counts_the_list_after_repeats_are_dropped(listed: Listed) -> None:
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
    most = 10 * listed.cap
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
        (
            Skills,
            lambda years: {"skills": [{"name": "Python", "years": years}]},
            ("skills", 0, "years"),
            0,
            60,
        ),
        (Pace, lambda leads: {**PACE, "leads_per_day": leads}, ("leads_per_day",), 1, 50),
        (Pace, lambda score: {**PACE, "brief_from_score": score}, ("brief_from_score",), 1, 5),
    ],
    ids=[
        "days in the office",
        "pay floor",
        "pay ask",
        "years of a skill",
        "leads a day",
        "lowest score for a brief",
    ],
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


def test_deal_breakers_take_every_company_size_and_refuse_any_other() -> None:
    error = refusal(DealBreakers, {**DEAL_BREAKERS, "company_sizes": ["1-10", "10,001+"]})

    assert (
        saved(DealBreakers, {**DEAL_BREAKERS, "company_sizes": COMPANY_SIZES})["company_sizes"]
        == COMPANY_SIZES
    )
    assert (error["type"], error["loc"]) == ("literal_error", ("company_sizes", 1))


def test_companies_applied_to_are_the_same_job_only_when_company_and_title_both_match() -> None:
    applied = [
        {"company": "Example Company", "title": "Designer"},
        {"company": "Example Company", "title": "Writer"},
        {"company": "EXAMPLE COMPANY", "title": "designer"},
    ]

    assert saved(Companies, {**COMPANIES, "applied": applied})["applied"] == applied[:2]


def test_pace_takes_no_lowest_score_as_never_writing_a_brief() -> None:
    assert saved(Pace, {**PACE, "brief_from_score": None})["brief_from_score"] is None
    assert refusal(Pace, {"leads_per_day": 10})["type"] == "missing"


@pytest.mark.parametrize(
    "model",
    [
        TargetTitles,
        TitleRange,
        Office,
        Places,
        Pay,
        Skill,
        Skills,
        Gaps,
        DealBreakers,
        Application,
        Companies,
        Pace,
        OwnRules,
        Profile,
    ],
    ids=lambda model: model.__name__,
)
def test_every_field_says_what_it_holds_for_a_form_and_for_a_model_reading_the_schema(
    model: type[BaseModel],
) -> None:
    undescribed = [name for name, field in model.model_fields.items() if not field.description]

    assert undescribed == []


def test_places_publishes_the_state_codes_it_takes_in_its_schema() -> None:
    for mode in ("validation", "serialization"):
        states = Places.model_json_schema(mode=mode)["properties"]["states"]

        assert states["items"] == {"type": "string", "enum": sorted(US_STATES)}, mode


def test_places_takes_exactly_the_fifty_states_and_dc_in_any_case() -> None:
    assert len(US_STATES) == 51
    assert set(US_STATES) == profile_sections.US_STATES
    lower = [code.lower() for code in US_STATES]

    assert saved(Places, {**PLACES, "states": lower})["states"] == US_STATES


def test_places_takes_every_state_sent_twice_since_its_cap_counts_after_repeats() -> None:
    twice = [*US_STATES, *(code.lower() for code in US_STATES)]

    assert saved(Places, {**PLACES, "states": twice})["states"] == US_STATES
