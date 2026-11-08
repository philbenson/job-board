"""The interviewer's tools: one save for each profile section, and the end of the interview.

Invariant: the interviewer can change only the signed-in person's profile, and
only with input that section's own route would accept. The person's id comes
from the run's context alone: no tool's schema has a field for it, and a call
carrying one is refused, as the route refuses any key it does not name. Each
save is checked by the section's request model, the route's own, and written by
the one statement the routes use, so it stores exactly what the route would.

The schemas are built once, here, and never change within an interview, so
every request carries the same tool list.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import ToolCall, ToolMessage
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_board.profile_sections import (
    Companies,
    DealBreakers,
    Gaps,
    OwnRules,
    Pace,
    Pay,
    Places,
    Skills,
    TargetTitles,
    TitleRange,
)
from job_board.profiles import save_section

FINISH = "finish_interview"

# The Profile fields a tool saves: one for each section.
SectionName = Literal[
    "target_titles",
    "title_range",
    "places",
    "pay",
    "skills",
    "gaps",
    "deal_breakers",
    "companies",
    "pace",
    "own_rules",
]


@dataclass(frozen=True)
class SectionTool:
    section: SectionName  # the Profile field it replaces
    body: type[BaseModel]  # the request model of that section's route
    subject: str  # what the section holds, for the tool's description
    # The one field of the body stored as the whole section, for the target
    # titles, which are stored as a bare list; None stores the whole body.
    stored_field: str | None = None

    @property
    def name(self) -> str:
        return f"save_{self.section}"


SECTION_TOOLS = (
    SectionTool("target_titles", TargetTitles, "target job titles", stored_field="titles"),
    SectionTool("title_range", TitleRange, "range of titles around their target titles"),
    SectionTool("places", Places, "places they will work"),
    SectionTool("pay", Pay, "pay"),
    SectionTool("skills", Skills, "skills"),
    SectionTool("gaps", Gaps, "gaps they will apply with and trade-offs they will take"),
    SectionTool("deal_breakers", DealBreakers, "deal-breakers"),
    SectionTool("companies", Companies, "companies they watch and jobs they have applied to"),
    SectionTool("pace", Pace, "pace of leads"),
    SectionTool("own_rules", OwnRules, "own rules for close calls"),
)
_BY_NAME = {tool.name: tool for tool in SECTION_TOOLS}


def _inlined(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with each ``$ref`` replaced by the definition it names, and no ``$defs``.

    No section's model refers to itself, so the replacing ends.
    """
    definitions: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                named = definitions[node["$ref"].removeprefix("#/$defs/")]
                beside = {key: resolve(value) for key, value in node.items() if key != "$ref"}
                return {**resolve(named), **beside}
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


def _schema(tool: SectionTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": (
            f"Save the person's {tool.subject} in their profile. The input replaces the whole "
            "section as stored, so it must hold everything the section should keep. The answer "
            "is the section as stored, or each problem with the input, when it is refused."
        ),
        "input_schema": _inlined(tool.body.model_json_schema()),
    }


# In Anthropic's own form, which LangChain's client sends as it is.
TOOLS: tuple[dict[str, Any], ...] = (
    *(_schema(tool) for tool in SECTION_TOOLS),
    {
        "name": FINISH,
        "description": (
            "End the interview: call it when every section is answered, or as soon as the "
            "person asks to stop."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
)


def _call_id(call: ToolCall) -> str:
    # Anthropic names every call; LangChain's type allows a call without one.
    return call["id"] or ""


def _refused(call: ToolCall, why: str) -> ToolMessage:
    return ToolMessage(why, tool_call_id=_call_id(call), name=call["name"], status="error")


def _problems(refusal: ValidationError) -> str:
    """Each problem by its place in the input and its kind, quoting no value of the input."""
    problems = refusal.errors(include_url=False, include_input=False, include_context=False)
    named = (
        f"{'.'.join(str(step) for step in problem['loc']) or 'the input'}: {problem['type']}"
        for problem in problems
    )
    return "Refused, and nothing saved: " + "; ".join(named)


def saved_section(answer: ToolMessage) -> SectionName | None:
    """The section a save's answer says was stored, or None for a refusal or the end."""
    tool = _BY_NAME.get(answer.name or "")
    return tool.section if tool is not None and answer.status == "success" else None


def finished(call: ToolCall) -> ToolMessage:
    return ToolMessage("The interview is over.", tool_call_id=_call_id(call), name=FINISH)


async def save(
    call: ToolCall, person_id: int, sessionmaker: async_sessionmaker[AsyncSession]
) -> ToolMessage:
    """Runs one save call for ``person_id``, answering the section as stored or why not.

    Running it again with the same call stores the same section again.
    """
    tool = _BY_NAME.get(call["name"])
    if tool is None:
        return _refused(call, "No tool has that name; the tools are the ones listed.")
    try:
        body = tool.body.model_validate(call["args"])
    except ValidationError as refusal:
        return _refused(call, _problems(refusal))
    value = body.model_dump(mode="json")
    if tool.stored_field is not None:
        value = value[tool.stored_field]
    async with sessionmaker() as session:
        profile = await save_section(session, person_id, tool.section, value)
    stored = profile.model_dump(mode="json")[tool.section]
    return ToolMessage(json.dumps(stored), tool_call_id=_call_id(call), name=call["name"])
