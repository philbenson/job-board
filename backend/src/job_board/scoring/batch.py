"""One person's batch: up to BATCH_SIZE postings rated on that person's own key.

Invariants:

- One batch per person at a time: a batch holds the person's advisory lock,
  LOCK_CLASS and their id, on a connection kept for the batch. A batch that
  finds it held skips the person; that is not a failure. Two-key locks never
  collide with one-key ones, and the fetcher's take another first key.
- A batch whose lock's connection has closed has lost the lock, and another
  run may hold the person now: it stops before recording anything more.
- No transaction is open while the model answers. The lock's connection runs
  without one, the postings are read in one short transaction before the
  first request, and each result is written in its own afterwards.
- The opened key lives in this module's locals and the model built from it,
  for one batch. It is never logged, raised, stored or passed anywhere else.
  A failure is logged by its kind alone, since an error's text may quote the
  request.
- A posting is rated once: each result is a row, unreadable replies included,
  and a failed request writes nothing, leaving the posting for the next run.
"""

import logging
from dataclasses import dataclass
from typing import Literal

import anthropic
from sqlalchemy import func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from job_board.model_key.failure import KeyFailure
from job_board.model_key.sealing import SealBroken, SealedUnderAnotherKey, open_sealed, sealed_with
from job_board.models import ModelKey, Score
from job_board.scoring.graph import rate
from job_board.scoring.model import SCORING_MODEL, ModelFactory, Rating
from job_board.scoring.people import PROVIDER, candidate, eligible_people, unscored_postings
from job_board.scoring.posting_text import posting_text

BATCH_SIZE = 25  # postings rated per person per run, which bounds what one run costs them
# The first key of every lock scoring takes, the person's id the second. Its bytes spell "SCOR".
LOCK_CLASS = 0x53434F52

log = logging.getLogger(__name__)

type End = Literal["finished", "locked", "skipped", "stopped"]


@dataclass(frozen=True)
class BatchResult:
    """How one person's batch went.

    ``finished``: every posting found was rated. ``locked``: another run holds
    the person. ``skipped``: nothing to do with this key here, such as a key
    sealed under another service key. ``stopped``: a failure, named by
    ``reason``, ended the batch early.
    """

    person_id: int
    rated: int
    unreadable: int
    end: End
    reason: str | None = None

    @property
    def failed(self) -> bool:
        return self.end == "stopped"


@dataclass
class _Tally:
    rated: int = 0
    unreadable: int = 0


class _Stopped(Exception):
    def __init__(self, reason: str, end: End = "stopped") -> None:
        super().__init__(reason)
        self.reason = reason
        self.end: End = end


def _why(error: anthropic.APIError) -> tuple[str, KeyFailure | None]:
    """The reason a failed request stops the batch, and what it says of the key."""
    if isinstance(error, anthropic.APITimeoutError):  # a kind of connection error
        return "timed-out", None
    if isinstance(error, anthropic.APIConnectionError):
        return "connection-error", None
    if not isinstance(error, anthropic.APIStatusError):
        return f"unexpected: {type(error).__name__}", None
    status = error.status_code
    if status == 401:
        return "rejected", "rejected"
    if status in (403, 404):  # 404: the key's account cannot see this model
        return "not-permitted", "not-permitted"
    if status == 402:  # the SDK has no class of its own for it
        return "no-credit", "no-credit"
    if status == 408:
        return "timed-out", None
    if status == 429:
        return "rate-limited", None
    if status >= 500:
        return "server-error", None
    return f"refused-{status}", None


async def _record(
    sessionmaker: async_sessionmaker[AsyncSession],
    person_id: int,
    posting_id: int,
    rating: Rating | None,
) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(
            insert(Score)
            .values(
                person_id=person_id,
                posting_id=posting_id,
                outcome="unreadable" if rating is None else "scored",
                score=None if rating is None else rating.score,
                reason=None if rating is None else rating.reason,
                model=SCORING_MODEL,
            )
            .on_conflict_do_nothing(index_elements=["person_id", "posting_id"])
        )


async def _mark(
    sessionmaker: async_sessionmaker[AsyncSession],
    person_id: int,
    sealed_key: bytes,
    failure: KeyFailure,
) -> None:
    """Record the key's failure, unless the person has saved another key meanwhile."""
    async with sessionmaker() as session, session.begin():
        await session.execute(
            update(ModelKey)
            .where(
                ModelKey.person_id == person_id,
                ModelKey.provider == PROVIDER,
                ModelKey.sealed_key == sealed_key,
                ModelKey.failure.is_(None),
            )
            .values(failure=failure, failed_at=func.now())
        )


