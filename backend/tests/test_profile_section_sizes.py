"""Every section's largest body fits under the body cap, so a full section can always be saved.

Each body is built from the section's own limits: every list at its cap, every
text at its longest, in characters four bytes long in UTF-8, the widest any
character is. Raising a limit past what the body cap allows fails here.
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from profile_requests import Someone, client_for

from job_board.body_limit import LARGEST_BODY_BYTES
from job_board.profile_sections import (
    COMPANY_SIZES,
    DAYS_ON_SITE,
    MAX_APPLIED,
    MAX_CITY_LENGTH,
    MAX_COMPANY_LENGTH,
    MAX_GAP_LENGTH,
    MAX_GAPS,
    MAX_INDUSTRIES,
    MAX_INDUSTRY_LENGTH,
    MAX_LEADS_PER_DAY,
    MAX_NEARBY_TITLES,
    MAX_OFFICES,
    MAX_PAY_USD,
    MAX_RELOCATE_FOR,
    MAX_RULE_LENGTH,
    MAX_RULES,
    MAX_SKILL_LENGTH,
    MAX_SKILLS,
    MAX_TITLE_LENGTH,
    MAX_WATCHED,
    MAX_YEARS,
    TOP_SCORE,
    US_STATES,
)

# The first of a run of letters each four bytes in UTF-8, unchanged by folding
# case or composition, so every text below is kept exactly as sent.
FOUR_BYTE_LETTERS = 0x20000


def widest(n: int, length: int) -> str:
    """Text of ``length`` four-byte characters, different for each ``n``."""
    return chr(FOUR_BYTE_LETTERS + n) * length


def texts(cap: int, length: int) -> list[str]:
    return [widest(n, length) for n in range(cap)]


LARGEST = {
    "title range": (
        "/profile/title-range",
        "title_range",
        {"nearby_titles": texts(MAX_NEARBY_TITLES, MAX_TITLE_LENGTH), "lower_level_ok": False},
    ),
    "places": (
        "/profile/places",
        "places",
        {
            "remote_ok": False,
            "offices": [
                {"city": city, "days_a_week": DAYS_ON_SITE}
                for city in texts(MAX_OFFICES, MAX_CITY_LENGTH)
            ],
            "states": sorted(US_STATES),
            "will_relocate": False,
            "relocate_for": texts(MAX_RELOCATE_FOR, MAX_COMPANY_LENGTH),
        },
    ),
    "pay": ("/profile/pay", "pay", {"floor_usd": MAX_PAY_USD, "ask_usd": MAX_PAY_USD}),
    "skills": (
        "/profile/skills",
        "skills",
        {
            "skills": [
                {"name": name, "years": MAX_YEARS} for name in texts(MAX_SKILLS, MAX_SKILL_LENGTH)
            ]
        },
    ),
    "gaps": (
        "/profile/gaps",
        "gaps",
        {
            "apply_with": texts(MAX_GAPS, MAX_GAP_LENGTH),
            "trade_offs": texts(MAX_GAPS, MAX_GAP_LENGTH),
        },
    ),
    "deal-breakers": (
        "/profile/deal-breakers",
        "deal_breakers",
        {
            "industries": texts(MAX_INDUSTRIES, MAX_INDUSTRY_LENGTH),
            "company_sizes": list(COMPANY_SIZES),
            "no_agencies": False,
        },
    ),
    "companies": (
        "/profile/companies",
        "companies",
        {
            "watch": texts(MAX_WATCHED, MAX_COMPANY_LENGTH),
            "applied": [
                {"company": widest(n, MAX_COMPANY_LENGTH), "title": widest(n, MAX_TITLE_LENGTH)}
                for n in range(MAX_APPLIED)
            ],
        },
    ),
    "pace": (
        "/profile/pace",
        "pace",
        {"leads_per_day": MAX_LEADS_PER_DAY, "brief_from_score": TOP_SCORE},
    ),
    "own rules": ("/profile/own-rules", "own_rules", {"rules": texts(MAX_RULES, MAX_RULE_LENGTH)}),
}


@pytest.fixture
def someone(migrated_database_url: str) -> Iterator[Someone]:
    person = Someone(migrated_database_url)
    yield person
    person.remove()


@pytest.mark.parametrize(("path", "key", "body"), LARGEST.values(), ids=LARGEST.keys())
async def test_each_sections_largest_body_fits_under_the_body_cap_and_saves(
    someone: Someone, migrated_database_url: str, path: str, key: str, body: dict[str, Any]
) -> None:
    content = json.dumps(body, ensure_ascii=False).encode()

    assert len(content) < LARGEST_BODY_BYTES
    async with client_for(migrated_database_url) as client:
        response = await client.put(
            path, content=content, headers={**someone.headers, "Content-Type": "application/json"}
        )

    assert response.status_code == 200
    assert response.json()[key] == body
