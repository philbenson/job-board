"""The interviewer's real model, against a canned local server, as the interview binds it."""

import json
import secrets
from functools import cached_property
from typing import Any

import anthropic
import pytest
from canned_anthropic import canned_anthropic, error, message
from canned_tool_use import CALL_ID, tool_use
from langchain_anthropic import ChatAnthropic
from langchain_core.load import dumpd
from langchain_core.messages import AIMessage, BaseMessage

from job_board.interview.model import CUT_OFF, TIMEOUT_SECONDS, anthropic_interviewer
from job_board.interview.prompt import (
    SAY_IT_AGAIN,
    answer_message,
    notice,
    opening_message,
    system_message,
)
from job_board.interview.tools import TOOLS
from job_board.model_key.check import ANTHROPIC_API, CHECK_MODEL

RESUME = "Staff engineer at Example Co since 2019, writing Python and Go."
PACE = {"leads_per_day": 10, "brief_from_score": None}
# A conversation as the graph keeps it: the opener, a question, the service's
# notice and the answer that follows it.
CONVERSATION: list[BaseMessage] = [
    opening_message('{"target_titles": []}'),
    AIMessage("Which titles are you after?"),
    notice(SAY_IT_AGAIN),
    answer_message("Staff engineer.", None),
]


def fake_key() -> str:
    return f"sk-ant-api03-{secrets.token_urlsafe(48)}"


async def test_one_request_carries_the_settings_the_tools_the_cached_system_block_and_the_key() -> (
    None
):
    key = fake_key()
    with canned_anthropic(message("Which places will you work in?")) as server:
        model = anthropic_interviewer(key, base_url=server.url)
        await model.bind_tools(TOOLS).ainvoke([system_message(RESUME), *CONVERSATION])

    [request] = server.received
    assert request.path == "/v1/messages"
    assert request.headers["authorization"] == f"Bearer {key}"
    assert "x-api-key" not in request.headers
    body: dict[str, Any] = request.body
    assert body["model"] == CHECK_MODEL
    assert body["max_tokens"] == 8192
    assert body["thinking"] == {"type": "adaptive", "display": "omitted"}
    assert body["output_config"] == {"effort": "medium"}
    assert body["tools"] == list(TOOLS)
    assert len(body["tools"]) == 11
    [system] = body["system"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert RESUME in system["text"]
    sent = json.dumps(body)
    assert SAY_IT_AGAIN in sent
    assert "job_board_notice" not in sent  # the notice's mark stays in the service


async def test_a_failed_request_is_sent_once() -> None:
    with canned_anthropic(error(500, "api_error")) as server:
        model = anthropic_interviewer(fake_key(), base_url=server.url)
        with pytest.raises(anthropic.InternalServerError):
            await model.bind_tools(TOOLS).ainvoke([system_message(RESUME), *CONVERSATION])
    assert len(server.received) == 1


async def test_a_tool_use_reply_comes_back_as_a_tool_call() -> None:
    with canned_anthropic(tool_use("save_pace", PACE)) as server:
        model = anthropic_interviewer(fake_key(), base_url=server.url)
        reply = await model.bind_tools(TOOLS).ainvoke([system_message(RESUME), *CONVERSATION])

    assert isinstance(reply, AIMessage)
    assert reply.tool_calls == [
        {"name": "save_pace", "args": PACE, "id": CALL_ID, "type": "tool_call"}
    ]


async def test_a_reply_at_the_token_limit_carries_the_stop_reason_the_interviewer_reads() -> None:
    with canned_anthropic(message("Which places", stop_reason="max_tokens")) as server:
        model = anthropic_interviewer(fake_key(), base_url=server.url)
        reply = await model.bind_tools(TOOLS).ainvoke([system_message(RESUME), *CONVERSATION])

    assert reply.response_metadata["stop_reason"] == CUT_OFF


def test_the_model_gives_up_connecting_after_five_seconds_and_reading_after_its_timeout() -> None:
    model = anthropic_interviewer(fake_key(), base_url="http://127.0.0.1:9")
    assert isinstance(model, ChatAnthropic)
    expected = anthropic.Timeout(TIMEOUT_SECONDS, connect=5.0)
    assert [model._async_client.timeout, model._client.timeout] == [expected, expected]


async def test_the_model_ignores_the_environments_anthropic_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Either variable would otherwise send the person's key to whatever it names.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ANTHROPIC_API_URL", "http://127.0.0.1:9")
    model = anthropic_interviewer(fake_key())
    assert isinstance(model, ChatAnthropic)
    sent_to = [str(model._async_client.base_url), str(model._client.base_url)]
    assert sent_to == [ANTHROPIC_API, ANTHROPIC_API]

    key = fake_key()
    with canned_anthropic(message("Which places will you work in?")) as server:
        model = anthropic_interviewer(key, base_url=server.url)
        await model.bind_tools(TOOLS).ainvoke([system_message(RESUME), *CONVERSATION])
    [request] = server.received
    assert request.headers["authorization"] == f"Bearer {key}"


def test_langchain_still_sends_through_the_two_clients_the_interviewer_replaces() -> None:
    # The interviewer's model replaces LangChain's own two client properties.
    # Were an upgrade to rename them, the replacements would be clients nothing
    # sends through, and the test above would still pass on them.
    for name in ("_client", "_async_client"):
        assert isinstance(vars(ChatAnthropic).get(name), cached_property), name


def test_the_model_waits_out_its_timeout_and_shows_the_key_in_none_of_its_forms() -> None:
    key = fake_key()
    model = anthropic_interviewer(key, base_url="http://127.0.0.1:9")
    assert isinstance(model, ChatAnthropic)
    assert model.default_request_timeout == TIMEOUT_SECONDS
    forms = [repr(model), str(model), str(dumpd(model))]
    assert [form for form in forms if key in form] == []