async def _still_locked(lock: AsyncConnection) -> bool:
    """Whether the lock's connection still answers, and so still holds the session lock."""
    try:
        await lock.scalar(select(literal(1)))
    except Exception:  # a closed connection fails in the driver's own way
        return False
    return True


async def _unlock(lock: AsyncConnection, person_id: int) -> None:
    try:
        await lock.scalar(select(func.pg_advisory_unlock(LOCK_CLASS, person_id)))
    except Exception as error:  # a lost connection took the lock with it
        log.warning("person %d: could not let go of the lock: %s", person_id, type(error).__name__)


async def _rate_batch(
    lock: AsyncConnection,
    sessionmaker: async_sessionmaker[AsyncSession],
    person_id: int,
    tally: _Tally,
    *,
    service_key: bytes,
    model_factory: ModelFactory,
) -> None:
    async with sessionmaker() as session, session.begin():
        found = await candidate(session, person_id)
        postings = [] if found is None else await unscored_postings(session, person_id, BATCH_SIZE)
    if found is None:  # the key or the titles went since the run listed this person
        raise _Stopped("no-longer-eligible", end="skipped")
    if not sealed_with(found.sealed_key, service_key=service_key):
        # Sealed under another service key, or too short to name one: not ours to open.
        raise _Stopped("not-sealed-with-this-service-key", end="skipped")
    if not postings:
        return
    try:
        key = open_sealed(found.sealed_key, person_id, PROVIDER, service_key=service_key)
    except SealedUnderAnotherKey:
        raise _Stopped("not-sealed-with-this-service-key", end="skipped") from None
    except SealBroken:
        raise _Stopped("unopenable") from None
    model = model_factory(key)
    del key

    for posting_id, title, company_name, location, content_html in postings:
        text = posting_text(
            title=title, company_name=company_name, location=location, content_html=content_html
        )
        try:
            rating = await rate(model, found.titles, text)
        except anthropic.APIError as error:
            reason, failure = _why(error)
            if failure is not None:
                await _mark(sessionmaker, person_id, found.sealed_key, failure)
            raise _Stopped(reason) from None
        if not await _still_locked(lock):
            raise _Stopped("lost-the-lock")
        await _record(sessionmaker, person_id, posting_id, rating)
        if rating is None:
            tally.unreadable += 1
        else:
            tally.rated += 1


def _logged(result: BatchResult) -> BatchResult:
    end = result.end if result.reason is None else f"{result.end}: {result.reason}"
    log.log(
        logging.WARNING if result.failed else logging.INFO,
        "person %d: %d rated, %d unreadable, %s",
        result.person_id,
        result.rated,
        result.unreadable,
        end,
    )
    return result


async def score_person(
    engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    person_id: int,
    *,
    service_key: bytes,
    model_factory: ModelFactory,
) -> BatchResult:
    """Rate up to BATCH_SIZE of this person's unscored open postings, and log how it went."""
    async with engine.connect() as connection:
        lock = await connection.execution_options(isolation_level="AUTOCOMMIT")
        if not await lock.scalar(select(func.pg_try_advisory_lock(LOCK_CLASS, person_id))):
            return _logged(BatchResult(person_id, 0, 0, "locked"))
        tally = _Tally()
        try:
            await _rate_batch(
                lock,
                sessionmaker,
                person_id,
                tally,
                service_key=service_key,
                model_factory=model_factory,
            )
        except _Stopped as stopped:
            result = BatchResult(
                person_id, tally.rated, tally.unreadable, stopped.end, stopped.reason
            )
        except Exception as error:  # named by kind only: its text may quote the key
            result = BatchResult(
                person_id,
                tally.rated,
                tally.unreadable,
                "stopped",
                f"unexpected: {type(error).__name__}",
            )
        else:
            result = BatchResult(person_id, tally.rated, tally.unreadable, "finished")
        finally:
            await _unlock(lock, person_id)
    return _logged(result)


async def score_everyone(
    engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    service_key: bytes,
    model_factory: ModelFactory,
) -> list[BatchResult]:
    """One batch for each person to be scored, in order of id."""
    async with sessionmaker() as session:
        people = await eligible_people(session)
    return [
        await score_person(
            engine, sessionmaker, person, service_key=service_key, model_factory=model_factory
        )
        for person in people
    ]
