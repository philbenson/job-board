import asyncio
import base64
import logging
import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import jwt
import pytest
from fastapi import FastAPI, Request
from session_tokens import claims, signed
from settings_for_tests import MODEL_KEY_ENCRYPTION_KEY, make_settings
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.app import create_app
from job_board.database import get_session
from job_board.logging_setup import LOGGER_NAME
from job_board.model_key.check import CheckOutcome, get_key_checker
from job_board.model_key.check_limits import CHECKS_PER_HOUR, CheckLimits
from job_board.model_key.sealing import open_sealed, seal

SERVICE_KEY = base64.urlsafe_b64decode(MODEL_KEY_ENCRYPTION_KEY)

REJECTED = "Anthropic did not accept that key."
NOT_PERMITTED = "That key cannot use the model this app runs."
UNAVAILABLE = (
    "Anthropic did not confirm the key, so nothing was saved. Try again later; "
    "if it keeps happening, check the key's limits in the Claude Console."
)
MALFORMED = "That does not look like an Anthropic API key."
CHECK_RUNNING = "A check of your key is already running. Wait for it to finish."
TOO_MANY_CHECKS = "You have checked too many keys in the last hour. Try again later."


def fake_key() -> str:
    return f"sk-ant-api03-{secrets.token_urlsafe(48)}"


@dataclass
class FakeChecker:
    """Stands in for Anthropic: answers as told and keeps the keys it was asked about."""

    outcome: CheckOutcome = "accepted"
    asked: list[str] = field(default_factory=list)
    # Called while the check waits, to look at the request's database state.
    while_checking: Callable[[], None] | None = None
    # When set, each check waits for it, so a test can act while one runs.
    hold: asyncio.Event | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self, key: str) -> CheckOutcome:
        self.asked.append(key)
        if self.while_checking is not None:
            self.while_checking()
        self.started.set()
        if self.hold is not None:
            await self.hold.wait()
        return self.outcome


@dataclass
class Service:
    client: httpx.AsyncClient
    app: FastAPI
    checker: FakeChecker
    sessions: list[AsyncSession]


@asynccontextmanager
async def service_for(database_url: str) -> AsyncIterator[Service]:
    app = create_app(make_settings(database_url=database_url))
    checker = FakeChecker()
    sessions: list[AsyncSession] = []

    async def recorded_session(request: Request) -> AsyncIterator[AsyncSession]:
        # The session get_session gives, opened here rather than by iterating
        # get_session, which would leave its session open when a route refuses.
        async with request.app.state.sessionmaker() as session:
            sessions.append(session)
            yield session

    app.dependency_overrides[get_key_checker] = lambda: checker
    app.dependency_overrides[get_session] = recorded_session
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Service(client, app, checker, sessions)


@pytest.fixture
async def service(migrated_database_url: str) -> AsyncIterator[Service]:
    async with service_for(migrated_database_url) as running:
        yield running


def new_person() -> dict[str, str]:
    """The headers of a person signing in for the first time."""
    return {"Authorization": f"Bearer {signed(claims(sub=f'user_{secrets.token_hex(12)}'))}"}


def save(key: str, provider: str = "anthropic") -> dict[str, Any]:
    return {"provider": provider, "key": key}


def stored_rows(database_url: str, headers: dict[str, str]) -> list[Any]:
    """The model key rows of the person whose session token is in these headers."""
    token = headers["Authorization"].removeprefix("Bearer ")
    user = jwt.decode(token, options={"verify_signature": False})["sub"]
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = list(
            connection.execute(
                text(
                    "SELECT k.person_id, k.provider, k.sealed_key, k.last_four, k.checked_at, "
                    "k.created_at, k.updated_at "
                    "FROM model_keys k JOIN people p ON p.id = k.person_id "
                    "WHERE p.clerk_user_id = :user"
                ),
                {"user": user},
            )
        )
    engine.dispose()
    return rows


async def test_saves_a_checked_key_sealed_to_its_owner_and_shows_only_its_last_four(
    service: Service, migrated_database_url: str
) -> None:
    person = new_person()
    key = fake_key()

    saved = await service.client.put("/model-key", headers=person, json=save(f"  {key}\n"))
    read = await service.client.get("/model-key", headers=person)

    assert saved.status_code == 200
    assert saved.json() == read.json()
    assert set(saved.json()) == {
        "provider",
        "last_four",
        "checked_at",
        "usable",
        "failure",
        "failed_at",
    }
    assert (saved.json()["failure"], saved.json()["failed_at"]) == (None, None)
    assert saved.json()["provider"] == "anthropic"
    assert saved.json()["usable"] is True
    assert saved.json()["last_four"] == key[-4:]
    assert datetime.fromisoformat(saved.json()["checked_at"]).tzinfo is not None
    assert service.checker.asked == [key]  # checked without its surrounding whitespace

    (row,) = stored_rows(migrated_database_url, person)
    assert key.encode() not in row.sealed_key
    assert open_sealed(row.sealed_key, row.person_id, "anthropic", service_key=SERVICE_KEY) == key


