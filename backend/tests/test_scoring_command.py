"""The scoring command: what it refuses, what it needs, and what it exits with."""

import asyncio
import base64
import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import anthropic
import httpx2
import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import RunnableLambda
from settings_for_tests import MODEL_KEY_ENCRYPTION_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from job_board.environment_refusal import TRACING_VARIABLES
from job_board.model_key.sealing import seal
from job_board.scoring.command import EXIT_REFUSED, EXIT_STOPPED, main
from job_board.scoring.model import ModelFactory, Rating, RatingModel
from job_board.settings import ScoringSettings

BACKEND = Path(__file__).resolve().parents[1]
SERVICE_KEY = base64.urlsafe_b64decode(MODEL_KEY_ENCRYPTION_KEY)


def answering(reply: object) -> RatingModel:
    async def answer(messages: LanguageModelInput) -> object:
        if isinstance(reply, BaseException):
            raise reply
        return reply

    return RunnableLambda(answer)


def never_built(key: str) -> RatingModel:
    raise AssertionError("no model should be built")


@pytest.fixture
def scoring_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, module_database_url: str
) -> pytest.MonkeyPatch:
    """The command's two settings and nothing else, in a folder with no .env."""
    monkeypatch.chdir(tmp_path)
    for name in ("CLERK_ISSUER", "CLERK_JWT_KEY", "CLERK_AUTHORIZED_PARTIES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", module_database_url)
    monkeypatch.setenv("MODEL_KEY_ENCRYPTION_KEY", MODEL_KEY_ENCRYPTION_KEY)
    return monkeypatch


