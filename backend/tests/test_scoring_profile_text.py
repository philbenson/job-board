"""The person's profile as the model reads it: every saved section but pace, in order."""

from typing import Any

import pytest

from job_board.profiles import stored_profile
from job_board.scoring.profile_text import profile_text

TITLES = ["Staff Engineer", "Platform Lead"]
FULL: dict[str, Any] = {
    "target_titles": TITLES,
    "title_range": {"nearby_titles": ["Principal Engineer"], "lower_level_ok": True},
    "places": {
        "remote_ok": True,
        "offices": [
            {"city": "Boston", "days_a_week": 3},
            {"city": "Denver", "days_a_week": 5},
            {"city": "Austin", "days_a_week": 1},
        ],
        "states": ["ma", "CO"],
        "will_relocate": False,
        "relocate_for": ["Example Co"],
    },
    "pay": {"floor_usd": 150000, "ask_usd": 1250000},
    "skills": {
        "skills": [
            {"name": "Python", "years": 12},
            {"name": "Go", "years": 1},
            {"name": "Rust", "years": 0},
        ]
    },
    "gaps": {
        "apply_with": ["No Kubernetes in production"],
        "trade_offs": ["A smaller title for a stronger team"],
    },
    "deal_breakers": {
        "industries": ["Gambling"],
        "company_sizes": ["1-10", "10001+"],
        "no_agencies": True,
    },
    "companies": {
        "watch": ["Example Labs"],
        "applied": [{"company": "Example Co", "title": "Staff Engineer"}],
    },
    "pace": {"leads_per_day": 10, "brief_from_score": 4},
    "own_rules": {"rules": ["No on-call rotation more often than one week in six."]},
}

TITLES_TEXT = """\
Job titles they are looking for:
- Staff Engineer
- Platform Lead"""

FULL_TEXT = f"""\
{TITLES_TEXT}

How far from their target titles they will look:
Nearby titles also worth seeing:
- Principal Engineer
A role one level below the target titles is fine.

Where they will work:
A fully remote role is fine.
Cities where they would go into an office:
- Boston, 3 days a week
- Denver, on site
- Austin, 1 day a week
US states they can work from:
- MA
- CO
They would not move for a role.
Companies they would move for even though they would not move otherwise:
- Example Co

Pay, as annual base pay in whole US dollars before bonus or equity:
The lowest they would take: $150,000
What they ask for: $1,250,000

Skills they bring, with whole years of using each:
- Python, 12 years
- Go, 1 year
- Rust, under a year

Where they fall short of a posting and would still apply:
Requirements they lack but would still apply without:
- No Kubernetes in production
What they would give up for the right role:
- A smaller title for a stronger team

Deal-breakers, each of which rules a posting out whatever else it offers:
Industries they will not work in:
- Gambling
Company sizes they will not work at:
- 1-10 employees
- 10001+ employees
A posting from a recruiting agency, not the employer, is ruled out.

Companies they keep an eye on, and jobs they have already applied to:
Companies whose postings they want to see:
- Example Labs
Jobs they have already applied to:
- Staff Engineer at Example Co

Their own rules, in their own words, which settle close calls:
- No on-call rotation more often than one week in six."""


def rendered(document: dict[str, Any]) -> str:
    return profile_text(stored_profile(document))


def test_renders_every_saved_section_but_pace_in_the_profiles_order() -> None:
    assert rendered(FULL) == FULL_TEXT


@pytest.mark.parametrize(
    ("section", "heading"),
    [
        ("title_range", "How far"),
        ("places", "Where they will work"),
        ("pay", "Pay,"),
        ("skills", "Skills"),
        ("gaps", "Where they fall short"),
        ("deal_breakers", "Deal-breakers"),
        ("companies", "Companies they keep"),
        ("own_rules", "Their own rules"),
    ],
)
def test_leaves_out_a_section_nobody_has_saved(section: str, heading: str) -> None:
    unsaved = {key: value for key, value in FULL.items() if key != section}
    kept = [block for block in FULL_TEXT.split("\n\n") if not block.startswith(heading)]
    assert len(kept) == len(FULL_TEXT.split("\n\n")) - 1
    assert rendered(unsaved) == "\n\n".join(kept)


def test_gives_only_the_titles_when_only_the_titles_and_pace_are_saved() -> None:
    assert rendered({"target_titles": TITLES, "pace": FULL["pace"]}) == TITLES_TEXT


def test_leaves_out_a_section_left_with_nothing_to_say() -> None:
    empty = {
        "target_titles": TITLES,
        "skills": {"skills": []},
        "gaps": {"apply_with": [], "trade_offs": []},
        "deal_breakers": {"industries": [], "company_sizes": [], "no_agencies": False},
        "companies": {"watch": [], "applied": []},
        "own_rules": {"rules": []},
    }
    assert rendered(empty) == TITLES_TEXT
    assert rendered({**empty, "target_titles": []}) == ""


def test_leaves_out_an_empty_list_and_keeps_the_rest_of_its_section() -> None:
    document = {
        "target_titles": TITLES,
        "title_range": {"nearby_titles": [], "lower_level_ok": False},
        "places": {
            "remote_ok": False,
            "offices": [],
            "states": [],
            "will_relocate": True,
            "relocate_for": [],
        },
        "gaps": {"apply_with": [], "trade_offs": ["A longer commute"]},
    }
    assert rendered(document) == (
        f"{TITLES_TEXT}\n\n"
        "How far from their target titles they will look:\n"
        "A role one level below the target titles is not wanted.\n\n"
        "Where they will work:\n"
        "A fully remote role is not wanted.\n"
        "They would move for a role.\n\n"
        "Where they fall short of a posting and would still apply:\n"
        "What they would give up for the right role:\n"
        "- A longer commute"
    )


def test_puts_an_item_holding_a_line_or_paragraph_separator_on_one_line() -> None:
    document = {
        "target_titles": ["Staff\u2028Engineer"],
        "places": {
            "remote_ok": True,
            "offices": [{"city": "New\u2029York", "days_a_week": 2}],
            "states": [],
            "will_relocate": True,
            "relocate_for": [],
        },
        "own_rules": {"rules": ["First line.\u2028\u2028Then another."]},
    }
    text = rendered(document)
    assert "- Staff Engineer\n" in text
    assert "- New York, 2 days a week\n" in text
    assert text.endswith("- First line.  Then another.")
