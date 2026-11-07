import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from session_tokens import ABSENT, USER_ID, claims, forged, signed
from settings_for_tests import ISSUER, ORIGIN, make_settings
from sqlalchemy import create_engine, text

from job_board.app import create_app

REFUSED_BODY = b'{"detail":"sign-in required"}'
ANOTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@asynccontextmanager
async def client_for(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_user_id() -> str:
    return f"user_{secrets.token_hex(12)}"


def rows_for(database_url: str, clerk_user_id: str) -> list[int]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        ids = connection.execute(
            text("SELECT id FROM people WHERE clerk_user_id = :user"), {"user": clerk_user_id}
        ).scalars()
        result = list(ids)
    engine.dispose()
    return result


async def test_answers_the_signed_in_person_and_remembers_them(
    migrated_database_url: str,
) -> None:
    user = new_user_id()
    token = signed(claims(sub=user))
    async with client_for(migrated_database_url) as client:
        first = await client.get("/me", headers=bearer(token))
        again = await client.get("/me", headers=bearer(token))
        someone_else = await client.get("/me", headers=bearer(signed(claims(sub=new_user_id()))))

    assert first.status_code == 200
    assert first.json() == again.json() == {"id": rows_for(migrated_database_url, user)[0]}
    assert someone_else.json() != first.json()
    assert rows_for(migrated_database_url, user) == [first.json()["id"]]


async def test_two_first_requests_at_once_make_one_row(migrated_database_url: str) -> None:
    user = new_user_id()
    token = signed(claims(sub=user))
    async with client_for(migrated_database_url) as client:
        answers = await asyncio.gather(
            client.get("/me", headers=bearer(token)), client.get("/me", headers=bearer(token))
        )

    assert [answer.status_code for answer in answers] == [200, 200]
    assert answers[0].json() == answers[1].json()
    assert len(rows_for(migrated_database_url, user)) == 1


REFUSALS: dict[str, tuple[Callable[[], dict[str, str]], str]] = {
    "no header": (lambda: {}, "missing"),
    "a header without Bearer": (lambda: {"Authorization": signed(claims())}, "malformed"),
    "a token that is not one": (lambda: bearer("not-a-token"), "malformed"),
    "expired": (lambda: bearer(signed(claims(exp=1))), "expired"),
    "not yet valid": (lambda: bearer(signed(claims(nbf=4_000_000_000))), "not-yet-valid"),
    "another issuer": (lambda: bearer(signed(claims(iss="https://other.example.com"))), "issuer"),
    "no authorized party": (lambda: bearer(signed(claims(azp=ABSENT))), "party"),
    "a party not permitted": (
        lambda: bearer(signed(claims(azp="https://evil.example.com"))),
        "party",
    ),
    "a session still pending": (lambda: bearer(signed(claims(sts="pending"))), "pending"),
    "signed by another key": (lambda: bearer(signed(claims(), ANOTHER_KEY)), "signature"),
    "HS256 keyed with the public key": (lambda: bearer(forged("HS256", claims())), "signature"),
    "alg none": (lambda: bearer(forged("none", claims())), "signature"),
    "an empty subject": (lambda: bearer(signed(claims(sub=""))), "claims"),
}


@pytest.mark.parametrize(("headers", "reason"), REFUSALS.values(), ids=REFUSALS.keys())
async def test_refuses_alike_whatever_the_reason_and_logs_only_the_reason(
    headers: Callable[[], dict[str, str]],
    reason: str,
    closed_port: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The database is unreachable: a refusal never waits on it.
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    sent = headers()
    with caplog.at_level(logging.INFO, logger="job_board"):
        async with client_for(unreachable) as client:
            response = await client.get("/me", headers=sent)

    assert response.status_code == 401
    assert response.content == REFUSED_BODY
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert [record.getMessage() for record in caplog.records] == [f"sign-in refused: {reason}"]
    secrets_sent = [value.removeprefix("Bearer ") for value in sent.values()]
    for leak in [*secrets_sent, USER_ID, ISSUER, ORIGIN, "evil.example.com", "other.example.com"]:
        assert leak not in caplog.text
