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
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from job_board.model_errors import PROVIDER, failure_reason, mark_key_failure
from job_board.model_key.sealing import SealBroken, SealedUnderAnotherKey, open_sealed, sealed_with
from job_board.models import Score
from job_board.scoring.graph import rate
from job_board.scoring.model import SCORING_MODEL, ModelFactory, Rating
from job_board.scoring.people import candidate, eligible_people, unscored_postings
from job_board.scoring.posting_text import posting_text
from job_board.scoring.profile_text import profile_text

BATCH_SIZE = 25  # postings rated per person per run, which bounds what one run costs them
# The first key of every lock scoring takes, the person's id the second. Its bytes spell "SCOR".
LOCK_CLASS = 0x53434F52
# A key sealed under another service key: the operator's to fix, since no key here will open.
NOT_SEALED_HERE = "not-sealed-with-this-service-key"

log = logging.getLogger(__name__)

type End = Literal["finished", "locked", "skipped", "stopped"]


@dataclass(frozen=True)
class BatchResult:
    """How one person's batch went.

    ``finished``: every posting found was rated. ``locked``: another run holds
    the person. ``skipped``: nothing to do with this key here, such as a key
    sealed under another service key. ``stopped``: a failure, named by
    ``reason``, ended the batch early, and the run exits 1.
    """

    person_id: int
    rated: int
    unreadable: int
    end: End
    reason: str | None = None

    @property
    def failed(self) -> bool:
        return self.end == "stopped"

    @property
    def sealed_elsewhere(self) -> bool:
        return self.reason == NOT_SEALED_HERE


@dataclass
class _Tally:
    rated: int = 0
    unreadable: int = 0


class _Stopped(Exception):
    def __init__(self, reason: str, end: End = "stopped") -> None:
        super().__init__(reason)
        self.reason = reason
        self.end: End = end


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
        raise _Stopped(NOT_SEALED_HERE, end="skipped")
    if not postings:
        return
    try:
        key = open_sealed(found.sealed_key, person_id, PROVIDER, service_key=service_key)
    except SealedUnderAnotherKey:
        raise _Stopped(NOT_SEALED_HERE, end="skipped") from None
    except SealBroken:
        raise _Stopped("unopenable") from None
    model = model_factory(key)
    del key

    # Rendered once, from the profile read above, so every posting in the batch
    # is sent the same system block and all but the first can read it cached.
    profile = profile_text(found.profile)
    for posting_id, title, company_name, location, content_html in postings:
        text = posting_text(
            title=title, company_name=company_name, location=location, content_html=content_html
        )
        try:
            rating = await rate(model, profile, text)
        except anthropic.APIError as error:
            reason, failure = failure_reason(error)
            if failure is not None:
                await mark_key_failure(sessionmaker, person_id, found.sealed_key, failure)
            raise _Stopped(reason) from None
        if rating == "cut-off":
            # One line each, quoting nothing: the sign that MAX_TOKENS is too low.
            log.warning(
                "person %d, posting %d: reply cut off at the token limit", person_id, posting_id
            )
        if not await _still_locked(lock):
            raise _Stopped("lost-the-lock")
        scored = rating if isinstance(rating, Rating) else None
        await _record(sessionmaker, person_id, posting_id, scored)
        if scored is None:
            tally.unreadable += 1
        else:
            tally.rated += 1


def _logged(result: BatchResult) -> BatchResult:
    end = result.end if result.reason is None else f"{result.end}: {result.reason}"
    log.log(
        logging.WARNING if result.failed or result.sealed_elsewhere else logging.INFO,
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
