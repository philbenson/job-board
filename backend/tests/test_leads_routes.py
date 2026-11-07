import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from session_tokens import claims, signed
from settings_for_tests import make_settings
from sqlalchemy import create_engine, text

from job_board.app import create_app
from job_board.leads import leads_statement

REFUSED_BODY = b'{"detail":"sign-in required"}'
START = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER = START + timedelta(days=1)


@asynccontextmanager
async def client_for(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@dataclass(frozen=True)
class Reader:
    """A person already in the table, and the session token that names them."""

    id: int
    headers: dict[str, str]


class Planted:
    """The people, postings and scores one test adds, all removed after it."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.people: list[int] = []
        self.postings: list[int] = []

    def _one(self, sql: str, **values: Any) -> int:
        with self.engine.begin() as connection:
            found: int = connection.execute(text(sql), values).scalar_one()
        return found

    def person(self) -> Reader:
        clerk_user_id = f"user_{secrets.token_hex(12)}"
        person_id = self._one(
            "INSERT INTO people (clerk_user_id) VALUES (:user) RETURNING id", user=clerk_user_id
        )
        self.people.append(person_id)
        token = signed(claims(sub=clerk_user_id))
        return Reader(person_id, {"Authorization": f"Bearer {token}"})

    def posting(
        self,
        *,
        title: str = "Staff Engineer",
        company: str | None = "Example Co",
        board: str = "example",
        location: str | None = "Remote",
        url: str = "https://boards.example.com/jobs/1",
        published: datetime | None = START,
        seen: datetime = START,
        closed: bool = False,
    ) -> int:
        posting_id = self._one(
            "INSERT INTO postings (source, board, external_id, title, company_name, location, "
            "url, content_html, first_published_at, source_updated_at, first_seen_at, "
            "last_seen_at, closed_at) VALUES ('greenhouse', :board, :external, :title, "
            ":company, :location, :url, '<p>Build the platform.</p>', :published, :seen, :seen, "
            ":seen, CASE WHEN :closed THEN now() END) RETURNING id",
            board=board,
            external=secrets.randbelow(10**12),
            title=title,
            company=company,
            location=location,
            url=url,
            published=published,
            seen=seen,
            closed=closed,
        )
        self.postings.append(posting_id)
        return posting_id

    def score(
        self,
        reader: Reader,
        posting_id: int,
        *,
        score: int | None = 3,
        reason: str | None = "A fair match.",
        outcome: str = "scored",
        scored_at: datetime = LATER,
    ) -> None:
        self._one(
            "INSERT INTO scores (person_id, posting_id, outcome, score, reason, model, scored_at) "
            "VALUES (:person, :posting, :outcome, :score, :reason, 'a-model', :scored_at) "
            "RETURNING id",
            person=reader.id,
            posting=posting_id,
            outcome=outcome,
            score=score,
            reason=reason,
            scored_at=scored_at,
        )

    def remove(self) -> None:
        # Each person's scores go with them, and each posting's with it.
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM people WHERE id = ANY(:ids)"), {"ids": self.people}
            )
            connection.execute(
                text("DELETE FROM postings WHERE id = ANY(:ids)"), {"ids": self.postings}
            )
        self.engine.dispose()


@pytest.fixture
def planted(migrated_database_url: str) -> Iterator[Planted]:
    plant = Planted(migrated_database_url)
    yield plant
    plant.remove()


async def leads_for(planted: Planted, reader: Reader) -> dict[str, Any]:
    async with client_for(planted.database_url) as client:
        response = await client.get("/leads", headers=reader.headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def ranked(body: dict[str, Any]) -> list[tuple[int, int, str]]:
    return [(lead["posting_id"], lead["score"], lead["reason"]) for lead in body["leads"]]


def with_times_read(lead: dict[str, Any]) -> dict[str, Any]:
    # Compared as instants, so the database server's time zone cannot matter.
    return {
        **lead,
        "published_at": lead["published_at"] and datetime.fromisoformat(lead["published_at"]),
        "scored_at": datetime.fromisoformat(lead["scored_at"]),
    }


async def test_answers_no_leads_for_someone_with_no_scores(planted: Planted) -> None:
    reader = planted.person()
    planted.posting()

    assert await leads_for(planted, reader) == {"leads": [], "total": 0}


async def test_each_person_sees_only_the_leads_scored_for_them_with_their_own_scores(
    planted: Planted,
) -> None:
    first, second = planted.person(), planted.person()
    shared, only_first, only_second = planted.posting(), planted.posting(), planted.posting()
    planted.score(first, shared, score=5, reason="Right on target.")
    planted.score(first, only_first, score=2, reason="A stretch.")
    planted.score(second, shared, score=1, reason="Another field.")
    planted.score(second, only_second, score=4, reason="A close match.")

    first_sees = await leads_for(planted, first)
    second_sees = await leads_for(planted, second)

    assert ranked(first_sees) == [(shared, 5, "Right on target."), (only_first, 2, "A stretch.")]
    assert ranked(second_sees) == [
        (only_second, 4, "A close match."),
        (shared, 1, "Another field."),
    ]
    assert first_sees["total"] == second_sees["total"] == 2


async def test_leaves_out_unreadable_ratings_and_closed_postings(planted: Planted) -> None:
    reader = planted.person()
    kept, unreadable, closed = planted.posting(), planted.posting(), planted.posting(closed=True)
    planted.score(reader, kept)
    planted.score(reader, unreadable, outcome="unreadable", score=None, reason=None)
    planted.score(reader, closed, score=5)

    body = await leads_for(planted, reader)

    assert ranked(body) == [(kept, 3, "A fair match.")]
    assert body["total"] == 1


async def test_orders_best_first_then_newest_published_then_newest_seen_then_highest_id(
    planted: Planted,
) -> None:
    reader = planted.person()
    # Planted out of order, so the answer's order cannot be the order of
    # insertion, and each one seen later has the lower id, so only the time
    # seen can put it first.
    undated_seen_later = planted.posting(published=None, seen=LATER)
    seen_later = planted.posting(published=START, seen=LATER)
    worst_and_newest = planted.posting(published=LATER + timedelta(days=1))
    undated = planted.posting(published=None, seen=START)
    lower_id = planted.posting(published=START, seen=START)
    newest = planted.posting(published=LATER)
    higher_id = planted.posting(published=START, seen=START)
    best_and_undated = planted.posting(published=None)
    planted.score(reader, best_and_undated, score=5)
    planted.score(reader, worst_and_newest, score=1)
    for posting in (undated, lower_id, newest, undated_seen_later, higher_id, seen_later):
        planted.score(reader, posting, score=3)

    body = await leads_for(planted, reader)

    assert [lead["posting_id"] for lead in body["leads"]] == [
        best_and_undated,
        newest,
        seen_later,
        higher_id,
        lower_id,
        undated_seen_later,
        undated,
        worst_and_newest,
    ]


def test_breaks_every_remaining_tie_by_the_highest_posting_id() -> None:
    # Read from the statement, not from an answer: at these sizes PostgreSQL
    # may happen to list ties by id anyway, so no planted rows could show the
    # key missing every time.
    compiled = str(leads_statement(1))
    order_by = compiled.split("ORDER BY", 1)[1].split("LIMIT", 1)[0].strip()

    assert order_by.endswith("postings.id DESC")


async def test_answers_the_best_100_and_counts_every_lead(planted: Planted) -> None:
    reader = planted.person()
    # The newest posting, so only its score can put it last.
    worst = planted.posting(published=LATER)
    planted.score(reader, worst, score=1)
    for _ in range(100):
        planted.score(reader, planted.posting(), score=3)

    body = await leads_for(planted, reader)

    assert len(body["leads"]) == 100
    assert worst not in [lead["posting_id"] for lead in body["leads"]]
    assert body["total"] == 101


async def test_answers_each_leads_fields_naming_the_board_when_no_company_is_given(
    planted: Planted,
) -> None:
    reader = planted.person()
    named = planted.posting(
        title="Platform Lead",
        company="Example Co",
        location="Remote",
        url="https://boards.example.com/jobs/7",
        published=START,
    )
    unnamed = planted.posting(
        title="Staff Engineer",
        company=None,
        board="example-board",
        location=None,
        url="https://boards.example.com/jobs/8",
        published=None,
    )
    planted.score(reader, named, score=5, reason="Right on target.", scored_at=LATER)
    planted.score(
        reader, unnamed, score=4, reason="A close match.", scored_at=LATER + timedelta(hours=1)
    )

    body = await leads_for(planted, reader)

    assert [with_times_read(lead) for lead in body["leads"]] == [
        {
            "posting_id": named,
            "title": "Platform Lead",
            "company": "Example Co",
            "location": "Remote",
            "url": "https://boards.example.com/jobs/7",
            "published_at": START,
            "score": 5,
            "reason": "Right on target.",
            "scored_at": LATER,
        },
        {
            "posting_id": unnamed,
            "title": "Staff Engineer",
            "company": "example-board",
            "location": None,
            "url": "https://boards.example.com/jobs/8",
            "published_at": None,
            "score": 4,
            "reason": "A close match.",
            "scored_at": LATER + timedelta(hours=1),
        },
    ]
    assert body["total"] == 2


async def test_refuses_a_request_without_a_session_token_before_the_database(
    closed_port: int,
) -> None:
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    async with client_for(unreachable) as client:
        response = await client.get("/leads")

    assert response.status_code == 401
    assert response.content == REFUSED_BODY
