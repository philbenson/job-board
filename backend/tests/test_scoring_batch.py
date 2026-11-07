"""Scoring one person's batch, and everyone's: who, which postings, and every outcome.

The model is a fake, or the real one pointed at a canned local server. Each
test starts from empty tables in this module's own database, since a batch
reads every open posting.
"""

import base64
import json
import logging
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import anthropic
import httpx2
import pytest
from canned_anthropic import Reply, canned_anthropic, error, message, rating
from langchain_core.exceptions import ModelRefusalError, OutputParserException
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import RunnableLambda
from settings_for_tests import MODEL_KEY_ENCRYPTION_KEY
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from job_board.database import make_sessionmaker
from job_board.model_key.check import CHECK_MODEL
from job_board.model_key.sealing import seal
from job_board.scoring.batch import (
    BATCH_SIZE,
    LOCK_CLASS,
    BatchResult,
    score_everyone,
    score_person,
)
from job_board.scoring.model import ModelFactory, Rating, RatingModel, anthropic_model
from job_board.scoring.people import candidate, eligible_people

SERVICE_KEY = base64.urlsafe_b64decode(MODEL_KEY_ENCRYPTION_KEY)
TITLES = {"target_titles": ["Staff Engineer", "Platform Lead"]}
RULE = "Nothing in advertising, however the posting words it."
WHOLE_PROFILE = {
    **TITLES,
    "places": {
        "remote_ok": True,
        "offices": [],
        "states": ["MA"],
        "will_relocate": False,
        "relocate_for": [],
    },
    "pay": {"floor_usd": 150000, "ask_usd": 180000},
    "deal_breakers": {"industries": ["Gambling"], "company_sizes": [], "no_agencies": True},
    "pace": {"leads_per_day": 10, "brief_from_score": None},
    "own_rules": {"rules": [RULE]},
}
START = datetime(2026, 9, 1, tzinfo=UTC)
GOOD = Rating(score=4, reason="A close match.")
UNREADABLE = OutputParserException("Failed to parse Rating from completion")


def new_key() -> str:
    return f"sk-ant-api03-{secrets.token_urlsafe(48)}"


