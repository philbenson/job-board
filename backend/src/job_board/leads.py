"""``GET /leads``: the open postings scored for the signed-in person, best first.

Invariant: a person sees only leads scored for them. Every row comes through
a score whose ``person_id`` is the signed-in person's.

Invariant: the order is total and stable. Best score first, then the order
scoring itself uses for the newest postings: newest published, undated ones
after every dated one, then newest first seen, then the highest id.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.models import Person, Posting, Score
from job_board.people import SIGN_IN_REQUIRED, current_person

# No index orders the leads: the sort runs over one person's scored rows,
# which the unique (person_id, posting_id) index finds, and scoring adds at
# most 25 of those a run. A page of 100 is four runs' worth of new ratings,
# with the best on top and the total saying how many more there are.
MAX_LEADS = 100


class Lead(BaseModel):
    """One open posting scored for the person: enough to judge it and follow the link."""

    posting_id: int
    title: str
    company: str  # the posting's company, or its board's token when the source names none
    location: str | None
    url: str
    published_at: datetime | None  # when the source first published it, if it says
    score: int = Field(ge=1, le=5)
    reason: str
    scored_at: datetime


class Leads(BaseModel):
    """A page of the person's leads, best first, and how many they have in all."""

    leads: list[Lead]
    total: int


router = APIRouter()


@router.get("/leads", responses=SIGN_IN_REQUIRED)
async def read_leads(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Leads:
    """The signed-in person's leads: open postings with a rating for them, best first."""
    # One statement for the page and the count, so the two always agree. The
    # window counts every row the filter keeps, before the limit cuts the page.
    rows = await session.execute(
        select(
            Posting.id.label("posting_id"),
            Posting.title,
            func.coalesce(Posting.company_name, Posting.board).label("company"),
            Posting.location,
            Posting.url,
            Posting.first_published_at.label("published_at"),
            Score.score,
            Score.reason,
            Score.scored_at,
            func.count().over().label("total"),
        )
        .join(Score, Score.posting_id == Posting.id)
        .where(
            Score.person_id == person.id,
            Score.outcome == "scored",
            Posting.closed_at.is_(None),
        )
        .order_by(
            Score.score.desc(),
            Posting.first_published_at.desc().nulls_last(),
            Posting.first_seen_at.desc(),
            Posting.id.desc(),
        )
        .limit(MAX_LEADS)
    )
    found = rows.all()
    return Leads(
        leads=[Lead.model_validate(row, from_attributes=True) for row in found],
        total=found[0].total if found else 0,
    )
