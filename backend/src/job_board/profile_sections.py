"""The bodies that replace one section of the profile each, and their rules.

Requests are strict: a body with a key its section does not name is refused.
"""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from job_board.profile_rules import checked_text, distinct_and_capped, fold, sent_limit

MAX_TARGET_TITLES = 20  # enough to cover the variants of one search; more is a different search
MAX_TITLE_LENGTH = 100  # longer than any real job title, short enough to show on one line
MAX_SENT_TITLES = sent_limit(MAX_TARGET_TITLES)

TargetTitle = Annotated[str, AfterValidator(checked_text("a target title", MAX_TITLE_LENGTH))]


class TargetTitles(BaseModel):
    """The body that replaces the target titles. An empty list means none chosen."""

    model_config = ConfigDict(extra="forbid")

    titles: Annotated[
        list[TargetTitle],
        Field(max_length=MAX_SENT_TITLES),
        AfterValidator(distinct_and_capped("target titles", MAX_TARGET_TITLES, fold)),
    ]