async def test_reads_a_key_sealed_under_another_service_key_as_unusable(
    service: Service, migrated_database_url: str
) -> None:
    person = new_person()
    key = fake_key()
    await service.client.put("/model-key", headers=person, json=save(key))
    (row,) = stored_rows(migrated_database_url, person)
    resealed = seal(key, row.person_id, "anthropic", service_key=os.urandom(32))
    engine = create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE model_keys SET sealed_key = :sealed WHERE person_id = :person"),
            {"sealed": resealed, "person": row.person_id},
        )
    engine.dispose()

    read = await service.client.get("/model-key", headers=person)

    assert read.status_code == 200
    assert read.json()["usable"] is False
    assert read.json()["last_four"] == key[-4:]


def fail_the_key(database_url: str, person_id: int, failure: str) -> None:
    """Record a failure on the key, as scoring does when Anthropic refuses it."""
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE model_keys SET failure = :failure, failed_at = now() "
                "WHERE person_id = :person"
            ),
            {"failure": failure, "person": person_id},
        )
    engine.dispose()


@pytest.mark.parametrize("failure", ["rejected", "not-permitted", "no-credit"])
async def test_reads_the_failure_scoring_recorded_on_the_key(
    service: Service, migrated_database_url: str, failure: str
) -> None:
    person = new_person()
    await service.client.put("/model-key", headers=person, json=save(fake_key()))
    (row,) = stored_rows(migrated_database_url, person)
    fail_the_key(migrated_database_url, row.person_id, failure)

    read = await service.client.get("/model-key", headers=person)

    assert read.status_code == 200
    assert read.json()["failure"] == failure
    assert datetime.fromisoformat(read.json()["failed_at"]).tzinfo is not None


async def test_saving_a_key_clears_its_failure(
    service: Service, migrated_database_url: str
) -> None:
    person = new_person()
    await service.client.put("/model-key", headers=person, json=save(fake_key()))
    (row,) = stored_rows(migrated_database_url, person)
    fail_the_key(migrated_database_url, row.person_id, "rejected")

    replaced = await service.client.put("/model-key", headers=person, json=save(fake_key()))
    read = await service.client.get("/model-key", headers=person)

    assert (replaced.json()["failure"], replaced.json()["failed_at"]) == (None, None)
    assert (read.json()["failure"], read.json()["failed_at"]) == (None, None)


async def test_answers_404_when_no_key_is_saved(service: Service) -> None:
    response = await service.client.get("/model-key", headers=new_person())
    assert response.status_code == 404
    assert response.json() == {"detail": "no model key saved"}


async def test_replaces_a_saved_key(service: Service, migrated_database_url: str) -> None:
    person = new_person()
    first, second = fake_key(), fake_key()
    await service.client.put("/model-key", headers=person, json=save(first))
    (before,) = stored_rows(migrated_database_url, person)
    await asyncio.sleep(0.01)  # so the replacement's stamps can differ

    replaced = await service.client.put("/model-key", headers=person, json=save(second))

    assert replaced.status_code == 200
    assert replaced.json()["last_four"] == second[-4:]
    (after,) = stored_rows(migrated_database_url, person)
    assert (
        open_sealed(after.sealed_key, after.person_id, "anthropic", service_key=SERVICE_KEY)
        == second
    )
    assert after.created_at == before.created_at
    assert after.updated_at > before.updated_at
    assert after.checked_at > before.checked_at


async def test_removes_a_saved_key_and_answers_alike_when_there_is_none(
    service: Service, migrated_database_url: str
) -> None:
    person = new_person()
    await service.client.put("/model-key", headers=person, json=save(fake_key()))

    removed = await service.client.delete("/model-key", headers=person)
    again = await service.client.delete("/model-key", headers=person)

    assert (removed.status_code, removed.content) == (204, b"")
    assert (again.status_code, again.content) == (204, b"")
    assert stored_rows(migrated_database_url, person) == []
    assert (await service.client.get("/model-key", headers=person)).status_code == 404


async def test_touches_only_the_signed_in_persons_own_key(
    service: Service, migrated_database_url: str
) -> None:
    owner, other = new_person(), new_person()
    key = fake_key()
    await service.client.put("/model-key", headers=owner, json=save(key))

    assert (await service.client.get("/model-key", headers=other)).status_code == 404
    assert (await service.client.delete("/model-key", headers=other)).status_code == 204
    assert (await service.client.get("/model-key", headers=owner)).json()["last_four"] == key[-4:]
    assert len(stored_rows(migrated_database_url, owner)) == 1


