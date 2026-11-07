"""The bodies that replace one section of the profile each, and their rules.

Requests are strict: a body with a key its section does not name is refused,
and no value is converted to the type a field wants. Every field carries a
description written for the person filling in a form and for a language model
reading the model's schema as a tool's.
"""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

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


class Section(BaseModel):
    """What every section's body keeps: no key it does not name, and no value converted."""

    # Strict, so "100", 1.5 and true are refused where a whole number is
    # wanted, and a string where a list is. JSON strings still match a Literal.
    model_config = ConfigDict(extra="forbid", strict=True)


MAX_NEARBY_TITLES = 20  # the target titles' cap: the same kind of list, one step out

NearbyTitle = Annotated[str, AfterValidator(checked_text("a nearby title", MAX_TITLE_LENGTH))]


class TitleRange(Section):
    """How far from their target titles a person will look."""

    nearby_titles: Annotated[
        list[NearbyTitle],
        Field(
            max_length=sent_limit(MAX_NEARBY_TITLES),
            description=(
                "Job titles close to the target titles that are also worth seeing, each up to"
                f" {MAX_TITLE_LENGTH} characters; at most {MAX_NEARBY_TITLES}."
            ),
        ),
        AfterValidator(distinct_and_capped("nearby titles", MAX_NEARBY_TITLES, fold)),
    ]
    lower_level_ok: bool = Field(
        description="Whether a role one level below the target titles is fine."
    )


MAX_OFFICES = 20  # more cities than anyone commutes between
MAX_CITY_LENGTH = 100  # longer than any city's name
MAX_RELOCATE_FOR = 20  # a short list of exceptions, not a search
MAX_COMPANY_LENGTH = 100  # longer than any company's name
DAYS_ON_SITE = 5  # a full working week in the office

# The two-letter postal codes of the fifty states and the District of Columbia.
US_STATES = frozenset(
    {
        *("AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID"),
        *("IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO"),
        *("MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA"),
        *("RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"),
    }
)

City = Annotated[str, AfterValidator(checked_text("a city", MAX_CITY_LENGTH))]
CompanyName = Annotated[str, AfterValidator(checked_text("a company", MAX_COMPANY_LENGTH))]


def _checked_state(code: str) -> str:
    """The code in upper case, or the rule it breaks."""
    # Only ASCII: some other letters upper-case to ASCII ones, dotless i to I.
    upper = code.upper()
    if not code.isascii() or upper not in US_STATES:
        raise PydanticCustomError(
            "state_unknown", "A state must be the two-letter postal code of a US state or DC"
        )
    return upper


State = Annotated[str, AfterValidator(_checked_state)]


class Office(Section):
    """A city a person would go into an office in, and how often."""

    city: City = Field(
        description=f"The city's name as the person typed it, up to {MAX_CITY_LENGTH} characters."
    )
    days_a_week: int = Field(
        ge=1,
        le=DAYS_ON_SITE,
        description=(
            f"Days a week in the office, from 1 to {DAYS_ON_SITE}; {DAYS_ON_SITE} means on site."
        ),
    )


class Places(Section):
    """Where a person will work: remote, offices in named cities, US states, and moving."""

    remote_ok: bool = Field(description="Whether a fully remote role is fine.")
    offices: Annotated[
        list[Office],
        Field(
            max_length=sent_limit(MAX_OFFICES),
            description=(
                "Cities, as typed, where they would go into an office, and how many days a week;"
                f" at most {MAX_OFFICES}, one per city."
            ),
        ),
        AfterValidator(
            distinct_and_capped("offices", MAX_OFFICES, lambda office: fold(office.city))
        ),
    ]
    states: Annotated[
        list[State],
        Field(
            max_length=sent_limit(len(US_STATES)),
            description=(
                "US states they would work in, as two-letter postal codes, DC included;"
                " any case is taken and stored in upper case."
            ),
        ),
        AfterValidator(distinct_and_capped("states", len(US_STATES), fold)),
    ]
    will_relocate: bool = Field(description="Whether they would move for a role.")
    relocate_for: Annotated[
        list[CompanyName],
        Field(
            max_length=sent_limit(MAX_RELOCATE_FOR),
            description=(
                "Companies they would move for even though they would not move otherwise, each up"
                f" to {MAX_COMPANY_LENGTH} characters; at most {MAX_RELOCATE_FOR}, and empty when"
                " they would move anyway."
            ),
        ),
        AfterValidator(distinct_and_capped("companies", MAX_RELOCATE_FOR, fold)),
    ]

    @field_validator("relocate_for")
    @classmethod
    def _only_when_not_moving_anyway(cls, companies: list[str], info: ValidationInfo) -> list[str]:
        # will_relocate is checked first, being declared first; when it was
        # refused it is missing here, and that refusal is the one answered.
        if companies and info.data.get("will_relocate") is True:
            raise PydanticCustomError(
                "relocate_for_while_relocating",
                "List companies you would move for only if you would not move otherwise",
            )
        return companies


MAX_PAY_USD = 10_000_000  # far above any salary; a typo with extra zeros is refused


class Pay(Section):
    """What a person will be paid: annual base pay in whole US dollars, before bonus or equity."""

    floor_usd: int = Field(
        ge=0,
        le=MAX_PAY_USD,
        description="The lowest annual base pay, in whole US dollars, they would take.",
    )
    ask_usd: int = Field(
        ge=0,
        le=MAX_PAY_USD,
        description="The annual base pay, in whole US dollars, they ask for; at least the floor.",
    )

    @field_validator("ask_usd")
    @classmethod
    def _not_below_the_floor(cls, ask: int, info: ValidationInfo) -> int:
        # The floor is checked first, being declared first; when it was
        # refused it is missing here, and that refusal is the one answered.
        floor = info.data.get("floor_usd")
        if floor is not None and ask < floor:
            raise PydanticCustomError("ask_below_floor", "The ask cannot be below the floor")
        return ask
