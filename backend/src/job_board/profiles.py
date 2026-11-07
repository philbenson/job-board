"""A person's profile: one document per person, written a section at a time.

The document grows by sections. Every section has a default, so a document
written before a section existed still reads, and reading ignores keys it does
not know, so a document written by newer code still reads in older code.
Requests are strict instead: a body with a key it does not name is refused.
"""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

MAX_TARGET_TITLES = 20  # enough to cover the variants of one search; more is a different search
MAX_TITLE_LENGTH = 100  # longer than any real job title, short enough to show on one line


class Profile(BaseModel):
    """The whole profile, as stored and as answered."""

    model_config = ConfigDict(extra="ignore")

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