@pytest.fixture
async def engine(module_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(module_database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE people, postings RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


async def add_person(
    engine: AsyncEngine,
    document: dict[str, Any] | None = TITLES,
    *,
    key: str | None = None,
    failure: str | None = None,
    sealed: Callable[[str, int], bytes] | None = None,
) -> int:
    """A person with this profile document (None: no profile row) and a sealed key.

    ``key`` defaults to a fresh one; pass ``sealed`` to seal it some other way.
    Pass ``key=""`` for a person with no key at all.
    """
    async with engine.begin() as connection:
        person: int = (
            await connection.execute(
                text("INSERT INTO people (clerk_user_id) VALUES (:user) RETURNING id"),
                {"user": f"user_{secrets.token_hex(12)}"},
            )
        ).scalar_one()
        if document is not None:
            await connection.execute(
                text("INSERT INTO profiles (person_id, document) VALUES (:person, :document)"),
                {"person": person, "document": json.dumps(document)},
            )
        if key != "":
            plain = key or new_key()
            sealed_key = (
                sealed(plain, person)
                if sealed
                else seal(plain, person, "anthropic", service_key=SERVICE_KEY)
            )
            await connection.execute(
                text(
                    "INSERT INTO model_keys (person_id, provider, sealed_key, last_four, "
                    "checked_at, failure, failed_at) VALUES (:person, 'anthropic', :sealed, "
                    ":last_four, now(), CAST(:failure AS text), CASE WHEN CAST(:failure AS text) "
                    "IS NOT NULL THEN now() END)"
                ),
                {
                    "person": person,
                    "sealed": sealed_key,
                    "last_four": plain[-4:],
                    "failure": failure,
                },
            )
    return person


async def add_posting(
    engine: AsyncEngine,
    *,
    published: datetime | None = START,
    seen: datetime = START,
    closed: bool = False,
    content: str | None = "<p>Build the platform.</p>",
) -> int:
    async with engine.begin() as connection:
        posting: int = (
            await connection.execute(
                text(
                    "INSERT INTO postings (source, board, external_id, title, company_name, "
                    "location, url, content_html, first_published_at, source_updated_at, "
                    "first_seen_at, last_seen_at, closed_at) VALUES ('greenhouse', 'example', "
                    ":external, 'Staff Engineer', 'Example Co', 'Remote', "
                    "'https://boards.example.com/1', :content, :published, :seen, :seen, :seen, "
                    "CASE WHEN :closed THEN now() END) RETURNING id"
                ),
                {
                    "external": secrets.randbelow(10**12),
                    "content": content,
                    "published": published,
                    "seen": seen,
                    "closed": closed,
                },
            )
        ).scalar_one()
    return posting


async def scores_of(engine: AsyncEngine, person: int) -> list[tuple[int, str, int | None]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT posting_id, outcome, score, reason, model FROM scores "
                "WHERE person_id = :person ORDER BY id"
            ),
            {"person": person},
        )
        result = []
        for posting, outcome, score, reason, model in rows:
            assert model == CHECK_MODEL
            assert (reason is not None) == (outcome == "scored")
            result.append((posting, outcome, score))
        return result


async def failure_of(engine: AsyncEngine, person: int) -> tuple[str | None, bool]:
    """The key's failure, and whether its time is set."""
    async with engine.connect() as connection:
        failure, failed_at = (
            await connection.execute(
                text("SELECT failure, failed_at FROM model_keys WHERE person_id = :person"),
                {"person": person},
            )
        ).one()
    return failure, failed_at is not None


class Fake:
    """A model factory whose models answer from ``replies`` in turn, the last one again."""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.keys: list[str] = []
        self.calls = 0

    def __call__(self, key: str) -> RatingModel:
        self.keys.append(key)

        async def answer(messages: LanguageModelInput) -> object:
            self.calls += 1
            reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
            if isinstance(reply, BaseException):
                raise reply
            return reply

        return RunnableLambda(answer)


def status_error(status: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    kinds: dict[int, type[anthropic.APIStatusError]] = {
        401: anthropic.AuthenticationError,
        403: anthropic.PermissionDeniedError,
        404: anthropic.NotFoundError,
        429: anthropic.RateLimitError,
        500: anthropic.InternalServerError,
        529: anthropic.InternalServerError,
    }
    return kinds.get(status, anthropic.APIStatusError)("refused", response=response, body=None)


def connection_error(kind: type[anthropic.APIConnectionError]) -> anthropic.APIConnectionError:
    return kind(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


async def run(engine: AsyncEngine, person: int, factory: ModelFactory) -> BatchResult:
    return await score_person(
        engine, make_sessionmaker(engine), person, service_key=SERVICE_KEY, model_factory=factory
    )


# Who is scored


async def test_scores_only_people_with_a_working_key_and_a_title(engine: AsyncEngine) -> None:
    first = await add_person(engine)
    await add_person(engine, key="")  # no key
    for failure in ("rejected", "not-permitted", "no-credit"):
        await add_person(engine, failure=failure)
    await add_person(engine, None)  # no profile row
    await add_person(engine, {})  # a profile with no titles key
    await add_person(engine, {"target_titles": []})
    await add_person(engine, {**WHOLE_PROFILE, "target_titles": []})  # all else, but no titles
    second = await add_person(engine, {"target_titles": ["Engineer"], "other": 1})
    async with make_sessionmaker(engine)() as session:
        assert await eligible_people(session) == [first, second]


async def test_scores_a_person_whose_section_holds_a_key_this_code_does_not_name(
    engine: AsyncEngine,
) -> None:
    # A section saved by newer code may hold a key this code does not know;
    # the profile still reads, as the profile route reads it, and is sent whole.
    pay = {"floor_usd": 90000, "ask_usd": 120000, "currency": "USD"}
    person = await add_person(engine, {"target_titles": ["Engineer"], "pay": pay})
    async with make_sessionmaker(engine)() as session:
        assert await eligible_people(session) == [person]
    await add_posting(engine)
    with canned_anthropic(rating(3, "A partial match.")) as server:
        assert (await run(engine, person, real(server.url))).rated == 1
    [block] = server.received[0].body["system"]
    assert "What they ask for: $120,000" in block["text"]
    assert "currency" not in block["text"]


async def test_keeps_the_persons_profile_out_of_the_candidates_repr(engine: AsyncEngine) -> None:
    person = await add_person(engine, WHOLE_PROFILE)
    async with make_sessionmaker(engine)() as session:
        found = await candidate(session, person)
    assert found is not None
    assert found.profile.own_rules is not None and found.profile.own_rules.rules == [RULE]
    assert RULE not in repr(found)
    assert "Staff Engineer" not in repr(found)


async def test_scores_everyone_who_qualifies_in_order_of_id(engine: AsyncEngine) -> None:
    people = [await add_person(engine) for _ in range(3)]
    await add_person(engine, {})
    await add_posting(engine)
    fake = Fake(GOOD)
    results = await score_everyone(
        engine, make_sessionmaker(engine), service_key=SERVICE_KEY, model_factory=fake
    )
    assert [result.person_id for result in results] == people
    assert all(result.end == "finished" and result.rated == 1 for result in results)


# Which postings


async def test_rates_the_newest_open_unscored_postings_up_to_the_batch_size(
    engine: AsyncEngine,
) -> None:
    person = await add_person(engine)
    later = START + timedelta(days=1)
    expected: list[int] = []
    # Published newest first; ties on publishing broken by first seen, then by id.
    for day in range(BATCH_SIZE - 6, 0, -1):
        expected.append(await add_posting(engine, published=START + timedelta(days=day)))
    tied_seen_later = await add_posting(engine, published=START, seen=later)
    tied_both = [await add_posting(engine, published=START, seen=START) for _ in range(2)]
    expected += [tied_seen_later, *reversed(tied_both)]
    # Never published dates come after every dated one, newest first seen first.
    undated_older = await add_posting(engine, published=None, seen=START)
    undated_newer = await add_posting(engine, published=None, seen=later)
    expected += [undated_newer, undated_older]
    assert len(expected) == BATCH_SIZE - 1
    overflow = await add_posting(engine, published=None, seen=START - timedelta(days=1))
    left_over = await add_posting(engine, published=None, seen=START - timedelta(days=2))
    expected.append(overflow)
    await add_posting(engine, published=START + timedelta(days=99), closed=True)

    result = await run(engine, person, Fake(GOOD))
    assert result == BatchResult(person, rated=BATCH_SIZE, unreadable=0, end="finished")
    assert [posting for posting, _, _ in await scores_of(engine, person)] == expected

    again = await run(engine, person, Fake(GOOD))
    assert again.rated == 1
    assert [posting for posting, _, _ in await scores_of(engine, person)][-1] == left_over


async def test_rates_nothing_twice_unreadable_replies_included(engine: AsyncEngine) -> None:
    person = await add_person(engine)
    for _ in range(3):
        await add_posting(engine)
    first = await run(engine, person, Fake(GOOD, UNREADABLE, ModelRefusalError()))
    assert (first.rated, first.unreadable, first.end) == (1, 2, "finished")

    fake = Fake(GOOD)
    second = await run(engine, person, fake)
    assert (second.rated, second.unreadable, second.end) == (0, 0, "finished")
    assert fake.calls == 0
    assert fake.keys == []  # no postings, so no model is built


async def test_another_persons_scores_do_not_count_as_this_persons(engine: AsyncEngine) -> None:
    first, second = await add_person(engine), await add_person(engine)
    await add_posting(engine)
    await run(engine, first, Fake(GOOD))
    assert (await run(engine, second, Fake(GOOD))).rated == 1


# The lock

TRY_LOCK = text("SELECT pg_try_advisory_lock(:lock_class, :id)")
UNLOCK = text("SELECT pg_advisory_unlock(:lock_class, :id)")


async def test_skips_a_person_whose_batch_another_run_holds(
    engine: AsyncEngine, module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    person = await add_person(engine)
    await add_posting(engine)
    holder = create_engine(module_database_url)
    fake = Fake(GOOD)
    with holder.connect() as connection:
        assert connection.execute(TRY_LOCK, {"lock_class": LOCK_CLASS, "id": person}).scalar()
        result = await run(engine, person, fake)
        connection.execute(UNLOCK, {"lock_class": LOCK_CLASS, "id": person})
    holder.dispose()

    assert result == BatchResult(person, rated=0, unreadable=0, end="locked")
    assert fake.keys == [] and await scores_of(engine, person) == []
    assert f"person {person}: 0 rated, 0 unreadable, locked" in caplog.messages


async def test_lets_go_of_the_lock_when_the_batch_ends(
    engine: AsyncEngine, module_database_url: str
) -> None:
    person = await add_person(engine)
    await add_posting(engine)
    await run(engine, person, Fake(status_error(500)))
    other = create_engine(module_database_url)
    with other.connect() as connection:
        taken = connection.execute(TRY_LOCK, {"lock_class": LOCK_CLASS, "id": person})
        assert taken.scalar() is True
    other.dispose()


async def test_takes_its_lock_in_the_two_key_space_leaving_the_one_key_space_free(
    engine: AsyncEngine, module_database_url: str
) -> None:
    person = await add_person(engine)
    await add_posting(engine)
    holder = create_engine(module_database_url)
    seen: list[tuple[int, int, int]] = []

    def factory(key: str) -> RatingModel:
        async def answer(messages: LanguageModelInput) -> Rating:
            with holder.connect() as probe:
                seen.extend(
                    (row[0], row[1], row[2])
                    for row in probe.execute(
                        text(
                            "SELECT classid::bigint, objid::bigint, objsubid FROM pg_locks "
                            "WHERE locktype = 'advisory' AND granted"
                        )
                    )
                )
            return GOOD

        return RunnableLambda(answer)

    with holder.connect() as connection:
        # Someone else's one-key lock on the same number does not hold scoring up.
        assert connection.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": person}).scalar()
        result = await run(engine, person, factory)
        connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": person})
    holder.dispose()

    assert result.end == "finished"
    assert (LOCK_CLASS, person, 2) in seen


async def test_stops_a_batch_whose_lock_was_lost_and_goes_on_to_the_next_person(
    engine: AsyncEngine, module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    first, second = await add_person(engine), await add_person(engine)
    for _ in range(2):
        await add_posting(engine)
    killer = create_engine(module_database_url)
    asked: list[int] = []

    def factory(key: str) -> RatingModel:
        async def answer(messages: LanguageModelInput) -> Rating:
            asked.append(len(asked))
            if len(asked) == 1:  # the first person's first posting: their lock's session ends
                with killer.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE "
                            "locktype = 'advisory' AND classid = :lock_class AND objid = :id "
                            "AND objsubid = 2"
                        ),
                        {"lock_class": LOCK_CLASS, "id": first},
                    )
            return GOOD

        return RunnableLambda(answer)

    results = await score_everyone(
        engine, make_sessionmaker(engine), service_key=SERVICE_KEY, model_factory=factory
    )
    killer.dispose()

    assert results[0] == BatchResult(first, 0, 0, "stopped", "lost-the-lock")
    assert results[1] == BatchResult(second, 2, 0, "finished")
    assert await scores_of(engine, first) == []
    assert len(await scores_of(engine, second)) == 2


async def test_holds_no_transaction_open_while_the_model_answers(
    engine: AsyncEngine, module_database_url: str
) -> None:
    person = await add_person(engine)
    for _ in range(2):
        await add_posting(engine)
    probe = create_engine(module_database_url, isolation_level="AUTOCOMMIT")
    seen: list[int] = []

    def factory(key: str) -> RatingModel:
        async def answer(messages: LanguageModelInput) -> Rating:
            with probe.connect() as connection:
                seen.append(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                            "current_database() AND state LIKE 'idle in transaction%'"
                        )
                    ).scalar_one()
                )
            return GOOD

        return RunnableLambda(answer)

    await run(engine, person, factory)
    probe.dispose()
    assert seen == [0, 0]


# Each outcome, through a fake model


async def test_keeps_a_rating_and_an_unreadable_reply(engine: AsyncEngine) -> None:
    person = await add_person(engine)
    first, second = await add_posting(engine), await add_posting(engine, seen=START - timedelta(1))
    result = await run(engine, person, Fake(Rating(score=5, reason="Exact."), UNREADABLE))
    assert result == BatchResult(person, rated=1, unreadable=1, end="finished")
    assert await scores_of(engine, person) == [(first, "scored", 5), (second, "unreadable", None)]


async def test_records_nothing_more_for_a_posting_scored_while_its_rating_was_asked(
    engine: AsyncEngine,
) -> None:
    person = await add_person(engine)
    posting = await add_posting(engine)

    def factory(key: str) -> RatingModel:
        async def answer(messages: LanguageModelInput) -> Rating:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO scores (person_id, posting_id, outcome, model) "
                        "VALUES (:person, :posting, 'unreadable', :model)"
                    ),
                    {"person": person, "posting": posting, "model": CHECK_MODEL},
                )
            return GOOD

        return RunnableLambda(answer)

    result = await run(engine, person, factory)
    assert result.end == "finished"
    assert await scores_of(engine, person) == [(posting, "unreadable", None)]


