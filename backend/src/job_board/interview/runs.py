"""The interview's runs: each a task of the service's own, holding the interview's claim.

Invariant: every run ends with its claim released, recording why it failed
when it did, or abandoned to staleness when the process dies. A run whose
claim another run took over releases nothing, so it never writes over that
run's claim.

Invariant: a run that finished or failed leaves its thread one saved step,
the last, pruned while it still holds the claim, so each later request reads
the conversation once rather than once per step. A run cut off by shutdown or
taken over leaves its steps, and the next run to end prunes them.

Invariant: no log line, recorded failure or answer quotes the resume, an
answer, the profile or a reply. A failure is logged by its code, or by its
type's name when it is unexpected, since an error's text may quote the request.
"""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_board.interview.claims import release_claim, renew_claim
from job_board.interview.failures import (
    INTERVIEW_FAILURES,
    EmptyReply,
    InterviewFailure,
    LostClaim,
    ModelDeclined,
    ReplyCutOff,
)
from job_board.interview.graph import Context, InterviewGraph, InterviewState, thread_config
from job_board.interview.model import InterviewModelFactory
from job_board.model_errors import PROVIDER, failure_reason, mark_key_failure
from job_board.model_key.sealing import SealBroken, SealedUnderAnotherKey, open_sealed

logger = logging.getLogger(__name__)

# How long shutdown waits for the runs in flight before it cancels them: enough
# for a run between model calls to save its step, while a run waiting on the
# model is cut off, recorded as interrupted, and retried by the person.
SHUTDOWN_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class RunServices:
    """What every run reaches the world through."""

    graph: InterviewGraph = field(repr=False)
    saver: BaseCheckpointSaver[str] = field(repr=False)  # the graph's own, to prune its steps
    sessionmaker: async_sessionmaker[AsyncSession] = field(repr=False)
    service_key: bytes = field(repr=False)  # opens the person's sealed key
    model_factory: InterviewModelFactory = field(repr=False)


@dataclass(frozen=True)
class Turn:
    """One run of one person's interview, holding the claim ``run_id``."""

    person_id: int
    run_id: str
    thread_id: str
    sealed_key: bytes = field(repr=False)
    # The start's input, the person's answer, or None to go on from the last saved step.
    graph_input: InterviewState | Command[str] | None = field(repr=False)


class InterviewRuns:
    """The runs this process has started and not yet seen end, one registry per application."""

    def __init__(self, *, grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> None:
        self._grace_seconds = grace_seconds
        # Held here so a running task is never collected before it ends.
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, run: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(run)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def settle(self) -> None:
        """Waits for every run started so far to end."""
        if self._tasks:
            await asyncio.wait(set(self._tasks))

    async def stop(self) -> None:
        """Waits out the grace, then cancels every run still going and waits for them to end."""
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=self._grace_seconds)
        pending = set(self._tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def _stored(reason: str) -> InterviewFailure:
    """The interview's code for a reason ``failure_reason`` gives, without its details."""
    if reason.startswith("refused-"):
        return "refused"
    for code in INTERVIEW_FAILURES:
        if reason == code:
            return code
    return "unexpected"


def _failed(turn: Turn, code: InterviewFailure, reason: str | None = None) -> InterviewFailure:
    logger.warning("person %d: the interview's run failed: %s", turn.person_id, reason or code)
    return code


async def _run(services: RunServices, turn: Turn) -> InterviewFailure | None:
    try:
        key = open_sealed(
            turn.sealed_key, turn.person_id, PROVIDER, service_key=services.service_key
        )
    except SealedUnderAnotherKey:
        return _failed(turn, "not-sealed-here")
    except SealBroken:
        return _failed(turn, "unopenable")
    model = services.model_factory(key)
    del key
    context = Context(turn.person_id, turn.run_id, model, services.sessionmaker)
    try:
        await services.graph.ainvoke(
            turn.graph_input, thread_config(turn.thread_id), context=context
        )
    except anthropic.APIError as error:
        reason, key_failure = failure_reason(error)
        if key_failure is not None:
            await mark_key_failure(
                services.sessionmaker, turn.person_id, turn.sealed_key, key_failure
            )
        return _failed(turn, _stored(reason), reason)
    except (ReplyCutOff, ModelDeclined, EmptyReply) as error:
        return _failed(turn, error.code)
    return None


async def _prune(services: RunServices, turn: Turn) -> None:
    """Drops every step of the thread but the last, keeping that step's pending pause.

    A failure is logged and changes nothing else: the steps stay, and the next
    run to end prunes them.
    """
    try:
        # Renewed first, so the prune runs only while this run holds the claim
        # and never under a run that took it over.
        if await renew_claim(services.sessionmaker, turn.person_id, turn.run_id):
            await services.saver.aprune([turn.thread_id], strategy="keep_latest")
    except Exception as error:
        logger.warning(
            "person %d: could not prune the interview's steps: %s",
            turn.person_id,
            type(error).__name__,
        )


async def run_interview(services: RunServices, turn: Turn) -> None:
    """Runs the interview until it waits, ends or fails, prunes, then releases the claim.

    It raises only when cancelled, after recording the run as interrupted.
    """
    failure: InterviewFailure | None = None
    ended = False  # finished or failed, rather than cut off or taken over
    try:
        failure = await _run(services, turn)
        ended = True
    except LostClaim:
        logger.warning(
            "person %d: the interview's run lost its claim to another run and stopped",
            turn.person_id,
        )
    except asyncio.CancelledError:
        failure = "interrupted"
        logger.warning("person %d: the interview's run was cut off by shutdown", turn.person_id)
        raise
    except Exception as error:
        failure = _failed(turn, "unexpected", f"unexpected: {type(error).__name__}")
        ended = True
    finally:
        try:
            if ended:
                await _prune(services, turn)
        finally:  # a shutdown that cuts the prune off still releases, keeping the outcome
            try:
                await release_claim(services.sessionmaker, turn.person_id, turn.run_id, failure)
            except Exception as error:  # the claim goes stale, and the next run takes it over
                logger.warning(
                    "person %d: could not release the interview's claim: %s",
                    turn.person_id,
                    type(error).__name__,
                )