@pytest.fixture
async def one_person_one_posting(module_database_url: str) -> AsyncIterator[int]:
    engine = create_async_engine(module_database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE people, postings RESTART IDENTITY CASCADE"))
        person: int = (
            await connection.execute(
                text("INSERT INTO people (clerk_user_id) VALUES ('user_command') RETURNING id")
            )
        ).scalar_one()
        await connection.execute(
            text(
                "INSERT INTO profiles (person_id, document) VALUES "
                """(:person, '{"target_titles": ["Staff Engineer"]}')"""
            ),
            {"person": person},
        )
        await connection.execute(
            text(
                "INSERT INTO model_keys (person_id, provider, sealed_key, last_four, checked_at) "
                "VALUES (:person, 'anthropic', :sealed, 'abcd', now())"
            ),
            {
                "person": person,
                "sealed": seal("sk-ant-api03-abcd", person, "anthropic", service_key=SERVICE_KEY),
            },
        )
        await connection.execute(
            text(
                "INSERT INTO postings (source, board, external_id, title, url, "
                "source_updated_at, first_seen_at, last_seen_at) VALUES ('greenhouse', "
                "'example', 1, 'Engineer', 'https://boards.example.com/1', now(), now(), now())"
            )
        )
    await engine.dispose()
    yield person


# Tracing


@pytest.mark.parametrize("variable", TRACING_VARIABLES)
@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES", " true "])
def test_refuses_to_start_when_tracing_is_on(
    scoring_environment: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    variable: str,
    value: str,
) -> None:
    scoring_environment.setenv(variable, value)
    assert main(model_factory=never_built) == EXIT_REFUSED
    assert any(variable in line for line in caplog.messages)


@pytest.mark.parametrize("value", ["false", "False", "0", "no", ""])
async def test_starts_when_tracing_is_off(
    scoring_environment: pytest.MonkeyPatch, value: str
) -> None:
    for variable in TRACING_VARIABLES:
        scoring_environment.setenv(variable, value)
    assert await _main_off_the_loop(never_built) == 0


def test_the_tests_run_with_tracing_unset() -> None:
    assert [name for name in TRACING_VARIABLES if name in os.environ] == []


@pytest.mark.parametrize(
    "value",
    ["X-Api-Key: sk-ant-api03-someone-else", "Authorization: Bearer someone-else", ""],
    ids=["api-key", "authorization", "empty"],
)
def test_refuses_to_start_while_custom_anthropic_headers_are_set(
    scoring_environment: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, value: str
) -> None:
    scoring_environment.setenv("ANTHROPIC_CUSTOM_HEADERS", value)
    assert main(model_factory=never_built) == EXIT_REFUSED
    assert any("ANTHROPIC_CUSTOM_HEADERS" in line for line in caplog.messages)
    assert "someone-else" not in caplog.text


def test_the_tests_run_with_custom_anthropic_headers_unset() -> None:
    assert "ANTHROPIC_CUSTOM_HEADERS" not in os.environ


@pytest.mark.parametrize("value", ["debug", "info"])
def test_refuses_to_start_while_the_anthropic_librarys_own_logging_is_on(
    scoring_environment: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, value: str
) -> None:
    scoring_environment.setenv("ANTHROPIC_LOG", value)
    assert main(model_factory=never_built) == EXIT_REFUSED
    refusals = [line for line in caplog.messages if "ANTHROPIC_LOG" in line]
    assert len(refusals) == 1
    assert f"={value}" not in refusals[0] and f"'{value}'" not in refusals[0]


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
async def test_starts_while_the_anthropic_librarys_own_logging_is_off(
    scoring_environment: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        scoring_environment.delenv("ANTHROPIC_LOG", raising=False)
    else:
        scoring_environment.setenv("ANTHROPIC_LOG", value)
    assert await _main_off_the_loop(never_built) == 0


def test_the_tests_run_with_the_anthropic_librarys_own_logging_unset() -> None:
    assert "ANTHROPIC_LOG" not in os.environ


def test_the_command_refuses_tracing_as_a_process(tmp_path: Path) -> None:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in ("DATABASE_URL", "MODEL_KEY_ENCRYPTION_KEY")
    }
    environment["LANGSMITH_TRACING"] = "true"
    finished = subprocess.run(
        [sys.executable, "-m", "job_board.scoring"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert finished.returncode == EXIT_REFUSED
    assert "LANGSMITH_TRACING" in finished.stderr


# Settings


def test_needs_only_the_database_url_and_the_encryption_key(
    scoring_environment: pytest.MonkeyPatch,
) -> None:
    settings = ScoringSettings()
    assert settings.model_key_encryption_key.get_secret_value() == SERVICE_KEY


@pytest.mark.parametrize("missing", ["DATABASE_URL", "MODEL_KEY_ENCRYPTION_KEY"])
def test_refuses_to_start_naming_a_missing_setting(
    scoring_environment: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, missing: str
) -> None:
    scoring_environment.delenv(missing)
    assert main(model_factory=never_built) == EXIT_REFUSED
    assert any(missing in line for line in caplog.messages)


def test_refuses_a_bad_encryption_key_without_repeating_it(
    scoring_environment: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    scoring_environment.setenv("MODEL_KEY_ENCRYPTION_KEY", "not-a-key-but-a-secret-anyway")
    assert main(model_factory=never_built) == EXIT_REFUSED
    assert "MODEL_KEY_ENCRYPTION_KEY" in caplog.text
    assert "not-a-key-but-a-secret-anyway" not in caplog.text


# Exit codes


async def _main_off_the_loop(factory: ModelFactory) -> int:
    """``main`` runs its own event loop, so the async tests call it from a thread."""
    return await asyncio.to_thread(main, model_factory=factory)


async def test_exits_zero_when_every_batch_finishes(
    scoring_environment: pytest.MonkeyPatch,
    one_person_one_posting: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    rating = Rating(score=3, reason="A partial match.")
    assert await _main_off_the_loop(lambda key: answering(rating)) == 0
    assert f"person {one_person_one_posting}: 1 rated, 0 unreadable, finished" in caplog.messages


async def add_sealed_elsewhere(module_database_url: str, count: int) -> None:
    """``count`` more people with a title and a key sealed under another service key."""
    engine = create_async_engine(module_database_url)
    async with engine.begin() as connection:
        for n in range(count):
            person: int = (
                await connection.execute(
                    text("INSERT INTO people (clerk_user_id) VALUES (:user) RETURNING id"),
                    {"user": f"user_elsewhere_{n}"},
                )
            ).scalar_one()
            await connection.execute(
                text(
                    "INSERT INTO profiles (person_id, document) VALUES "
                    """(:person, '{"target_titles": ["Staff Engineer"]}')"""
                ),
                {"person": person},
            )
            await connection.execute(
                text(
                    "INSERT INTO model_keys (person_id, provider, sealed_key, last_four, "
                    "checked_at) VALUES (:person, 'anthropic', :sealed, 'abcd', now())"
                ),
                {
                    "person": person,
                    "sealed": seal("sk-ant-api03-abcd", person, "anthropic", service_key=bytes(32)),
                },
            )
    await engine.dispose()


async def test_exits_one_when_no_key_opens_under_this_service_key(
    scoring_environment: pytest.MonkeyPatch, module_database_url: str
) -> None:
    engine = create_async_engine(module_database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE people, postings RESTART IDENTITY CASCADE"))
        await connection.execute(
            text(
                "INSERT INTO postings (source, board, external_id, title, url, "
                "source_updated_at, first_seen_at, last_seen_at) VALUES ('greenhouse', "
                "'example', 1, 'Engineer', 'https://boards.example.com/1', now(), now(), now())"
            )
        )
    await engine.dispose()
    await add_sealed_elsewhere(module_database_url, 2)
    assert await _main_off_the_loop(never_built) == EXIT_STOPPED


async def test_exits_zero_when_some_keys_open_under_this_service_key(
    scoring_environment: pytest.MonkeyPatch, one_person_one_posting: int, module_database_url: str
) -> None:
    await add_sealed_elsewhere(module_database_url, 1)
    rating = Rating(score=3, reason="A partial match.")
    assert await _main_off_the_loop(lambda key: answering(rating)) == 0


async def test_exits_one_and_marks_no_key_when_anthropic_cannot_find_the_model(
    scoring_environment: pytest.MonkeyPatch,
    one_person_one_posting: int,
    module_database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    missing = anthropic.NotFoundError(
        "no such model", response=httpx2.Response(404, request=request), body=None
    )
    assert await _main_off_the_loop(lambda key: answering(missing)) == EXIT_STOPPED
    [line] = [r for r in caplog.records if f"person {one_person_one_posting}:" in r.getMessage()]
    assert line.getMessage().endswith("stopped: model-not-found")
    assert line.levelno == logging.WARNING
    engine = create_async_engine(module_database_url)
    async with engine.connect() as connection:
        failure = (await connection.execute(text("SELECT failure FROM model_keys"))).scalar_one()
    await engine.dispose()
    assert failure is None


async def test_exits_one_when_a_batch_stops_on_a_failure(
    scoring_environment: pytest.MonkeyPatch, one_person_one_posting: int
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    failure = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )
    assert await _main_off_the_loop(lambda key: answering(failure)) == EXIT_STOPPED
