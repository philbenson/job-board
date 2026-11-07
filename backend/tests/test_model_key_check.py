"""The real checker, driven through a fake transport: no request leaves the machine."""

import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine

import anthropic
import httpx2
import pytest

from job_board.model_key import check
from job_board.model_key.check import CHECK_MODEL, CheckOutcome, check_with_anthropic

Handler = Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]

NO_WAIT = {"retry-after-ms": "1"}  # the client honours it, so a retried answer costs no wait


def fake_key() -> str:
    return f"sk-ant-api03-{secrets.token_urlsafe(48)}"


def error(status: int, kind: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": kind, "message": "refused in a test"}}
    return httpx2.Response(status, json=body, headers=NO_WAIT)


MODEL = {
    "type": "model",
    "id": CHECK_MODEL,
    "display_name": "Claude Opus 5.5",
    "created_at": "2026-10-01T00:00:00Z",
}


class Recorder:
    """Answers every request alike and keeps each one it was sent."""

    def __init__(self, answer: Callable[[], httpx2.Response]) -> None:
        self.answer = answer
        self.requests: list[httpx2.Request] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.answer()


async def run_check(key: str, handler: Handler) -> CheckOutcome:
    transport = httpx2.MockTransport(handler)
    return await check_with_anthropic(
        key, http_client=anthropic.DefaultAsyncHttpxClient(transport=transport)
    )


async def test_accepts_a_key_that_can_read_the_model_and_sends_it_only_to_anthropic() -> None:
    key = fake_key()
    recorder = Recorder(lambda: httpx2.Response(200, json=MODEL))

    assert await run_check(key, recorder) == "accepted"

    (request,) = recorder.requests
    assert request.method == "GET"
    assert str(request.url) == "https://api.anthropic.com/v1/models/claude-opus-5-5"
    # The installed client sends a key as a bearer token, not as x-api-key.
    assert request.headers["authorization"] == f"Bearer {key}"
    assert "x-api-key" not in request.headers
    assert request.content == b""


async def test_ignores_an_environment_that_points_the_client_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://collector.example.com")
    recorder = Recorder(lambda: httpx2.Response(200, json=MODEL))

    await run_check(fake_key(), recorder)

    assert recorder.requests[0].url.host == "api.anthropic.com"


ANSWERS: dict[str, tuple[Callable[[], httpx2.Response], CheckOutcome, int]] = {
    "401": (lambda: error(401, "authentication_error"), "rejected", 1),
    "403": (lambda: error(403, "permission_error"), "not-permitted", 1),
    "404": (lambda: error(404, "not_found_error"), "not-permitted", 1),
    "400": (lambda: error(400, "invalid_request_error"), "unavailable", 1),
    "429": (lambda: error(429, "rate_limit_error"), "unavailable", 2),
    "500": (lambda: error(500, "api_error"), "unavailable", 2),
    "529": (lambda: error(529, "overloaded_error"), "unavailable", 2),
}


@pytest.mark.parametrize(("answer", "outcome", "attempts"), ANSWERS.values(), ids=ANSWERS.keys())
async def test_maps_each_answer_to_its_outcome(
    answer: Callable[[], httpx2.Response],
    outcome: CheckOutcome,
    attempts: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = fake_key()
    recorder = Recorder(answer)

    with caplog.at_level(logging.DEBUG):
        assert await run_check(key, recorder) == outcome

    assert len(recorder.requests) == attempts  # one retry, and only where it can help
    assert key not in caplog.text
    assert key[:12] not in caplog.text


FAILURES: dict[str, Exception] = {
    "a connection error": httpx2.ConnectError("connection refused"),
    "a timeout": httpx2.ReadTimeout("timed out"),
}


@pytest.mark.parametrize("failure", FAILURES.values(), ids=FAILURES.keys())
async def test_is_unavailable_when_anthropic_cannot_be_reached(
    failure: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    key = fake_key()
    attempts = 0

    async def fail(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        raise failure

    with caplog.at_level(logging.DEBUG):
        assert await run_check(key, fail) == "unavailable"

    assert attempts == 2
    assert key[:12] not in caplog.text


async def test_gives_up_at_its_ceiling_however_long_anthropic_asks_it_to_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check, "CHECK_CEILING_SECONDS", 0.2)
    # Anthropic may ask for a long wait before a retry, and the client would honour it.
    recorder = Recorder(lambda: httpx2.Response(429, headers={"retry-after": "60"}))

    async with asyncio.timeout(5):
        assert await run_check(fake_key(), recorder) == "unavailable"

    assert len(recorder.requests) == 1
