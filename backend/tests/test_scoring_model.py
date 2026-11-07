"""The rating's rules, and the real model factory against a canned local server."""

import secrets
from typing import Any

import pytest
from canned_anthropic import canned_anthropic, message, rating
from langchain_core.exceptions import ModelRefusalError, OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.load import dumpd
from langchain_core.runnables import RunnableBinding, RunnableParallel, RunnableSequence
from pydantic import ValidationError

from job_board.model_key.check import CHECK_MODEL
from job_board.scoring.model import MAX_REASON_LENGTH, Rating, ReplyCutOff, anthropic_model


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


@pytest.mark.parametrize(
    "reason",
    [
        "Fine\x00",
        "Fi\x00ne",
        "Fine\x07",
        "Fine\x7f",
        "Fine\x9b",
        "Fine\ud800",
        "Fine\u202e",
        "\u2066Fine",
    ],
    ids=["nul", "inner-nul", "bell", "delete", "c1", "surrogate", "right-to-left", "isolate"],
)
def test_a_rating_refuses_a_reason_holding_a_control_a_surrogate_or_a_direction_control(
    reason: str,
) -> None:
    with pytest.raises(ValidationError):
        Rating.model_validate({"score": 3, "reason": reason})


def test_a_rating_keeps_a_reason_of_the_longest_length_trimmed() -> None:
    reason = "x" * MAX_REASON_LENGTH
    assert Rating.model_validate({"score": 3, "reason": f" {reason}\n"}).reason == reason


async def test_the_real_model_sends_the_key_the_model_id_the_effort_the_cap_and_the_schema() -> (
    None
):
    key = fake_key()
    with canned_anthropic(rating(4, "A close match for the profile.")) as server:
        result = await anthropic_model(key, base_url=server.url).ainvoke("Rate this.")

    assert result == Rating(score=4, reason="A close match for the profile.")
    [request] = server.received
    assert request.path == "/v1/messages"
    assert request.headers["authorization"] == f"Bearer {key}"
    assert "x-api-key" not in request.headers
    body: dict[str, Any] = request.body
    assert body["model"] == CHECK_MODEL
    assert body["max_tokens"] == 4096
    assert body["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert body["output_config"]["effort"] == "low"
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


async def test_the_real_model_lets_a_refusal_through_as_a_refusal() -> None:
    refused = message(None, stop_reason="refusal")
    with canned_anthropic(refused) as server, pytest.raises(ModelRefusalError):
        await anthropic_model(fake_key(), base_url=server.url).ainvoke("Rate this.")


# The parser mends unclosed JSON, so the first of these would read as a rating
# whose reason stops mid-word were the stop reason not checked.
@pytest.mark.parametrize(
    "text",
    ['{"score": 4, "reason": "A close mat', '{"score": 4, "rea', None],
    ids=["mid-reason", "mid-key", "no-text"],
)
async def test_the_real_model_tells_a_reply_cut_off_at_the_limit_from_an_unreadable_one(
    text: str | None,
) -> None:
    cut_off = message(text, stop_reason="max_tokens")
    with canned_anthropic(cut_off) as server, pytest.raises(ReplyCutOff) as raised:
        await anthropic_model(fake_key(), base_url=server.url).ainvoke("Rate this.")
    assert str(raised.value) == ""  # it carries none of the reply
    assert raised.value.__cause__ is None and raised.value.__context__ is None


async def test_the_real_model_takes_a_whole_rating_that_stopped_at_the_limit() -> None:
    whole = message('{"score": 4, "reason": "A close match."}', stop_reason="max_tokens")
    with canned_anthropic(whole) as server:
        result = await anthropic_model(fake_key(), base_url=server.url).ainvoke("Rate this.")
    assert result == Rating(score=4, reason="A close match.")


async def test_the_real_model_refuses_a_whole_but_invalid_reply_at_the_limit_as_unreadable() -> (
    None
):
    invalid = message('{"score": 9, "reason": "Off the scale."}', stop_reason="max_tokens")
    with canned_anthropic(invalid) as server, pytest.raises(OutputParserException):
        await anthropic_model(fake_key(), base_url=server.url).ainvoke("Rate this.")


def chat_model_of(model: object) -> BaseChatModel:
    """The chat model inside the factory's model: the runnable its first step binds as raw."""
    assert isinstance(model, RunnableSequence)
    assert isinstance(model.first, RunnableParallel)
    binding = model.first.steps__["raw"]
    assert isinstance(binding, RunnableBinding)
    assert isinstance(binding.bound, BaseChatModel)
    return binding.bound


def test_the_real_model_shows_the_key_in_none_of_its_text_or_serialized_forms() -> None:
    key = fake_key()
    model = anthropic_model(key, base_url="http://127.0.0.1:9")
    chat = chat_model_of(model)
    forms = [repr(model), str(model), repr(chat), str(chat), str(dumpd(model)), str(dumpd(chat))]
    assert [form for form in forms if key in form] == []
