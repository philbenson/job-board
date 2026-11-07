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

import unicodedata
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError
from sqlalchemy import Text, func, literal, select
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.me import Refused
from job_board.models import Person, ProfileRow
from job_board.people import current_person

MAX_TARGET_TITLES = 20  # enough to cover the variants of one search; more is a different search
MAX_TITLE_LENGTH = 100  # longer than any real job title, short enough to show on one line


class Profile(BaseModel):
    """The whole profile, as stored and as answered."""

    # Every section is always in the answer, so the description marks it
    # required there even though a stored document may lack it.
    model_config = ConfigDict(extra="ignore", json_schema_serialization_defaults_required=True)

    target_titles: list[str] = Field(default_factory=list)


def _checked_title(title: str) -> str:
    """The title with its surrounding whitespace trimmed, or the rule it breaks.

    Each refusal's message is the rule alone, so the person reads it as given.
    """
    trimmed = title.strip()
    if not trimmed:
        raise PydanticCustomError("target_title_blank", "A target title cannot be blank")
    if len(trimmed) > MAX_TITLE_LENGTH:
        raise PydanticCustomError(
            "target_title_too_long",
            f"A target title can be at most {MAX_TITLE_LENGTH} characters",
        )
    # Category Cc is the C0 and C1 controls and DEL: tabs, newlines, nulls and
    # the like, which have no place inside a title and break how it shows.
    if any(unicodedata.category(character) == "Cc" for character in trimmed):
        raise PydanticCustomError(
            "target_title_control_character",
            "A target title cannot contain control characters",
        )
    return trimmed


def _distinct_and_capped(titles: list[str]) -> list[str]:
    """The titles without repeats, in the order given, or a refusal past the cap.

    A repeat differs from an earlier title only in case and is dropped rather
    than refused; the first spelling stays. The cap counts what is left.
    """
    seen: set[str] = set()
    distinct: list[str] = []
    for title in titles:
        key = title.casefold()
        if key not in seen:
            seen.add(key)
            distinct.append(title)
    if len(distinct) > MAX_TARGET_TITLES:
        raise PydanticCustomError(
            "target_titles_too_many",
            f"You can list at most {MAX_TARGET_TITLES} target titles",
        )
    return distinct


TargetTitle = Annotated[str, AfterValidator(_checked_title)]


class TargetTitles(BaseModel):
    """The body that replaces the target titles. An empty list means none chosen."""

    model_config = ConfigDict(extra="forbid")

    titles: Annotated[list[TargetTitle], AfterValidator(_distinct_and_capped)]


router = APIRouter()

SIGN_IN_REQUIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": Refused, "description": "No valid session token"}
}


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


@router.put("/profile/target-titles", responses=SIGN_IN_REQUIRED)
async def save_target_titles(
    body: TargetTitles,
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profile:
    """Replaces the signed-in person's target titles and answers the profile as stored."""
    section = "target_titles"  # the Profile field this route owns
    new_row = insert(ProfileRow).values(person_id=person.id, document={section: body.titles})
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
