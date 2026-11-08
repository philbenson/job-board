"""The interview graph: the interviewer asks, the person answers, the tools save.

The graph is compiled once per application, with the saver, and each run
reaches it with its own context: the person's id, the run's id, the chat model
built on that person's key, and the session maker. The context is never part
of the state, so none of it is saved with a step.

Invariant: within one interview, every request is the previous one with
messages added at the end (see ``prompt``), and the tool list never changes.

Invariant: no database connection is held while the model answers. Each read
and write opens its own short session.

Invariant: the ``ask`` node does nothing before it waits. When an answer
arrives, LangGraph runs the node again from its first line.
"""

from dataclasses import dataclass, field
from typing import Annotated, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_board.interview.claims import renew_claim
from job_board.interview.failures import EmptyReply, LostClaim, ModelDeclined, ReplyCutOff
from job_board.interview.model import CUT_OFF, DECLINED
from job_board.interview.prompt import (
    LIMIT_REACHED,
    SAY_IT_AGAIN,
    answer_message,
    notice,
    opening_message,
    system_message,
)
from job_board.interview.tools import FINISH, TOOLS, finished, save
from job_board.models import ProfileRow
from job_board.profiles import Profile, stored_profile

# Model calls in one interview: ten sections, a question, a save and a
# correction or two each, with room to spare; past it, the interview stops.
INTERVIEW_MODEL_CALLS = 60
# Model calls between two answers: a save, a correction and the next question,
# with one to spare. More means the model is stuck on what it was told.
ANSWER_MODEL_CALLS = 4

type Ended = Literal["finished", "stopped"]


class InterviewState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    resume_text: str  # the checked resume text when the interview started
    profile_shown: str  # the stored profile's JSON as the model last saw it
    model_calls: int
    calls_since_answer: int
    ended: Ended | None


@dataclass(frozen=True)
class Context:
    person_id: int
    run_id: str
    model: BaseChatModel = field(repr=False)
    sessionmaker: async_sessionmaker[AsyncSession] = field(repr=False)


async def profile_json(sessionmaker: async_sessionmaker[AsyncSession], person_id: int) -> str:
    """The person's profile as the profile route answers it, as JSON."""
    async with sessionmaker() as session:
        document = await session.scalar(
            select(ProfileRow.document).where(ProfileRow.person_id == person_id)
        )
    return (Profile() if document is None else stored_profile(document)).model_dump_json()


def thread_config(thread_id: str) -> RunnableConfig:
    """The configuration naming the interview's thread, the key of its saved steps."""
    return {"configurable": {"thread_id": thread_id}}


def start_input(resume_text: str, shown: str) -> InterviewState:
    """A new interview's state: the opening message, holding the stored profile ``shown``."""
    return {
        "messages": [opening_message(shown)],
        "resume_text": resume_text,
        "profile_shown": shown,
        "model_calls": 0,
        "calls_since_answer": 0,
        "ended": None,
    }


async def _renew_claim(context: Context) -> None:
    if not await renew_claim(context.sessionmaker, context.person_id, context.run_id):
        raise LostClaim


def _asked_with_the_tool_calls(messages: list[AnyMessage]) -> bool:
    """True when the last step ran tool calls whose reply also asked something."""
    if not isinstance(messages[-1], ToolMessage):
        return False
    calling = next(message for message in reversed(messages) if isinstance(message, AIMessage))
    return bool(calling.text.strip())


