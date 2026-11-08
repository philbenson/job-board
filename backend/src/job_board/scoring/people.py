"""Who is scored, and which postings each person's next batch rates.

A person is scored when they have an Anthropic key with no recorded failure
and at least one target title. No profile, a profile without titles and an
empty list of titles all mean no titles. A person scored is rated against their
whole profile.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Row, Select, and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.model_errors import PROVIDER
from job_board.models import ModelKey, Person, Posting, ProfileRow, Score
from job_board.profiles import Profile, stored_profile

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    person_id: int
    # The person's own words, kept out of every repr and so out of every traceback.
    profile: Profile = field(repr=False)
    # Sealed, so it says nothing without the service key; kept out of the repr regardless.
    sealed_key: bytes = field(repr=False)


def _with_a_working_key() -> Select[int, bytes, dict[str, Any] | None]:
    return (
        select(Person.id, ModelKey.sealed_key, ProfileRow.document)
        .join(
            ModelKey,
            and_(
                ModelKey.person_id == Person.id,
                ModelKey.provider == PROVIDER,
                ModelKey.failure.is_(None),
            ),
        )
        .outerjoin(ProfileRow, ProfileRow.person_id == Person.id)
        .order_by(Person.id)
    )


def _profile(person_id: int, document: dict[str, Any] | None) -> Profile | None:
    if document is None:
        return None
    try:
        return stored_profile(document)
    except ValidationError:
        # The error would quote the document, so it names the person alone.
        log.warning("person %d: profile unreadable, not scored", person_id)
        return None


def _candidate(row: Row[int, bytes, dict[str, Any] | None]) -> Candidate | None:
    person_id, sealed_key, document = row
    profile = _profile(person_id, document)
    if profile is None or not profile.target_titles:
        return None
    return Candidate(person_id, profile, sealed_key)


async def eligible_people(session: AsyncSession) -> list[int]:
    """Everyone to score, in order of id."""
    rows = await session.execute(_with_a_working_key())
    return [found.person_id for row in rows if (found := _candidate(row)) is not None]


async def candidate(session: AsyncSession, person_id: int) -> Candidate | None:
    """This person, if they are still to be scored."""
    row = (await session.execute(_with_a_working_key().where(Person.id == person_id))).first()
    return None if row is None else _candidate(row)


async def unscored_postings(
    session: AsyncSession, person_id: int, limit: int
) -> Sequence[Row[int, str, str | None, str | None, str | None]]:
    """The newest open postings this person has no score for, at most ``limit``.

    Newest by when the source first published them; postings without that date
    come after every dated one. Ties fall to the newest first seen, then the
    highest id, so the order is total and a batch never depends on chance.
    """
    scored = exists().where(Score.person_id == person_id, Score.posting_id == Posting.id)
    rows = await session.execute(
        select(
            Posting.id, Posting.title, Posting.company_name, Posting.location, Posting.content_html
        )
        .where(Posting.closed_at.is_(None), ~scored)
        .order_by(
            Posting.first_published_at.desc().nulls_last(),
            Posting.first_seen_at.desc(),
            Posting.id.desc(),
        )
        .limit(limit)
    )
    return rows.all()
