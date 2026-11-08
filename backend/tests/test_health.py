import asyncio
import logging
import time

import httpx
import pytest
from settings_for_tests import make_settings

from job_board import health
from job_board.app import create_app
from job_board.logging_setup import LOGGER_NAME

OK = {"status": "ok", "database": "ok"}
UNAVAILABLE = {"status": "unavailable", "database": "unreachable"}


def unreachable_url(port: int) -> str:
    return f"postgresql://job_board:s3cret@127.0.0.1:{port}/job_board"


async def get_health(database_url: str) -> httpx.Response:
    app = create_app(make_settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")


async def test_ok_when_the_database_answers(database_url: str) -> None:
    response = await get_health(database_url)
    assert response.status_code == 200
    assert response.json() == OK


async def test_unavailable_quickly_when_the_server_is_down(closed_port: int) -> None:
    started = time.monotonic()
    response = await get_health(unreachable_url(closed_port))
    assert time.monotonic() - started < health.HEALTH_CHECK_TIMEOUT_SECONDS
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


async def test_unavailable_within_the_ceiling_when_the_server_hangs(
    silent_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "HEALTH_CHECK_TIMEOUT_SECONDS", 0.3)
    started = time.monotonic()
    # Without a working ceiling, psycopg would wait minutes; fail in seconds instead.
    response = await asyncio.wait_for(get_health(unreachable_url(silent_port)), 5)
    assert time.monotonic() - started < 1.5
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


async def test_a_failure_leaks_nothing_about_why(
    closed_port: int, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Building the service would set its own loggers to info, dropping their debug lines unread.
    monkeypatch.setattr("job_board.app.configure_logging", lambda: None)
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        response = await get_health(unreachable_url(closed_port))
    for leak in ("127.0.0.1", str(closed_port), "s3cret", "postgresql", "refused", "Error"):
        assert leak not in response.text
    assert [
        record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING
    ] == [
        "resume storage is not set up: the resume routes answer 503",  # logged at start
        "database health check failed: OperationalError",
    ]
    for leak in ("127.0.0.1", str(closed_port), "s3cret", "postgresql"):
        assert leak not in caplog.text
