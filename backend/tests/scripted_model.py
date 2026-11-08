"""A fake chat model for the interviewer, answering from a script and recording each request."""

import itertools
import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field

_CALL_IDS = itertools.count(1)


class ScriptedModel(GenericFakeChatModel):
    """Answers each request with the next scripted reply, or raises it.

    ``requests`` holds the messages of each request and ``tool_lists`` the tool
    list of each binding, as JSON. ``key`` stands for the person's key, which
    the real model holds, so a test can look for it wherever the run keeps
    anything.
    """

    script: list[AIMessage | BaseException] = Field(default_factory=list)
    requests: list[list[BaseMessage]] = Field(default_factory=list)
    tool_lists: list[str] = Field(default_factory=list)
    key: str = ""
    disable_streaming: bool = True

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        self.tool_lists.append(json.dumps(list(tools)))
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.requests.append(list(messages))
        reply = self.script.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


def scripted(*replies: AIMessage | BaseException, key: str = "") -> ScriptedModel:
    return ScriptedModel(messages=iter(()), script=list(replies), key=key)


def calling(*calls: tuple[str, dict[str, Any]], text: str = "") -> AIMessage:
    """A reply making these tool calls, each by its name and input, in order."""
    tool_calls = [
        ToolCall(name=name, args=args, id=f"toolu_{next(_CALL_IDS):06d}", type="tool_call")
        for name, args in calls
    ]
    return AIMessage(text, tool_calls=tool_calls)
