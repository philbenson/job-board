"""Saving and reading the profile's sections through their routes."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from profile_requests import NEW_PROFILE, REFUSED_BODY, Someone, client_for, run
from settings_for_tests import make_settings

from job_board.app import create_app


@dataclass(frozen=True)
class Section:
    path: str
    key: str  # where the section sits in the document and the answer
    sent: dict[str, Any]
    answer: dict[str, Any]  # what the rules leave of what was sent


SECTIONS = {
    "title range": Section(
        "/profile/title-range",
        "title_range",
        {
            "nearby_titles": [" Senior designer ", "senior DESIGNER", "Design lead"],
            "lower_level_ok": True,
        },
        {"nearby_titles": ["Senior designer", "Design lead"], "lower_level_ok": True},
    ),
    "places": Section(
        "/profile/places",
        "places",
        {
            "remote_ok": False,
            "offices": [{"city": "Lisbon", "days_a_week": 3}, {"city": "LISBON", "days_a_week": 5}],
            "states": ["ny", "NY", "dc"],
            "will_relocate": False,
            "relocate_for": ["Example Company"],
        },
        {
            "remote_ok": False,
            "offices": [{"city": "Lisbon", "days_a_week": 3}],
            "states": ["NY", "DC"],
            "will_relocate": False,
            "relocate_for": ["Example Company"],
        },
    ),
    "pay": Section(
        "/profile/pay",
        "pay",
        {"floor_usd": 120_000, "ask_usd": 150_000},
        {"floor_usd": 120_000, "ask_usd": 150_000},
    ),
}


@pytest.fixture
def someone(migrated_database_url: str) -> Iterator[Someone]:
    person = Someone(migrated_database_url)
    yield person
    person.remove()


@pytest.fixture
def someone_else(migrated_database_url: str) -> Iterator[Someone]:
    person = Someone(migrated_database_url)
    yield person
    person.remove()


def store(someone: Someone, document: dict[str, Any]) -> None:
    run(
        someone.database_url,
        "INSERT INTO profiles (person_id, document) VALUES (:person, CAST(:document AS jsonb))",
        person=someone.person_id(),
        document=json.dumps(document),
    )


@pytest.mark.parametrize("section", SECTIONS.values(), ids=SECTIONS.keys())
async def test_saves_each_section_as_its_rules_leave_it_and_reads_it_back(
    someone: Someone, migrated_database_url: str, section: Section
) -> None:
    async with client_for(migrated_database_url) as client:
        saved = await client.put(section.path, json=section.sent, headers=someone.headers)
        read = await client.get("/profile", headers=someone.headers)

    assert saved.status_code == 200
    assert saved.json() == read.json() == {**NEW_PROFILE, section.key: section.answer}
    assert [row.document for row in someone.stored()] == [{section.key: section.answer}]


@pytest.mark.parametrize("section", SECTIONS.values(), ids=SECTIONS.keys())
async def test_saving_a_section_leaves_every_other_section_and_an_unknown_key_untouched(
    someone: Someone, migrated_database_url: str, section: Section
) -> None:
    others = {other.key: other.answer for other in SECTIONS.values() if other != section}
    before = {"target_titles": ["Designer"], **others, "later": {"anything": [1, 2]}}
    async with client_for(migrated_database_url) as client:
        await client.get("/me", headers=someone.headers)  # adds the person's row
        store(someone, before)
        saved = await client.put(section.path, json=section.sent, headers=someone.headers)

    assert saved.json() == {
        **NEW_PROFILE,
        "target_titles": ["Designer"],
        **others,
        section.key: section.answer,
    }
    assert [row.document for row in someone.stored()] == [{**before, section.key: section.answer}]


@pytest.mark.parametrize("section", SECTIONS.values(), ids=SECTIONS.keys())
async def test_a_section_one_person_saves_is_not_another_persons(
    someone: Someone, someone_else: Someone, migrated_database_url: str, section: Section
) -> None:
    async with client_for(migrated_database_url) as client:
        await client.put(section.path, json=section.sent, headers=someone.headers)
        theirs = await client.get("/profile", headers=someone_else.headers)

    assert theirs.json() == NEW_PROFILE
    assert someone_else.stored() == []


async def test_reads_a_stored_section_holding_a_key_this_code_does_not_know(
    someone: Someone, migrated_database_url: str
) -> None:
    async with client_for(migrated_database_url) as client:
        await client.get("/me", headers=someone.headers)
        store(someone, {"pay": {"floor_usd": 1, "ask_usd": 2, "currency": "EUR"}})
        read = await client.get("/profile", headers=someone.headers)

    assert read.status_code == 200
    assert read.json() == {**NEW_PROFILE, "pay": {"floor_usd": 1, "ask_usd": 2}}


def section_body(name: str, **changes: Any) -> dict[str, Any]:
    return {**SECTIONS[name].sent, **changes}


@pytest.mark.parametrize(
    ("path", "body", "loc", "rule"),
    [
        (
            "/profile/title-range",
            section_body("title range", nearby_titles=["Quoted", "​"]),
            ["body", "nearby_titles", 1],
            "A nearby title cannot be blank",
        ),
        (
            "/profile/title-range",
            section_body("title range", nearby_titles=[f"Quoted {n}" for n in range(21)]),
            ["body", "nearby_titles"],
            "You can list at most 20 nearby titles",
        ),
        (
            "/profile/places",
            section_body("places", offices=[{"city": "Quoted " + "x" * 100, "days_a_week": 1}]),
            ["body", "offices", 0, "city"],
            "A city can be at most 100 characters",
        ),
        (
            "/profile/places",
            section_body("places", states=["NY", "QU"]),
            ["body", "states", 1],
            "A state must be the two-letter postal code of a US state or DC",
        ),
        (
            "/profile/places",
            section_body("places", will_relocate=True, relocate_for=["Quoted Company"]),
            ["body", "relocate_for"],
            "List companies you would move for only if you would not move otherwise",
        ),
        (
            "/profile/pay",
            {"floor_usd": 150_000, "ask_usd": 140_000},
            ["body", "ask_usd"],
            "The ask cannot be below the floor",
        ),
    ],
    ids=[
        "a blank nearby title",
        "too many nearby titles",
        "a city too long",
        "an unknown state",
        "companies to move for while moving anyway",
        "an ask below the floor",
    ],
)
async def test_refuses_a_section_breaking_a_rule_quoting_nothing_and_storing_nothing(
    someone: Someone,
    migrated_database_url: str,
    path: str,
    body: dict[str, Any],
    loc: list[str | int],
    rule: str,
) -> None:
    async with client_for(migrated_database_url) as client:
        response = await client.put(path, json=body, headers=someone.headers)

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert set(error) == {"type", "loc", "msg"}
    assert (error["msg"], error["loc"]) == (rule, loc)
    for sent in ("Quoted", "QU", "140000"):
        assert sent not in response.text
    assert someone.stored() == []


@pytest.mark.parametrize(
    ("path", "body", "loc", "kind"),
    [
        ("/profile/pay", {"floor_usd": "100", "ask_usd": 200}, ["body", "floor_usd"], "int_type"),
        ("/profile/pay", {"floor_usd": 1.5, "ask_usd": 200}, ["body", "floor_usd"], "int_type"),
        ("/profile/pay", {"floor_usd": True, "ask_usd": 200}, ["body", "floor_usd"], "int_type"),
        ("/profile/pay", {"floor_usd": 100}, ["body", "ask_usd"], "missing"),
        (
            "/profile/pay",
            {"floor_usd": 1, "ask_usd": 2, "bonus_usd": 3},
            ["body", "bonus_usd"],
            "extra_forbidden",
        ),
        (
            "/profile/places",
            section_body("places", remote_ok="true"),
            ["body", "remote_ok"],
            "bool_type",
        ),
        (
            "/profile/places",
            section_body("places", offices=[{"city": "Lisbon", "days_a_week": "2"}]),
            ["body", "offices", 0, "days_a_week"],
            "int_type",
        ),
        (
            "/profile/places",
            section_body("places", offices=[{"city": "Lisbon", "days_a_week": 2, "desk": 1}]),
            ["body", "offices", 0, "desk"],
            "extra_forbidden",
        ),
        (
            "/profile/title-range",
            section_body("title range", nearby_titles="Designer"),
            ["body", "nearby_titles"],
            "list_type",
        ),
    ],
    ids=[
        "a number as text",
        "a fraction",
        "a boolean as a number",
        "a missing field",
        "a field it does not name",
        "a boolean as text",
        "a number as text inside a list",
        "a field it does not name inside a list",
        "text for a list",
    ],
)
async def test_refuses_a_value_of_another_type_without_converting_it(
    someone: Someone,
    migrated_database_url: str,
    path: str,
    body: dict[str, Any],
    loc: list[str | int],
    kind: str,
) -> None:
    async with client_for(migrated_database_url) as client:
        response = await client.put(path, json=body, headers=someone.headers)

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert (error["type"], error["loc"]) == (kind, loc)
    assert someone.stored() == []


@pytest.mark.parametrize("section", SECTIONS.values(), ids=SECTIONS.keys())
async def test_refuses_each_section_without_a_session_token_before_the_database(
    section: Section, closed_port: int
) -> None:
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    async with client_for(unreachable) as client:
        response = await client.put(section.path, json=section.sent)

    assert response.status_code == 401
    assert response.content == REFUSED_BODY


def test_the_description_says_every_section_route_needs_a_bearer_token() -> None:
    paths = create_app(make_settings()).openapi()["paths"]

    for section in SECTIONS.values():
        save = paths[section.path]["put"]
        assert save["security"] == [{"HTTPBearer": []}], section.path
        assert set(save["responses"]) == {"200", "401", "422"}, section.path
