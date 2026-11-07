"""What the profile's route tests share: a client, a person to sign in as, the database."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from session_tokens import claims, signed
from settings_for_tests import make_settings
from sqlalchemy import create_engine, text

from job_board.app import create_app

REFUSED_BODY = b'{"detail":"sign-in required"}'

# A profile nobody has saved: every section unanswered but the target titles,
# which are an empty list.
NEW_PROFILE: dict[str, Any] = {
    "target_titles": [],
    "title_range": None,
    "places": None,
    "pay": None,
    "skills": None,
    "gaps": None,
    "deal_breakers": None,
    "companies": None,
    "pace": None,
    "own_rules": None,
}


@asynccontextmanager
async def client_for(
    database_url: str, *, raise_app_exceptions: bool = True
) -> AsyncIterator[httpx.AsyncClient]:
    # By default an error the app does not handle is raised in the test; turned
    # off, the client gets the 500 a real client would.
    app = create_app(make_settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
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
