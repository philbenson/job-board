"""A canned Anthropic reply that calls a tool, for the interviewer's tests of the real model."""

from typing import Any

from canned_anthropic import Reply, message

CALL_ID = "toolu_canned"


def tool_use(name: str, arguments: dict[str, Any]) -> Reply:
    """A reply calling the tool ``name`` with ``arguments``, after its thinking block."""
    reply = message(None, stop_reason="tool_use")
    reply.body["content"].append(
        {"type": "tool_use", "id": CALL_ID, "name": name, "input": arguments}
    )
    return reply
