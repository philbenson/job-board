"""The claim a run holds on an interview: every statement that takes, renews or releases it.

Invariant: one run at a time per person. A run holds the interview while its
row names the run's id; the run renews the claim around each model call, so
a claim older than ``STALE_AFTER`` belongs to a run that stopped without
releasing it, and the next run may take it over. The run that lost it finds
out at its next renewal and stops.
"""

from datetime import timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_board.interview.failures import InterviewFailure
from job_board.models import Checkpoint, InterviewRow

# Longer than the model's timeout and a tool step's few statements together,
# the most a live run goes between two renewals.
STALE_AFTER = timedelta(minutes=10)


def live_claim() -> ColumnElement[bool]:
    """True for an interview a run holds and has renewed within ``STALE_AFTER``."""
    return and_(
        InterviewRow.run_id.is_not(None), InterviewRow.running_since > func.now() - STALE_AFTER
    )


def unclaimed() -> ColumnElement[bool]:
    """True for an interview no live run holds: no claim, or one gone stale."""
    # Spelled out rather than as the negation of live_claim: with no claim the
    # comparison is null, and a negated null matches no row.
    return or_(
        InterviewRow.run_id.is_(None), InterviewRow.running_since <= func.now() - STALE_AFTER
    )


def _last_step() -> ColumnElement[str | None]:
    """The id of the interview's thread's last saved step, the one its snapshot reads."""
    return (
        select(Checkpoint.checkpoint_id)
        .where(Checkpoint.thread_id == InterviewRow.thread_id, Checkpoint.checkpoint_ns == "")
        .order_by(Checkpoint.checkpoint_id.desc())
        .limit(1)
        .scalar_subquery()
    )


async def claim(session: AsyncSession, person_id: int, run_id: str, seen_step: str | None) -> bool:
    """Gives the interview to ``run_id`` unless a live run holds it, clearing the last failure.

    ``seen_step`` is the id of the last saved step the caller read, None when
    it read none: the claim is taken only while that step is still the last,
    so a turn that ran and ended between the caller's read and its claim
    refuses the claim rather than letting an answer meant for one question
    resume the next. The caller commits.
    """
    claimed = await session.scalar(
        update(InterviewRow)
        .where(
            InterviewRow.person_id == person_id,
            unclaimed(),
            _last_step().is_not_distinct_from(seen_step),
        )
        .values(run_id=run_id, running_since=func.now(), failure=None)
        .returning(InterviewRow.person_id)
    )
    return claimed is not None


async def renew_claim(
    sessionmaker: async_sessionmaker[AsyncSession], person_id: int, run_id: str
) -> bool:
    """Renews ``run_id``'s claim; False when another run has taken it over."""
    async with sessionmaker() as session, session.begin():
        renewed = await session.scalar(
            update(InterviewRow)
            .where(InterviewRow.person_id == person_id, InterviewRow.run_id == run_id)
            .values(running_since=func.now())
            .returning(InterviewRow.person_id)
        )
    return renewed is not None


async def release_claim(
    sessionmaker: async_sessionmaker[AsyncSession],
    person_id: int,
    run_id: str,
    failure: InterviewFailure | None,
) -> None:
    """Ends ``run_id``'s claim, recording ``failure``.

    A run that lost its claim, or whose interview was deleted, records nothing.
    """
    async with sessionmaker() as session, session.begin():
        await session.execute(
            update(InterviewRow)
            .where(InterviewRow.person_id == person_id, InterviewRow.run_id == run_id)
            .values(run_id=None, running_since=None, failure=failure)
        )