async def test_records_a_reason_holding_a_nul_as_unreadable_and_goes_on(
    engine: AsyncEngine,
) -> None:
    person = await add_person(engine)
    first, second = await add_posting(engine), await add_posting(engine, seen=START - timedelta(1))
    with canned_anthropic(rating(3, "Fine\u0000"), rating(4, "A close match.")) as server:
        result = await run(engine, person, real(server.url))

    assert result == BatchResult(person, rated=1, unreadable=1, end="finished")
    assert await scores_of(engine, person) == [(first, "unreadable", None), (second, "scored", 4)]
    assert len(server.received) == 2


async def test_records_a_reply_cut_off_at_the_limit_as_unreadable_logs_it_and_goes_on(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    person = await add_person(engine)
    first, second, third = [
        await add_posting(engine, seen=START - timedelta(days=age)) for age in range(3)
    ]
    cut_off = message('{"score": 4, "reason": "Cut short in the mid', stop_reason="max_tokens")
    with canned_anthropic(rating(5, "Exact."), cut_off, rating(2, "A different field.")) as server:
        result = await run(engine, person, real(server.url))

    assert result == BatchResult(person, rated=2, unreadable=1, end="finished")
    assert await scores_of(engine, person) == [
        (first, "scored", 5),
        (second, "unreadable", None),
        (third, "scored", 2),
    ]
    assert len(server.received) == 3
    ours = [record for record in caplog.records if record.name.startswith("job_board.scoring")]
    assert [(record.levelno, record.getMessage()) for record in ours] == [
        (logging.WARNING, f"person {person}, posting {second}: reply cut off at the token limit"),
        (logging.INFO, f"person {person}: 2 rated, 1 unreadable, finished"),
    ]
    assert "Cut short" not in caplog.text


@pytest.mark.parametrize(
    ("status", "failure"),
    [(401, "rejected"), (403, "not-permitted"), (402, "no-credit")],
)
async def test_marks_the_key_and_stops_when_anthropic_refuses_it(
    engine: AsyncEngine, status: int, failure: str
) -> None:
    person = await add_person(engine)
    postings = [await add_posting(engine, seen=START - timedelta(n)) for n in range(4)]
    fake = Fake(GOOD, UNREADABLE, status_error(status), GOOD)
    result = await run(engine, person, fake)

    assert result == BatchResult(person, rated=1, unreadable=1, end="stopped", reason=failure)
    assert fake.calls == 3
    assert await scores_of(engine, person) == [
        (postings[0], "scored", 4),
        (postings[1], "unreadable", None),
    ]
    assert await failure_of(engine, person) == (failure, True)
    async with make_sessionmaker(engine)() as session:
        assert person not in await eligible_people(session)


@pytest.mark.parametrize(
    ("error_of", "reason"),
    [
        (lambda: status_error(429), "rate-limited"),
        (lambda: status_error(500), "server-error"),
        (lambda: status_error(529), "server-error"),
        (lambda: status_error(408), "timed-out"),
        (lambda: connection_error(anthropic.APIConnectionError), "connection-error"),
        (lambda: connection_error(anthropic.APITimeoutError), "timed-out"),
        (lambda: status_error(400), "refused-400"),
        (lambda: status_error(404), "model-not-found"),
    ],
    ids=["429", "500", "529", "408", "connection", "timeout", "400", "404"],
)
async def test_stops_and_leaves_the_posting_for_the_next_run_when_the_request_fails(
    engine: AsyncEngine, error_of: Callable[[], Exception], reason: str
) -> None:
    person = await add_person(engine)
    first, second = await add_posting(engine), await add_posting(engine, seen=START - timedelta(1))
    result = await run(engine, person, Fake(GOOD, error_of()))

    assert result == BatchResult(person, rated=1, unreadable=0, end="stopped", reason=reason)
    assert await scores_of(engine, person) == [(first, "scored", 4)]
    assert await failure_of(engine, person) == (None, False)

    assert (await run(engine, person, Fake(GOOD))).rated == 1
    assert await scores_of(engine, person) == [(first, "scored", 4), (second, "scored", 4)]


async def test_does_not_mark_a_key_saved_again_while_the_batch_ran(engine: AsyncEngine) -> None:
    person = await add_person(engine)
    await add_posting(engine)

    def factory(key: str) -> RatingModel:
        async def answer(messages: LanguageModelInput) -> Rating:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE model_keys SET sealed_key = :sealed WHERE person_id = :person"),
                    {
                        "person": person,
                        "sealed": seal(new_key(), person, "anthropic", service_key=SERVICE_KEY),
                    },
                )
            raise status_error(401)

        return RunnableLambda(answer)

    result = await run(engine, person, factory)
    assert (result.end, result.reason) == ("stopped", "rejected")
    assert await failure_of(engine, person) == (None, False)


