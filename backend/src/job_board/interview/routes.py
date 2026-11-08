"""``/interview``: start, answer, retry, read and remove the signed-in person's interview.

Invariant: one run at a time per person. Each route that starts a run first
takes the interview's claim, in one statement that yields to a live run, and
commits it before the run begins; the run releases it.

Invariant: whether an interview may be answered or retried is read from its
thread's saved steps, so an answer is sent only to a thread paused at ``ask``.
The claim is taken only while the last saved step is still the one read, so
an answer goes only to the question its sender saw.

Nothing here logs or answers the resume, an answer or a reply except as the
conversation's entries, which only the person reads.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from langgraph.types import Command
from pydantic import AfterValidator, BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.interview.answer_text import checked_answer
from job_board.interview.answers import (
    Found,
    Interview,
    found_interview,
    interview_answer,
    readiness,
    status_of,
)
from job_board.interview.claims import claim, live_claim, unclaimed
from job_board.interview.graph import InterviewGraph, InterviewState, profile_json, start_input
from job_board.interview.model import InterviewModelFactory, anthropic_interviewer
from job_board.interview.runs import InterviewRuns, RunServices, Turn, run_interview
from job_board.models import InterviewRow, Person
from job_board.people import SIGN_IN_REQUIRED, Refused, current_person, get_settings
from job_board.resumes.text_routes import TextRefused
from job_board.settings import Settings

NO_INTERVIEW = "No interview started"
ALREADY_STARTED = "Your interview has already started"
NO_WORKING_KEY = "The interview needs a working Anthropic key saved first"
NO_CHECKED_TEXT = "The interview needs your resume's text checked first"
RUNNING = "The interview is taking its turn; wait for it to finish"
CHANGED = "The interview has changed since it was read; reload it and try again"
NOT_WAITING = "The interview is not waiting on an answer"
NOT_FAILED = "The interview has not failed, so there is nothing to retry"

NO_INTERVIEW_ANSWER: dict[int | str, dict[str, Any]] = {
    404: {"model": Refused, "description": NO_INTERVIEW},
}

router = APIRouter()


class AnswerToSend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, AfterValidator(checked_answer)]


def interview_model_factory() -> InterviewModelFactory:
    """Builds each run's chat model from the person's key; the tests put a scripted one here."""
    return anthropic_interviewer


def interview_graph(request: Request) -> InterviewGraph:
    built: InterviewGraph = request.app.state.interview_graph
    return built


def interview_runs(request: Request) -> InterviewRuns:
    runs: InterviewRuns = request.app.state.interview_runs
    return runs


def run_services(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    graph: Annotated[InterviewGraph, Depends(interview_graph)],
    model_factory: Annotated[InterviewModelFactory, Depends(interview_model_factory)],
) -> RunServices:
    return RunServices(
        graph=graph,
        saver=request.app.state.interview_saver,
        sessionmaker=request.app.state.sessionmaker,
        service_key=settings.model_key_encryption_key.get_secret_value(),
        model_factory=model_factory,
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _no_interview() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_INTERVIEW)


async def _found(session: AsyncSession, graph: InterviewGraph, person_id: int) -> Found:
    found = await found_interview(session, graph, person_id)
    if found is None:
        raise _no_interview()
    if found.running:
        raise _conflict(RUNNING)
    return found


async def _claimed_run(
    session: AsyncSession,
    runs: InterviewRuns,
    services: RunServices,
    turn: Turn,
    found: Found,
) -> None:
    """Takes the claim for ``turn`` and starts its run.

    It refuses while a live run holds the claim, and when the interview has
    moved on from the step ``found`` read.
    """
    if not await claim(session, turn.person_id, turn.run_id, found.step):
        held = await session.scalar(
            select(live_claim()).where(InterviewRow.person_id == turn.person_id)
        )
        if held is None:
            raise _no_interview()
        raise _conflict(RUNNING if held else CHANGED)
    await session.commit()
    runs.start(run_interview(services, turn))


def _new_run_id() -> str:
    return str(uuid.uuid4())


@router.get("/interview", responses={**SIGN_IN_REQUIRED})
async def read_interview(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    graph: Annotated[InterviewGraph, Depends(interview_graph)],
) -> Interview:
    found = await found_interview(session, graph, person.id)
    ready = await readiness(session, person.id)
    return interview_answer(found, ready.missing)


@router.post(
    "/interview",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **SIGN_IN_REQUIRED,
        409: {
            "model": Refused,
            "description": "The interview has already started, or a start still needs "
            "a working key or the resume's checked text",
        },
    },
)
async def start_interview(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    services: Annotated[RunServices, Depends(run_services)],
    runs: Annotated[InterviewRuns, Depends(interview_runs)],
) -> Interview:
    """Starts the interview, whose run asks the first question; read it to see the run end."""
    ready = await readiness(session, person.id)
    sealed_key, resume_text = ready.sealed_key, ready.resume_text
    if sealed_key is None:
        raise _conflict(NO_WORKING_KEY)
    if resume_text is None:
        raise _conflict(NO_CHECKED_TEXT)
    graph_input = start_input(resume_text, await profile_json(services.sessionmaker, person.id))
    turn = Turn(person.id, _new_run_id(), str(uuid.uuid4()), sealed_key, graph_input)
    # Made with its claim taken, in the one statement, so of two starts at once
    # one makes the interview and the other finds it.
    made = await session.scalar(
        insert(InterviewRow)
        .values(
            person_id=person.id,
            thread_id=turn.thread_id,
            run_id=turn.run_id,
            running_since=func.now(),
        )
        .on_conflict_do_nothing()
        .returning(InterviewRow.person_id)
    )
    if made is None:
        raise _conflict(ALREADY_STARTED)
    await session.commit()
    runs.start(run_interview(services, turn))
    return interview_answer(None, [], started=True)


# The declared 422 replaces FastAPI's validation 422 in the API description,
# with the shape the app's one validation answer gives.
@router.post(
    "/interview/answer",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **SIGN_IN_REQUIRED,
        **NO_INTERVIEW_ANSWER,
        409: {
            "model": Refused,
            "description": "The interview is not waiting on an answer, has changed since it "
            "was read, or has no working key",
        },
        422: {
            "model": TextRefused,
            "description": "The answer breaks one of its rules, or the body is of another shape",
        },
    },
)
async def answer_interview(
    body: AnswerToSend,
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    services: Annotated[RunServices, Depends(run_services)],
    runs: Annotated[InterviewRuns, Depends(interview_runs)],
) -> Interview:
    """Sends the answer to the question the interview waits on; its run asks the next."""
    found = await _found(session, services.graph, person.id)
    if status_of(found)[0] != "waiting":
        raise _conflict(NOT_WAITING)
    ready = await readiness(session, person.id)
    if ready.sealed_key is None:
        raise _conflict(NO_WORKING_KEY)
    resume: Command[str] = Command(resume=body.text)
    turn = Turn(person.id, _new_run_id(), found.thread_id, ready.sealed_key, resume)
    await _claimed_run(session, runs, services, turn, found)
    return interview_answer(found, ready.missing, started=True)


@router.post(
    "/interview/retry",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **SIGN_IN_REQUIRED,
        **NO_INTERVIEW_ANSWER,
        409: {
            "model": Refused,
            "description": "The interview has not failed or has changed since it was read, "
            "or a retry still needs a working key or the resume's checked text",
        },
    },
)
async def retry_interview(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    services: Annotated[RunServices, Depends(run_services)],
    runs: Annotated[InterviewRuns, Depends(interview_runs)],
) -> Interview:
    """Runs a failed interview again from its last saved step, asking the model again."""
    found = await _found(session, services.graph, person.id)
    if status_of(found)[0] != "failed":
        raise _conflict(NOT_FAILED)
    ready = await readiness(session, person.id)
    if ready.sealed_key is None:
        raise _conflict(NO_WORKING_KEY)
    graph_input: InterviewState | None = None
    if found.snapshot.created_at is None:
        # The run failed before it saved a step, so there is nothing to go on
        # from: the interview starts afresh, from the text as checked now.
        if ready.resume_text is None:
            raise _conflict(NO_CHECKED_TEXT)
        shown = await profile_json(services.sessionmaker, person.id)
        graph_input = start_input(ready.resume_text, shown)
    turn = Turn(person.id, _new_run_id(), found.thread_id, ready.sealed_key, graph_input)
    await _claimed_run(session, runs, services, turn, found)
    return interview_answer(found, ready.missing, started=True)


@router.delete(
    "/interview",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **SIGN_IN_REQUIRED,
        **NO_INTERVIEW_ANSWER,
        409: {"model": Refused, "description": RUNNING},
    },
)
async def remove_interview(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Removes the interview and every step saved of it, unless a live run holds it."""
    removed = await session.scalar(
        delete(InterviewRow)
        .where(InterviewRow.person_id == person.id, unclaimed())
        .returning(InterviewRow.person_id)
    )
    if removed is None:
        held = await session.scalar(
            select(InterviewRow.person_id).where(InterviewRow.person_id == person.id)
        )
        raise _no_interview() if held is None else _conflict(RUNNING)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