REFUSALS: dict[str, tuple[CheckOutcome, int, str]] = {
    "rejected": ("rejected", 422, REJECTED),
    "not permitted": ("not-permitted", 422, NOT_PERMITTED),
    "unavailable": ("unavailable", 503, UNAVAILABLE),
}


@pytest.mark.parametrize(("outcome", "status", "detail"), REFUSALS.values(), ids=REFUSALS.keys())
async def test_a_failed_check_saves_nothing_and_keeps_an_earlier_key(
    outcome: CheckOutcome,
    status: int,
    detail: str,
    service: Service,
    migrated_database_url: str,
) -> None:
    person = new_person()
    earlier = fake_key()
    await service.client.put("/model-key", headers=person, json=save(earlier))
    (before,) = stored_rows(migrated_database_url, person)
    service.checker.outcome = outcome

    response = await service.client.put("/model-key", headers=person, json=save(fake_key()))

    assert response.status_code == status
    assert response.json() == {"detail": detail, "reason": outcome}
    assert stored_rows(migrated_database_url, person) == [before]


MALFORMED_KEYS = {
    "empty": "",
    "only whitespace": " \t\n",
    "too long": "sk-ant-" + "a" * 506,
    "one short of the shortest": "sk-ant-api03-abcdef",
    "a space inside": "sk-ant-api03 abcdefghijkl",
    "a tab inside": "sk-ant-api03\tabcdefghijkl",
    "a control character": "sk-ant-api03\x00abcdefghijkl",
    "a character outside ASCII": "sk-ant-api03-ébcdefghijkl",
}


@pytest.mark.parametrize("key", MALFORMED_KEYS.values(), ids=MALFORMED_KEYS.keys())
async def test_refuses_a_malformed_key_without_asking_anthropic(key: str, service: Service) -> None:
    person = new_person()
    response = await service.client.put("/model-key", headers=person, json=save(key))

    assert response.status_code == 422
    assert response.json() == {"detail": MALFORMED, "reason": "malformed"}
    assert service.checker.asked == []
    assert (await service.client.get("/model-key", headers=person)).status_code == 404


async def test_a_route_that_refuses_gives_its_connection_back_before_the_answer(
    service: Service,
) -> None:
    # The read of a key no one saved is answered 404 from inside its transaction.
    response = await service.client.get("/model-key", headers=new_person())

    assert response.status_code == 404
    assert service.app.state.engine.pool.checkedout() == 0


async def test_takes_a_key_of_exactly_the_shortest_length(service: Service) -> None:
    key = "sk-ant-api03-abcdefg"
    assert len(key) == 20
    response = await service.client.put("/model-key", headers=new_person(), json=save(key))
    assert response.status_code == 200


async def test_takes_a_key_of_exactly_the_longest_length(service: Service) -> None:
    response = await service.client.put(
        "/model-key", headers=new_person(), json=save("sk-ant-" + "a" * 505)
    )
    assert response.status_code == 200


async def test_refuses_a_second_check_while_the_first_runs(service: Service) -> None:
    person = new_person()
    service.checker.hold = asyncio.Event()
    first = asyncio.create_task(
        service.client.put("/model-key", headers=person, json=save(fake_key()))
    )
    await service.checker.started.wait()

    second_sent = asyncio.create_task(
        service.client.put("/model-key", headers=person, json=save(fake_key()))
    )
    answered, _ = await asyncio.wait({second_sent}, timeout=2)
    service.checker.hold.set()  # the first check ends whatever the second did
    second = await second_sent

    assert answered == {second_sent}  # answered while the first check still ran
    assert second.status_code == 429
    assert second.json() == {"detail": CHECK_RUNNING, "reason": "check-running"}
    assert (await first).status_code == 200
    assert len(service.checker.asked) == 1


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_refuses_an_eleventh_check_within_the_hour_and_not_one_an_hour_later(
    service: Service,
) -> None:
    clock = Clock()
    service.app.state.check_limits = CheckLimits(clock=clock)
    person = new_person()
    answers = []
    for _ in range(CHECKS_PER_HOUR + 1):
        answers.append(
            await service.client.put("/model-key", headers=person, json=save(fake_key()))
        )
    clock.now += 3600
    later = await service.client.put("/model-key", headers=person, json=save(fake_key()))

    assert [answer.status_code for answer in answers] == [200] * CHECKS_PER_HOUR + [429]
    assert answers[-1].json() == {"detail": TOO_MANY_CHECKS, "reason": "too-many-checks"}
    assert later.status_code == 200
    assert len(service.checker.asked) == CHECKS_PER_HOUR + 1


