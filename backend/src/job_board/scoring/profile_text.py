"""The person's profile as the model reads it: a heading per section, a fact per line.

Invariant: the model reads every saved section but pace, and nothing
unanswered. Pace says how many leads to show, not whether a posting fits, so it
is never read. A section nobody has saved is left out, as is an empty list and
a section left with nothing to say, so no empty answer reads as a rule.

Saved text holds no control character, but a Unicode line or paragraph
separator passes; every item is put on one line, so a person's text cannot
start a line that reads as another fact or a heading.
"""

from collections.abc import Callable, Sequence

from job_board.profile_sections import (
    DAYS_ON_SITE,
    Companies,
    DealBreakers,
    Gaps,
    Office,
    OwnRules,
    Pay,
    Places,
    Skills,
    TitleRange,
)
from job_board.profiles import Profile


def _items(items: Sequence[str]) -> list[str]:
    return [f"- {' '.join(item.splitlines())}" for item in items]


def _listed(lead: str, items: Sequence[str]) -> list[str]:
    """``lead`` and its items, one to a line; nothing at all when there are none."""
    return [lead, *_items(items)] if items else []


def _fine(ok: bool) -> str:
    return "is fine" if ok else "is not wanted"


def _counted(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


def _office(office: Office) -> str:
    days = (
        "on site"
        if office.days_a_week == DAYS_ON_SITE
        else f"{_counted(office.days_a_week, 'day')} a week"
    )
    return f"{office.city}, {days}"


def _title_range(section: TitleRange) -> list[str]:
    return [
        *_listed("Nearby titles also worth seeing:", section.nearby_titles),
        f"A role one level below the target titles {_fine(section.lower_level_ok)}.",
    ]


def _places(section: Places) -> list[str]:
    return [
        f"A fully remote role {_fine(section.remote_ok)}.",
        *_listed(
            "Cities where they would go into an office:",
            [_office(office) for office in section.offices],
        ),
        *_listed("US states they can work from:", section.states),
        "They would move for a role."
        if section.will_relocate
        else "They would not move for a role.",
        *_listed(
            "Companies they would move for even though they would not move otherwise:",
            section.relocate_for,
        ),
    ]


def _pay(section: Pay) -> list[str]:
    return [
        f"The lowest they would take: ${section.floor_usd:,}",
        f"What they ask for: ${section.ask_usd:,}",
    ]


def _skills(section: Skills) -> list[str]:
    return _items(
        [
            f"{skill.name}, {_counted(skill.years, 'year') if skill.years else 'under a year'}"
            for skill in section.skills
        ]
    )


def _gaps(section: Gaps) -> list[str]:
    return [
        *_listed("Requirements they lack but would still apply without:", section.apply_with),
        *_listed("What they would give up for the right role:", section.trade_offs),
    ]


def _deal_breakers(section: DealBreakers) -> list[str]:
    # Agencies being fine is no deal-breaker, so it says nothing here.
    agencies = ["A posting from a recruiting agency, not the employer, is ruled out."]
    return [
        *_listed("Industries they will not work in:", section.industries),
        *_listed(
            "Company sizes they will not work at:",
            [f"{size} employees" for size in section.company_sizes],
        ),
        *(agencies if section.no_agencies else []),
    ]


def _companies(section: Companies) -> list[str]:
    return [
        *_listed("Companies whose postings they want to see:", section.watch),
        *_listed(
            "Jobs they have already applied to:",
            [f"{job.title} at {job.company}" for job in section.applied],
        ),
    ]


def _own_rules(section: OwnRules) -> list[str]:
    return _items(section.rules)


def _facts[S](section: S | None, render: Callable[[S], list[str]]) -> list[str]:
    return [] if section is None else render(section)


def profile_text(profile: Profile) -> str:
    """The profile's saved sections as plain text, a blank line between sections."""
    sections = [
        ("Job titles they are looking for:", _items(profile.target_titles)),
        (
            "How far from their target titles they will look:",
            _facts(profile.title_range, _title_range),
        ),
        ("Where they will work:", _facts(profile.places, _places)),
        (
            "Pay, as annual base pay in whole US dollars before bonus or equity:",
            _facts(profile.pay, _pay),
        ),
        ("Skills they bring, with whole years of using each:", _facts(profile.skills, _skills)),
        ("Where they fall short of a posting and would still apply:", _facts(profile.gaps, _gaps)),
        (
            "Deal-breakers, each of which rules a posting out whatever else it offers:",
            _facts(profile.deal_breakers, _deal_breakers),
        ),
        (
            "Companies they keep an eye on, and jobs they have already applied to:",
            _facts(profile.companies, _companies),
        ),
        (
            "Their own rules, in their own words, which settle close calls:",
            _facts(profile.own_rules, _own_rules),
        ),
    ]
    return "\n\n".join("\n".join([heading, *facts]) for heading, facts in sections if facts)
