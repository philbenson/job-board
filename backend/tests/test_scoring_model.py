"""The rating's rules, and the real model factory against a canned local server."""

import secrets
from typing import Any

import pytest
from canned_anthropic import canned_anthropic, message, rating
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from job_board.model_key.check import CHECK_MODEL
from job_board.scoring.model import MAX_REASON_LENGTH, Rating, anthropic_model


def fake_key() -> str:
    return f"sk-ant-api03-{secrets.token_urlsafe(48)}"


@pytest.mark.parametrize("score", [1, 3, 5])
def test_a_rating_takes_a_score_from_one_to_five(score: int) -> None:
    assert Rating.model_validate({"score": score, "reason": "Fits."}).score == score


@pytest.mark.parametrize("score", [0, 6, -1, 4.0, "4", True])
def test_a_rating_refuses_a_score_that_is_not_a_whole_number_from_one_to_five(
    score: object,
) -> None:
    with pytest.raises(ValidationError):
        Rating.model_validate({"score": score, "reason": "Fits."})


@pytest.mark.parametrize(
    "reason",
    ["", "   ", "x" * (MAX_REASON_LENGTH + 1), "Fits.\nAnd more.", "Fits.\rMore", "A\u2028B"],
)
def test_a_rating_refuses_a_reason_that_is_empty_too_long_or_on_more_than_one_line(
    reason: str,
) -> None:
    with pytest.raises(ValidationError):
        Rating.model_validate({"score": 3, "reason": reason})


def test_a_rating_keeps_a_reason_of_the_longest_length_trimmed() -> None:
    reason = "x" * MAX_REASON_LENGTH
    assert Rating.model_validate({"score": 3, "reason": f" {reason}\n"}).reason == reason


async def test_the_real_model_sends_the_key_the_model_id_the_cap_and_the_schema_and_no_tools() -> (
    None
):
    key = fake_key()
    with canned_anthropic(rating(4, "A close match for the titles.")) as server:
        result = await anthropic_model(key, base_url=server.url).ainvoke("Rate this.")

    assert result == Rating(score=4, reason="A close match for the titles.")
    [request] = server.received
    assert request.path == "/v1/messages"
    assert request.headers["authorization"] == f"Bearer {key}"
    assert "x-api-key" not in request.headers
    body: dict[str, Any] = request.body
    assert body["model"] == CHECK_MODEL
    assert body["max_tokens"] == 1024
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert set(body["output_config"]["format"]["schema"]["properties"]) == {"score", "reason"}
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_the_real_model_ignores_environment_variables_that_would_send_the_key_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = fake_key()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ANTHROPIC_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "Authorization: Bearer someone-else")
    with canned_anthropic(rating(2, "A different field.")) as server:
        await anthropic_model(key, base_url=server.url).ainvoke("Rate this.")

    [request] = server.received
    assert request.headers["authorization"] == f"Bearer {key}"


@pytest.mark.parametrize(
    "reply",
    ['{"score": 7, "reason": "Too high."}', '{"score": 3, "reason": ""}', "not a rating at all"],
)
async def test_the_real_model_refuses_a_reply_that_is_not_a_valid_rating(reply: str) -> None:
    with canned_anthropic(message(reply)) as server, pytest.raises(OutputParserException):
        await anthropic_model(fake_key(), base_url=server.url).ainvoke("Rate this.")