# The sealed key


async def test_gives_the_model_the_persons_own_key(engine: AsyncEngine) -> None:
    key = new_key()
    person = await add_person(engine, key=key)
    await add_posting(engine)
    fake = Fake(GOOD)
    await run(engine, person, fake)
    assert fake.keys == [key]


OTHER_SERVICE_KEY = secrets.token_bytes(32)


@pytest.mark.parametrize(
    "sealed",
    [
        lambda key, who: seal(key, who, "anthropic", service_key=OTHER_SERVICE_KEY),
        lambda key, who: b"\x01",
    ],
    ids=["another-service-key", "too-short-to-name-one"],
)
async def test_skips_a_key_not_sealed_with_this_service_key(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture, sealed: Callable[[str, int], bytes]
) -> None:
    caplog.set_level(logging.INFO)
    person = await add_person(engine, sealed=sealed)
    await add_posting(engine)
    fake = Fake(GOOD)
    result = await run(engine, person, fake)

    assert result == BatchResult(
        person, rated=0, unreadable=0, end="skipped", reason="not-sealed-with-this-service-key"
    )
    assert fake.keys == []
    assert await failure_of(engine, person) == (None, False)
    [line] = [record for record in caplog.records if f"person {person}:" in record.getMessage()]
    assert "skipped" in line.getMessage()
    assert line.levelno == logging.WARNING  # a service key that differs is the operator's to fix


