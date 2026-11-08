"""A running service for the resume routes' tests, and a signed-in person to call it as."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, Request
from pdf_files import pdf, resume_lines
from session_tokens import claims, signed
from settings_for_tests import make_settings
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.app import create_app
from job_board.database import get_session

ACCESS_KEY_ID = "resume-test-access-key-id"
SECRET_ACCESS_KEY = "resume-test-secret-access-key"
A_PDF = pdf(resume_lines())
A_PDF_TEXT = "\n".join(resume_lines())


def run(database_url: str, sql: str, **values: Any) -> list[Any]:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            result = connection.execute(text(sql), values)
            return list(result) if result.returns_rows else []
    finally:
        engine.dispose()


class Someone:
    """A person with a session token, whose rows the test removes after."""

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

    def key(self) -> str:
        return f"resumes/{self.person_id()}.pdf"

    def rows(self) -> list[Any]:
        return run(
            self.database_url,
            "SELECT r.object_key, r.size_bytes, r.uploaded_at "
            "FROM resumes r JOIN people p ON p.id = r.person_id WHERE p.clerk_user_id = :user",
            user=self.clerk_user_id,
        )

    def text_row(self) -> Any:
        (row,) = run(
            self.database_url,
            "SELECT r.text_state, r.text, r.text_checked_at "
            "FROM resumes r JOIN people p ON p.id = r.person_id WHERE p.clerk_user_id = :user",
            user=self.clerk_user_id,
        )
        return row

    def check_text(self) -> None:
        """Mark the text checked, as a save would."""
        run(
            self.database_url,
            "UPDATE resumes SET text = coalesce(text, 'typed in'), text_checked_at = now() "
            "WHERE person_id = :person",
            person=self.person_id(),
        )

    def remove(self) -> None:
        # The resume row goes with the person.
        run(
            self.database_url,
            "DELETE FROM people WHERE clerk_user_id = :user",
            user=self.clerk_user_id,
        )


@dataclass
class Service:
    client: httpx.AsyncClient
    app: FastAPI
    sessions: list[AsyncSession] = field(default_factory=list)


def storage_settings(endpoint: str, bucket: str) -> dict[str, str]:
    return {
        "s3_endpoint_url": endpoint,
        "s3_region": "auto",  # R2's region, as the service is run against it
        "s3_bucket": bucket,
        "s3_access_key_id": ACCESS_KEY_ID,
        "s3_secret_access_key": SECRET_ACCESS_KEY,
    }


@asynccontextmanager
async def service_for(database_url: str, **storage: str) -> AsyncIterator[Service]:
    app = create_app(make_settings(database_url=database_url, **storage))
    sessions: list[AsyncSession] = []

    async def recorded_session(request: Request) -> AsyncIterator[AsyncSession]:
        # The session get_session gives, opened here rather than by iterating
        # get_session, which would leave its session open when a route refuses.
        async with request.app.state.sessionmaker() as session:
            sessions.append(session)
            yield session

    app.dependency_overrides[get_session] = recorded_session
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Service(client, app, sessions)


def pdf_headers(person: Someone, **more: str) -> dict[str, str]:
    return {**person.headers, "Content-Type": "application/pdf", **more}
