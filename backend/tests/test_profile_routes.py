import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from session_tokens import claims, signed
from settings_for_tests import make_settings
from sqlalchemy import create_engine, text

from job_board.app import create_app

REFUSED_BODY = b'{"detail":"sign-in required"}'


@asynccontextmanager
async def client_for(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def run(database_url: str, sql: str, **values: Any) -> list[Any]:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        result = connection.execute(text(sql), values)
        rows = list(result) if result.returns_rows else []
    engine.dispose()
    return rows


class Someone:
    """A person with a session token, whose row and profile the test removes after."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.clerk_user_id = f"user_{secrets.token_hex(12)}"
        self.headers = {"Authorization": f"Bearer {signed(claims(sub=self.clerk_user_id))}"}

    def person_id(self) -> int:
        (row,) = run(
            self.database_url,
            "SELECT id FROM people WHERE clerk_user_id = :user",
            user=self.clerk_user_id,
        )
        person_id: int = row.id
        return person_id

    def stored(self) -> list[Any]:
        return run(
            self.database_url,
            "SELECT document, created_at, updated_at FROM profiles WHERE person_id = :person",
            person=self.person_id(),
        )

    def remove(self) -> None:
        # The profile goes with the person.
        run(
            self.database_url,
            "DELETE FROM people WHERE clerk_user_id = :user",
            user=self.clerk_user_id,
        )


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


@pytest.fixture
def a_third_person(migrated_database_url: str) -> Iterator[Someone]:
    person = Someone(migrated_database_url)
    yield person
    person.remove()


async def test_reads_an_empty_profile_without_writing_one(
    someone: Someone, migrated_database_url: str
) -> None:
    async with client_for(migrated_database_url) as client:
        response = await client.get("/profile", headers=someone.headers)

    assert response.status_code == 200
    assert response.json() == {"target_titles": []}
    assert someone.stored() == []


async def test_saves_the_titles_as_the_rules_leave_them_and_reads_them_back(
    someone: Someone, migrated_database_url: str
) -> None:
    sent = {"titles": ["  Staff engineer ", "Data analyst", "staff ENGINEER"]}
    async with client_for(migrated_database_url) as client:
        saved = await client.put("/profile/target-titles", json=sent, headers=someone.headers)
        read = await client.get("/profile", headers=someone.headers)

    assert saved.status_code == 200
    assert saved.json() == read.json() == {"target_titles": ["Staff engineer", "Data analyst"]}
    (row,) = someone.stored()
    assert row.document == {"target_titles": ["Staff engineer", "Data analyst"]}


async def test_saving_titles_changes_no_other_section_and_touches_the_update_time(
    someone: Someone, migrated_database_url: str
) -> None:
    async with client_for(migrated_database_url) as client:
        await client.get("/me", headers=someone.headers)  # adds the person's row
        later_section = {"remote_only": True, "regions": ["Lisbon", "Remote"]}
        run(
            migrated_database_url,
            "INSERT INTO profiles (person_id, document, created_at, updated_at)"
            " VALUES (:person, CAST(:document AS jsonb), :then, :then)",
            person=someone.person_id(),
            document=json.dumps({"target_titles": ["Old title"], "later": later_section}),
            then="2026-01-01T00:00:00Z",
        )
        saved = await client.put(
            "/profile/target-titles", json={"titles": ["New title"]}, headers=someone.headers
        )

    # The answer is the profile as this code knows it; the stored document keeps the rest.
    assert saved.json() == {"target_titles": ["New title"]}
    (row,) = someone.stored()
    assert row.document == {"target_titles": ["New title"], "later": later_section}
    assert row.created_at.isoformat() == "2026-01-01T00:00:00+00:00"
    assert row.updated_at > row.created_at


async def test_each_person_reads_and_saves_only_their_own_profile(
    someone: Someone, someone_else: Someone, a_third_person: Someone, migrated_database_url: str
) -> None:
    async with client_for(migrated_database_url) as client:
        await client.put(
            "/profile/target-titles", json={"titles": ["Mine"]}, headers=someone.headers
        )
        await client.put(
            "/profile/target-titles", json={"titles": ["Theirs"]}, headers=someone_else.headers
        )
        await client.put(
            "/profile/target-titles", json={"titles": ["Mine, again"]}, headers=someone.headers
        )
        mine = await client.get("/profile", headers=someone.headers)
        theirs = await client.get("/profile", headers=someone_else.headers)
        # The third person has saved nothing while two rows exist, so a read
        # that lost its filter answers them someone else's titles.
        none_yet = await client.get("/profile", headers=a_third_person.headers)

    assert mine.json() == {"target_titles": ["Mine, again"]}
    assert theirs.json() == {"target_titles": ["Theirs"]}
    assert none_yet.json() == {"target_titles": []}
    assert [row.document for row in someone.stored()] == [{"target_titles": ["Mine, again"]}]
    assert [row.document for row in someone_else.stored()] == [{"target_titles": ["Theirs"]}]
    assert a_third_person.stored() == []


async def test_first_saves_at_once_make_one_row_holding_one_of_the_lists(
    someone: Someone, migrated_database_url: str
) -> None:
    lists = [[f"Title {number}"] for number in range(4)]
    async with client_for(migrated_database_url) as client:
        answers = await asyncio.gather(
            *(
                client.put(
                    "/profile/target-titles", json={"titles": titles}, headers=someone.headers
                )
                for titles in lists
            )
        )

    assert [answer.status_code for answer in answers] == [200] * len(lists)
    (row,) = someone.stored()
    assert row.document["target_titles"] in lists


async def test_saving_an_empty_list_clears_the_titles(
    someone: Someone, migrated_database_url: str
) -> None:
    async with client_for(migrated_database_url) as client:
        await client.put(
            "/profile/target-titles", json={"titles": ["Designer"]}, headers=someone.headers
        )
        cleared = await client.put(
            "/profile/target-titles", json={"titles": []}, headers=someone.headers
        )

    assert cleared.json() == {"target_titles": []}
    assert [row.document for row in someone.stored()] == [{"target_titles": []}]


@pytest.mark.parametrize(
    ("title", "rule"),
    [
        ("   ", "A target title cannot be blank"),
        ("Quoted " + "x" * 100, "A target title can be at most 100 characters"),
        ("Quoted\tanalyst", "A target title cannot contain control characters"),
        ("‮Quoted", "A target title cannot contain text direction controls"),
    ],
    ids=["blank", "too long", "a control character", "a direction control"],
)
async def test_refuses_a_title_breaking_a_rule_quoting_nothing_that_was_sent(
    someone: Someone, migrated_database_url: str, title: str, rule: str
) -> None:
    async with client_for(migrated_database_url) as client:
        response = await client.put(
            "/profile/target-titles",
            json={"titles": ["Designer", title, "Writer"]},
            headers=someone.headers,
        )

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    # The rule and where it applies, and no input or context to quote the body.
    assert set(error) == {"type", "loc", "msg"}
    assert error["msg"] == rule
    assert error["loc"] == ["body", "titles", 1]
    for sent in ("Designer", "Quoted", "Writer"):
        assert sent not in response.text
    assert someone.stored() == []


async def test_refuses_a_title_that_is_not_valid_text_as_a_rule_not_a_failure(
    someone: Someone, migrated_database_url: str
) -> None:
    # JSON can spell half of a surrogate pair, which no text encoding can hold.
    body = b'{"titles": ["Engineer \\ud800"]}'
    async with client_for(migrated_database_url) as client:
        response = await client.put(
            "/profile/target-titles",
            content=body,
            headers={**someone.headers, "Content-Type": "application/json"},
        )

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert set(error) == {"type", "loc", "msg"}
    assert error["msg"] == "A target title must be valid text"
    assert error["loc"] == ["body", "titles", 0]
    assert "Engineer" not in response.text
    assert someone.stored() == []


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/profile"), ("PUT", "/profile/target-titles")]
)
async def test_refuses_a_request_without_a_session_token_before_the_database(
    method: str, path: str, closed_port: int
) -> None:
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    async with client_for(unreachable) as client:
        response = await client.request(method, path, json={"titles": ["Designer"]})

    assert response.status_code == 401
    assert response.content == REFUSED_BODY


@pytest.mark.parametrize("authorization", [None, "Bearer not-a-session-token"], ids=["none", "bad"])
@pytest.mark.parametrize(
    "body",
    [b'{"titles": 5}', b'{"titles": ["   "]}', b'{"salary": 1}', b"[]"],
    ids=["not a list", "a blank title", "another key", "not an object"],
)
async def test_refuses_well_formed_json_without_a_valid_sign_in_with_the_one_401(
    body: bytes, authorization: str | None, closed_port: int
) -> None:
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    async with client_for(unreachable) as client:
        response = await client.put("/profile/target-titles", content=body, headers=headers)

    assert response.status_code == 401
    assert response.content == REFUSED_BODY


@pytest.mark.parametrize("authorization", [None, "Bearer not-a-session-token"], ids=["none", "bad"])
async def test_refuses_a_body_that_is_not_json_before_the_sign_in_saying_nothing_of_either(
    authorization: str | None, closed_port: int
) -> None:
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    async with client_for(unreachable) as client:
        response = await client.put("/profile/target-titles", content=b"{", headers=headers)

    # FastAPI decodes the body before any dependency runs, so this answer comes
    # first; it names the decoding error and its place, and nothing else.
    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["type"] == "json_invalid"
    assert error["loc"] == ["body", 1]
    assert "not-a-session-token" not in response.text
    assert "sign-in" not in response.text


def test_the_description_says_both_routes_need_a_bearer_token() -> None:
    paths = create_app(make_settings()).openapi()["paths"]
    read = paths["/profile"]["get"]
    save = paths["/profile/target-titles"]["put"]

    assert read["security"] == save["security"] == [{"HTTPBearer": []}]
    assert set(read["responses"]) == {"200", "401"}
    assert set(save["responses"]) == {"200", "401", "422"}
    assert "parameters" not in read
    assert "parameters" not in save