@pytest.mark.parametrize(
    "sealed",
    [
        lambda key, who: seal(key, who + 1, "anthropic", service_key=SERVICE_KEY),
        lambda key, who: seal(key, who, "anthropic", service_key=SERVICE_KEY)[:-1] + b"\0",
    ],
    ids=["another-person", "tampered"],
)
async def test_stops_on_a_key_that_will_not_open(
    engine: AsyncEngine, sealed: Callable[[str, int], bytes]
) -> None:
    person = await add_person(engine, sealed=sealed)
    await add_posting(engine)
    fake = Fake(GOOD)
    result = await run(engine, person, fake)

    assert result == BatchResult(person, rated=0, unreadable=0, end="stopped", reason="unopenable")
    assert fake.keys == []
    assert await failure_of(engine, person) == (None, False)


@pytest.mark.parametrize(
    ("error_body", "reason"),
    [
        (
            {"type": "invalid_request_error", "details": {"error_code": "spend_limit_reached"}},
            "refused-400 (invalid_request_error, spend_limit_reached)",
        ),
        ({"type": "invalid_request_error"}, "refused-400 (invalid_request_error)"),
        ({"type": "not a code: it says something"}, "refused-400"),
        (
            {"type": "invalid_request_error", "details": {"error_code": "Spend Limit!"}},
            "refused-400 (invalid_request_error)",
        ),
    ],
    ids=["type-and-code", "type", "free-text-type", "free-text-code"],
)
async def test_names_an_unlisted_refusal_by_its_codes_never_its_message(
    engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
    error_body: dict[str, Any],
    reason: str,
) -> None:
    caplog.set_level(logging.INFO)
    person = await add_person(engine)
    await add_posting(engine)
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {**error_body, "message": "a sentence that names things"}}
    refusal = anthropic.BadRequestError(
        "a sentence that names things",
        response=httpx2.Response(400, request=request, json=body),
        body=body,
    )
    result = await run(engine, person, Fake(refusal))

    assert result == BatchResult(person, 0, 0, "stopped", reason)
    assert f"person {person}: 0 rated, 0 unreadable, stopped: {reason}" in caplog.messages
    assert "names things" not in caplog.text
    assert await failure_of(engine, person) == (None, False)


