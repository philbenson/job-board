"""What the interview's routes answer: its status and conversation, read from the saved steps.

Invariant: an answer quotes only what the interviewer and the person said, the
service's own notices and the names of the sections saved. The opening
message, the profile sent along with an answer and the tools' answers to the
model never appear in it.
"""

from dataclasses import dataclass, field
from typing import Annotated, Literal, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.types import StateSnapshot
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.interview import graph
from job_board.interview.claims import live_claim
from job_board.interview.failures import InterviewFailure
from job_board.interview.graph import InterviewGraph, thread_config
from job_board.interview.prompt import is_notice
from job_board.interview.tools import SectionName, saved_section
from job_board.model_errors import PROVIDER
from job_board.models import InterviewRow, ModelKey, ResumeRow

InterviewStatus = Literal["not-started", "running", "waiting", "failed", "finished", "stopped"]
# What a start still needs: a key Anthropic has not refused, and the resume's
# text as the person checked it.
Missing = Literal["working-key", "checked-resume-text"]


class Said(BaseModel):
    """A line of the conversation: the interviewer's, the person's, or the service's own."""

    kind: Literal["interviewer", "person", "notice"]
    text: str


class Saved(BaseModel):
    """A section of the profile the interviewer saved."""

    kind: Literal["saved"]
    section: SectionName


Entry = Annotated[Said | Saved, Field(discriminator="kind")]


class Interview(BaseModel):
    """The signed-in person's interview, as the screen shows it.

    ``missing`` is what a start still needs, empty when nothing is. ``failure``
    is set only when the interview failed, and ``question`` only while it waits
    on an answer.
    """

    status: InterviewStatus
    missing: list[Missing]
    failure: InterviewFailure | None
    question: str | None
    entries: list[Entry]
    model_calls: int
    model_call_limit: int


@dataclass(frozen=True)
class Readiness:
    """What a run needs from the person's other rows."""

    sealed_key: bytes | None = field(repr=False)  # the person's key, unless Anthropic refused it
    resume_text: str | None = field(repr=False)  # the resume's text, once the person checked it

    @property
    def missing(self) -> list[Missing]:
        missing: list[Missing] = []
        if self.sealed_key is None:
            missing.append("working-key")
        if self.resume_text is None:
            missing.append("checked-resume-text")
        return missing


async def readiness(session: AsyncSession, person_id: int) -> Readiness:
    sealed_key = await session.scalar(
        select(ModelKey.sealed_key).where(
            ModelKey.person_id == person_id,
            ModelKey.provider == PROVIDER,
            ModelKey.failure.is_(None),
        )
    )
    resume_text = await session.scalar(
        select(ResumeRow.text).where(
            ResumeRow.person_id == person_id, ResumeRow.text_checked_at.is_not(None)
        )
    )
    return Readiness(sealed_key, resume_text)


@dataclass(frozen=True)
class Found:
    """An interview's row, read with its thread's last saved step."""

    thread_id: str
    running: bool  # a live run holds the claim
    failure: InterviewFailure | None  # why the last run stopped short, when it did
    snapshot: StateSnapshot = field(repr=False)

    @property
    def step(self) -> str | None:
        """The id of the saved step the snapshot read, None for a thread with none."""
        step = self.snapshot.config.get("configurable", {}).get("checkpoint_id")
        return step if isinstance(step, str) else None


async def found_interview(
    session: AsyncSession, interview_graph: InterviewGraph, person_id: int
) -> Found | None:
    """The interview's row and its thread's last saved step, or None when there is none.

    The row is read on both sides of the snapshot, so a run that took the claim
    while the steps were read shows as running rather than its half-made step
    as the interview's state. A run that both started and ended between the
    two row reads, a few milliseconds apart, is not seen.
    """
    before = (
        await session.execute(
            select(InterviewRow.thread_id, live_claim().label("running")).where(
                InterviewRow.person_id == person_id
            )
        )
    ).one_or_none()
    if before is None:
        return None
    snapshot = await interview_graph.aget_state(thread_config(before.thread_id))
    after = (
        await session.execute(
            select(InterviewRow.failure, live_claim().label("running")).where(
                InterviewRow.person_id == person_id
            )
        )
    ).one_or_none()
    if after is None:  # removed while its steps were read
        return None
    # The table's check holds the failure to the codes, or none.
    failure = cast("InterviewFailure | None", after.failure)
    return Found(before.thread_id, before.running or after.running, failure, snapshot)


def _waiting_on(snapshot: StateSnapshot) -> str | None:
    """The question a thread paused at ``ask`` waits on, or None for a thread not paused there."""
    if snapshot.next != ("ask",) or not snapshot.interrupts:
        return None
    question = snapshot.interrupts[0].value
    return question if isinstance(question, str) else None


def status_of(found: Found) -> tuple[InterviewStatus, InterviewFailure | None, str | None]:
    """The interview's status, with its failure when failed and its question when waiting.

    A recorded failure comes before a pause at ``ask``: a run that failed in
    that node, after its answer arrived, leaves the thread paused there with
    the answer saved. A retry goes on with that answer; a second answer would
    be dropped for it, unseen. A thread neither paused nor ended, with no
    failure recorded, belongs to a run that stopped without releasing its
    claim.
    """
    if found.running:
        return "running", None, None
    if found.failure is not None:
        return "failed", found.failure, None
    question = _waiting_on(found.snapshot)
    if question is not None:
        return "waiting", None, question
    ended = found.snapshot.values.get("ended")
    if ended == "finished":
        return "finished", None, None
    if ended == "stopped":
        return "stopped", None, None
    return "failed", "interrupted", None


def _first_text(message: HumanMessage) -> str:
    # An answer's first block is the answer; a second, when there is one, is
    # the profile sent along with it.
    content = message.content
    if isinstance(content, str):
        return content
    first = content[0]
    if isinstance(first, str):
        return first
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _entries(messages: list[AnyMessage]) -> list[Entry]:
    shown: list[Entry] = []
    for message in messages[1:]:  # the first is the opening message, the service's own
        if isinstance(message, AIMessage):
            if is_notice(message):
                shown.append(Said(kind="notice", text=message.text))
            elif message.text.strip():  # a reply of tool calls alone says nothing
                shown.append(Said(kind="interviewer", text=message.text))
        elif isinstance(message, HumanMessage):
            shown.append(Said(kind="person", text=_first_text(message)))
        elif isinstance(message, ToolMessage):
            section = saved_section(message)
            if section is not None:
                shown.append(Saved(kind="saved", section=section))
    return shown


def interview_answer(
    found: Found | None, missing: list[Missing], *, started: bool = False
) -> Interview:
    """The interview as the routes answer it; ``started`` for a run a route has just started."""
    values = {} if found is None else found.snapshot.values
    if started:
        status, failure, question = "running", None, None
    elif found is None:
        status, failure, question = "not-started", None, None
    else:
        status, failure, question = status_of(found)
    return Interview(
        status=status,
        missing=missing,
        failure=failure,
        question=question,
        entries=_entries(values.get("messages", [])),
        model_calls=values.get("model_calls", 0),
        model_call_limit=graph.INTERVIEW_MODEL_CALLS,  # read here, so a test may lower it
    )