async def _interviewer(state: InterviewState, runtime: Runtime[Context]) -> InterviewState:
    """The model's next reply, or the service's own line when a limit is reached.

    A reply cut off at the token limit, declined by the model, or holding
    nothing raises, and nothing of it is kept, so none of its tool calls runs:
    the run fails, and a retry asks again from the step before. The one empty
    reply kept from failing is one after tool calls whose reply asked a
    question: the model had nothing to add, so the interview waits on that
    question, with the empty reply counted as a call and kept out of the
    conversation.
    """
    context = runtime.context
    await _renew_claim(context)
    calls = state["model_calls"]
    if calls >= INTERVIEW_MODEL_CALLS:
        return {"messages": [notice(LIMIT_REACHED)], "ended": "stopped"}
    if state["calls_since_answer"] >= ANSWER_MODEL_CALLS:
        return {"messages": [notice(SAY_IT_AGAIN)]}
    request = [system_message(state["resume_text"]), *state["messages"]]
    reply = await context.model.bind_tools(TOOLS).ainvoke(request)
    # Renewed again, so a run whose claim was taken while the model answered
    # keeps nothing of the reply and writes no step over the run that took it.
    await _renew_claim(context)
    stop_reason = reply.response_metadata.get("stop_reason")
    if stop_reason == CUT_OFF:
        raise ReplyCutOff
    if stop_reason == DECLINED:
        raise ModelDeclined
    if not reply.tool_calls and not reply.text.strip():
        if not _asked_with_the_tool_calls(state["messages"]):
            raise EmptyReply
        return {"model_calls": calls + 1, "calls_since_answer": state["calls_since_answer"] + 1}
    return {
        "messages": [reply],
        "model_calls": calls + 1,
        "calls_since_answer": state["calls_since_answer"] + 1,
    }


def _after_interviewer(state: InterviewState) -> str:
    if state.get("ended") is not None:
        return END
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else "ask"


async def _tools(state: InterviewState, runtime: Runtime[Context]) -> InterviewState:
    """Runs the reply's tool calls in order, then notes the profile the model now knows.

    Run again, it repeats the same saves, which store the same sections. The
    claim is renewed first: a step run again by a run whose claim was taken
    over, or whose interview was removed, saves nothing.
    """
    context = runtime.context
    await _renew_claim(context)
    last = state["messages"][-1]
    calls = last.tool_calls if isinstance(last, AIMessage) else []
    answers: list[ToolMessage] = []
    for call in calls:
        if call["name"] == FINISH:
            answers.append(finished(call))
        else:
            answers.append(await save(call, context.person_id, context.sessionmaker))
    update: InterviewState = {
        "messages": list(answers),
        # The model saw each save's result, so only a change made elsewhere
        # is worth showing it again.
        "profile_shown": await profile_json(context.sessionmaker, context.person_id),
    }
    if any(call["name"] == FINISH for call in calls):
        update["ended"] = "finished"
    return update


def _after_tools(state: InterviewState) -> str:
    return END if state.get("ended") == "finished" else "interviewer"


def _question(messages: list[AnyMessage]) -> str:
    return next(message.text for message in reversed(messages) if isinstance(message, AIMessage))


async def _ask(state: InterviewState, runtime: Runtime[Context]) -> InterviewState:
    """Waits for the person's answer to the last question, then adds it to the conversation.

    The stored profile goes with the answer when it differs from what the model
    last saw, which happens only after an edit by hand.
    """
    answer: str = interrupt(_question(state["messages"]))
    context = runtime.context
    shown = await profile_json(context.sessionmaker, context.person_id)
    changed = shown if shown != state["profile_shown"] else None
    return {
        "messages": [answer_message(answer, changed)],
        "profile_shown": shown,
        "calls_since_answer": 0,
    }


type InterviewGraph = CompiledStateGraph[InterviewState, Context, InterviewState, InterviewState]


def build_interview_graph(checkpointer: BaseCheckpointSaver[str]) -> InterviewGraph:
    builder = StateGraph(InterviewState, context_schema=Context)
    builder.add_node("interviewer", _interviewer)
    builder.add_node("tools", _tools)
    builder.add_node("ask", _ask)
    builder.add_edge(START, "interviewer")
    builder.add_conditional_edges("interviewer", _after_interviewer, ["tools", "ask", END])
    builder.add_conditional_edges("tools", _after_tools, ["interviewer", END])
    builder.add_edge("ask", "interviewer")
    return builder.compile(checkpointer=checkpointer)