# Each outcome, through the real model and a canned server


def real(url: str, timeout: float = 5.0) -> ModelFactory:
    return lambda key: anthropic_model(key, base_url=url, timeout=timeout)


async def test_sends_the_persons_key_the_model_the_cap_and_the_schema_to_anthropic(
    engine: AsyncEngine,
) -> None:
    key = new_key()
    person = await add_person(engine, key=key)
    await add_posting(engine)
    with canned_anthropic(rating(3, "A partial match.")) as server:
        result = await run(engine, person, real(server.url))

    assert result.rated == 1
    [request] = server.received
    assert request.headers["authorization"] == f"Bearer {key}"
    assert request.body["model"] == CHECK_MODEL
    assert request.body["max_tokens"] == 4096
    assert request.body["output_config"]["effort"] == "low"
    assert request.body["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in request.body and "tool_choice" not in request.body


async def test_sends_every_posting_in_a_batch_the_same_system_block_holding_the_profile(
    engine: AsyncEngine,
) -> None:
    person = await add_person(engine, WHOLE_PROFILE)
    for age in range(3):
        await add_posting(engine, seen=START - timedelta(days=age))
    with canned_anthropic(rating(3, "A partial match.")) as server:
        result = await run(engine, person, real(server.url))

    assert result.rated == 3
    blocks = [json.dumps(request.body["system"]) for request in server.received]
    assert len(blocks) == 3 and len(set(blocks)) == 1
    [block] = server.received[0].body["system"]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert f"- {RULE}" in block["text"]
    assert "- Gambling" in block["text"]
    for request in server.received:  # the user message is the posting alone
        [turn] = request.body["messages"]
        assert turn["content"].startswith("<posting>\nTitle: Staff Engineer\n")
        assert turn["content"].endswith("</posting>")


@pytest.mark.parametrize(
    ("reply", "end", "reason", "failure"),
    [
        (message('{"score": 9, "reason": "Off the scale."}'), "finished", None, None),
        (error(401, "authentication_error"), "stopped", "rejected", "rejected"),
        (error(403, "permission_error"), "stopped", "not-permitted", "not-permitted"),
        (error(404, "not_found_error"), "stopped", "model-not-found", None),
        (
            error(400, "invalid_request_error"),
            "stopped",
            "refused-400 (invalid_request_error)",
            None,
        ),
        (error(413, "request_too_large"), "stopped", "refused-413 (request_too_large)", None),
        (error(402, "billing_error"), "stopped", "no-credit", "no-credit"),
        (error(429, "rate_limit_error"), "stopped", "rate-limited", None),
        (error(500, "api_error"), "stopped", "server-error", None),
        (error(529, "overloaded_error"), "stopped", "server-error", None),
    ],
    ids=["unreadable", "401", "403", "404", "400", "413", "402", "429", "500", "529"],
)
async def test_handles_each_answer_from_the_real_client(
    engine: AsyncEngine, reply: Reply, end: str, reason: str | None, failure: str | None
) -> None:
    person = await add_person(engine)
    posting = await add_posting(engine)
    with canned_anthropic(reply) as server:
        result = await run(engine, person, real(server.url))

    assert (result.end, result.reason) == (end, reason)
    assert len(server.received) == 1  # never retried
    expected = [(posting, "unreadable", None)] if end == "finished" else []
    assert await scores_of(engine, person) == expected
    assert (await failure_of(engine, person))[0] == failure


async def test_stops_when_anthropic_cannot_be_reached(
    engine: AsyncEngine, closed_port: int
) -> None:
    person = await add_person(engine)
    await add_posting(engine)
    result = await run(engine, person, real(f"http://127.0.0.1:{closed_port}"))
    assert (result.end, result.reason) == ("stopped", "connection-error")


async def test_stops_when_anthropic_does_not_answer_in_time(
    engine: AsyncEngine, silent_port: int
) -> None:
    person = await add_person(engine)
    await add_posting(engine)
    result = await run(engine, person, real(f"http://127.0.0.1:{silent_port}", timeout=0.5))
    assert (result.end, result.reason) == ("stopped", "timed-out")


# The log, and the key's absence from it


@pytest.fixture
def every_logger_at_debug(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    caplog.set_level(logging.DEBUG)
    for name in list(logging.root.manager.loggerDict):
        caplog.set_level(logging.DEBUG, logger=name)
    yield caplog


async def test_writes_one_line_per_person_naming_the_end(
    engine: AsyncEngine, every_logger_at_debug: pytest.LogCaptureFixture
) -> None:
    person = await add_person(engine)
    for _ in range(3):
        await add_posting(engine)
    await run(engine, person, Fake(GOOD, UNREADABLE, status_error(429)))
    ours = [
        record.getMessage()
        for record in every_logger_at_debug.records
        if record.name.startswith("job_board.scoring")
    ]
    assert ours == [f"person {person}: 1 rated, 1 unreadable, stopped: rate-limited"]


async def test_never_logs_or_raises_the_key(
    engine: AsyncEngine,
    every_logger_at_debug: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    closed_port: int,
) -> None:
    key = new_key()
    people = [await add_person(engine, key=key) for _ in range(3)]
    for _ in range(2):
        await add_posting(engine)
    sessionmaker = make_sessionmaker(engine)
    replies = [
        rating(4, "A close match."),
        message(f'{{"score": 9, "reason": "{key}"}}'),  # a reply quoting the key is dropped
        error(401, "authentication_error"),
    ]
    results: list[BatchResult] = []
    with canned_anthropic(*replies) as server:
        results.append(
            await score_person(
                engine,
                sessionmaker,
                people[0],
                service_key=SERVICE_KEY,
                model_factory=real(server.url),
            )
        )
        results.append(
            await score_person(
                engine,
                sessionmaker,
                people[1],
                service_key=SERVICE_KEY,
                model_factory=real(server.url),
            )
        )
    results.append(
        await score_person(
            engine,
            sessionmaker,
            people[2],
            service_key=SERVICE_KEY,
            model_factory=real(f"http://127.0.0.1:{closed_port}"),
        )
    )

    def boom(given: str) -> RatingModel:
        raise RuntimeError(f"a failure quoting {given}")

    results.extend(
        await score_everyone(engine, sessionmaker, service_key=SERVICE_KEY, model_factory=boom)
    )

    assert any(result.end == "stopped" for result in results)  # the failing paths ran
    shown = [
        every_logger_at_debug.text,
        *(repr(record.args) for record in every_logger_at_debug.records),
        *(record.exc_text or "" for record in every_logger_at_debug.records),
        *(repr(result) for result in results),
        *capsys.readouterr(),
    ]
    assert not [text_ for text_ in shown if key in text_]
    assert not [text_ for text_ in shown if key[-12:] in text_]


async def test_stops_a_batch_that_fails_in_an_unforeseen_way_naming_only_the_kind(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    person = await add_person(engine)
    await add_posting(engine)

    def boom(given: str) -> RatingModel:
        raise RuntimeError(f"a failure quoting {given}")

    [result] = await score_everyone(
        engine, make_sessionmaker(engine), service_key=SERVICE_KEY, model_factory=boom
    )
    assert result == BatchResult(
        person, rated=0, unreadable=0, end="stopped", reason="unexpected: RuntimeError"
    )
    assert f"person {person}: 0 rated, 0 unreadable, stopped: unexpected: RuntimeError" in (
        caplog.messages
    )
