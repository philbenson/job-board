"""A person's profile: one document per person, written a section at a time.

The document grows by sections. Every section has a default, so a document
written before a section existed still reads, and reading ignores keys it does
not know, so a document written by newer code still reads in older code.
Requests are strict instead: a body with a key it does not name is refused.

Invariant: a write changes only its own section, and only in the signed-in
person's row. It sets that one key inside the stored document in the database,
in the same statement that adds the row when there is none, so a section
written by another route, or by newer code, survives it untouched.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Text, func, literal, select
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.models import Person, ProfileRow
from job_board.people import SIGN_IN_REQUIRED, current_person
from job_board.profile_sections import (
    MAX_SENT_TITLES,
    MAX_TARGET_TITLES,
    MAX_TITLE_LENGTH,
    TargetTitles,
)

__all__ = [
    "MAX_SENT_TITLES",
    "MAX_TARGET_TITLES",
    "MAX_TITLE_LENGTH",
    "Profile",
    "TargetTitles",
    "router",
]


class Profile(BaseModel):
    """The whole profile, as stored and as answered."""

    # Every section is always in the answer, so the description marks it
    # required there even though a stored document may lack it.
    model_config = ConfigDict(extra="ignore", json_schema_serialization_defaults_required=True)

    target_titles: list[str] = Field(default_factory=list)


router = APIRouter()

# Without a valid sign-in, a request whose body is well-formed JSON, of any
# shape, gets the one 401, before its body is checked against the model. A
# body that is not JSON at all is refused first, with the app's 422, because
# FastAPI decodes the body before any dependency runs; that answer names the
# decoding error and where it is, and says nothing of the person or the token.


@router.get("/profile", responses=SIGN_IN_REQUIRED)
async def read_profile(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profile:
    """The signed-in person's profile; an empty one, written nowhere, before their first save."""
    document = await session.scalar(
        select(ProfileRow.document).where(ProfileRow.person_id == person.id)
    )
    return Profile() if document is None else Profile.model_validate(document)


async def _save_section(
    session: AsyncSession, person: Person, section: str, value: object
) -> Profile:
    """Sets one section of the person's stored document and answers the profile as stored.

    ``section`` is the Profile field the caller owns and ``value`` its JSON form.
    """
    new_row = insert(ProfileRow).values(person_id=person.id, document={section: value})
    # One statement, so two saves at once cannot interleave a read and a write:
    # the row is added holding only this section, or the stored document gets
    # this one key set with jsonb_set and keeps every other key it holds.
    save = new_row.on_conflict_do_update(
        index_elements=[ProfileRow.person_id],
        set_={
            ProfileRow.document: func.jsonb_set(
                ProfileRow.document,
                literal([section], ARRAY(Text)),
                new_row.excluded.document[section],
            ),
            ProfileRow.updated_at: func.now(),
        },
    ).returning(ProfileRow.document)
    document = await session.scalar(save)
    await session.commit()
    return Profile.model_validate(document)


@router.put("/profile/target-titles", responses=SIGN_IN_REQUIRED)
async def save_target_titles(
    body: TargetTitles,
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profile:
    """Replaces the signed-in person's target titles and answers the profile as stored."""
    return await _save_section(session, person, "target_titles", body.titles)