async def test_a_malformed_key_does_not_count_as_a_check(service: Service) -> None:
    clock = Clock()
    service.app.state.check_limits = CheckLimits(clock=clock)
    person = new_person()
    for _ in range(CHECKS_PER_HOUR):
        await service.client.put("/model-key", headers=person, json=save("not a key"))

    response = await service.client.put("/model-key", headers=person, json=save(fake_key()))

    assert response.status_code == 200


async def test_waits_on_anthropic_with_no_database_transaction_or_connection_held(
    service: Service,
) -> None:
    seen: list[tuple[bool, int]] = []

    def look() -> None:
        (session,) = service.sessions
        seen.append((session.in_transaction(), service.app.state.engine.pool.checkedout()))

    service.checker.while_checking = look
    response = await service.client.put("/model-key", headers=new_person(), json=save(fake_key()))

    assert response.status_code == 200
    assert seen == [(False, 0)]


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_every_route_needs_a_signed_in_person(method: str, service: Service) -> None:
    response = await service.client.request(method, "/model-key", json=save(fake_key()))
    assert response.status_code == 401
    assert service.checker.asked == []


def broken_bodies(key: str) -> list[Any]:
    """Bodies FastAPI itself refuses before the route runs, each carrying the key."""
    return [
        {"key": key},
        {"provider": "openai", "key": key},
        [key],
        key,
    ]


def unreadable_bodies(key: str) -> list[tuple[bytes, str]]:
    """Bodies that are not JSON objects at all, each carrying the key, with their content type."""
    whole = f'{{"provider":"anthropic","key":"{key}"}}'.encode()
    return [(whole[:-1], "application/json"), (whole, "text/plain")]


async def test_the_key_never_comes_back_or_reaches_the_logs(
    service: Service, caplog: pytest.LogCaptureFixture
) -> None:
    key = fake_key()
    answers: list[httpx.Response] = []
    # The service sets its own loggers to info, which would drop their debug lines unread.
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        for outcome in ("accepted", "rejected", "not-permitted", "unavailable"):
            service.checker.outcome = outcome
            answers.append(
                await service.client.put("/model-key", headers=new_person(), json=save(key))
            )
        answers.append(
            await service.client.put("/model-key", headers=new_person(), json=save(f"{key} {key}"))
        )
        for body in broken_bodies(key):
            answers.append(await service.client.put("/model-key", headers=new_person(), json=body))
        for content, content_type in unreadable_bodies(key):
            answers.append(
                await service.client.put(
                    "/model-key",
                    headers={**new_person(), "Content-Type": content_type},
                    content=content,
                )
            )
        answers.append(await service.client.get("/model-key", headers=new_person()))

    assert [answer.status_code for answer in answers] == [200, 422, 422, 503, 422] + [422] * 6 + [
        404
    ]
    for leak in (key, key[:12]):
        for answer in answers:
            assert leak not in answer.text
        assert leak not in caplog.text


async def test_a_structurally_broken_body_gets_a_list_of_problems_without_its_input(
    service: Service,
) -> None:
    response = await service.client.put("/model-key", headers=new_person(), json={"key": "x"})
    assert response.status_code == 422
    (problem,) = response.json()["detail"]
    assert problem["loc"] == ["body", "provider"]
    assert "input" not in problem


def test_the_description_declares_each_answer() -> None:
    description = create_app(make_settings()).openapi()
    route = description["paths"]["/model-key"]
    schemas = description["components"]["schemas"]

    assert set(route) == {"get", "put", "delete"}
    assert set(route["get"]["responses"]) == {"200", "401", "404"}
    assert set(route["put"]["responses"]) == {"200", "401", "422", "429", "503"}
    assert set(route["delete"]["responses"]) == {"204", "401"}
    for status in ("422", "429", "503"):
        refusal = route["put"]["responses"][status]["content"]["application/json"]["schema"]
        assert refusal == {"$ref": "#/components/schemas/ModelKeyRefused"}
    assert schemas["ModelKeyRefused"]["properties"]["reason"]["enum"] == [
        "malformed",
        "rejected",
        "not-permitted",
        "unavailable",
        "check-running",
        "too-many-checks",
    ]
    assert schemas["SavedModelKey"]["required"] == [
        "provider",
        "last_four",
        "checked_at",
        "usable",
        "failure",
        "failed_at",
    ]
    failure = schemas["SavedModelKey"]["properties"]["failure"]
    assert failure["anyOf"] == [
        {"type": "string", "enum": ["rejected", "not-permitted", "no-credit"]},
        {"type": "null"},
    ]
    assert schemas["ModelKeyToSave"]["required"] == ["provider", "key"]
