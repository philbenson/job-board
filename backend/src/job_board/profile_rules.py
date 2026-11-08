"""The rules every piece of text and every list in the profile keeps.

A text is trimmed of whitespace and invisible format characters at both ends,
then normalised to NFC, and every rule measures that form: an accented letter
counts as one character however it was typed, and the text is stored as the
person sees it. A list drops repeats that differ only in case or in how their
letters are composed, keeping the first spelling, and its cap counts what is
left. Each refusal's message is the rule alone, naming the kind of thing it is
about, so the person reads it as given and the answer quotes nothing sent.
"""

import unicodedata
from collections.abc import Callable, Hashable

from pydantic_core import PydanticCustomError

# A list may carry this many times its cap, counted before any item is checked,
# so a huge list is refused at once. Repeats are dropped after this count, so it
# sits well above the cap.
SENT_TIMES_CAP = 10

# The embeddings and overrides (U+202A to U+202E) and the isolates (U+2066 to
# U+2069), which reverse or reorder how the rest of a line shows.
DIRECTION_CONTROLS = frozenset(map(chr, [*range(0x202A, 0x202F), *range(0x2066, 0x206A)]))


def sent_limit(cap: int) -> int:
    """The most items a request may send for a list capped at ``cap``."""
    return SENT_TIMES_CAP * cap


def shows_something(character: str) -> bool:
    # Format characters (Cf: zero-width spaces, joiners) and combining marks
    # (Mn) show nothing on their own.
    return not character.isspace() and unicodedata.category(character) not in {"Cf", "Mn"}


def _trims_away(character: str) -> bool:
    # Whitespace and the invisible format characters (Cf: zero-width spaces,
    # joiners, byte order marks) at an end show nothing and join nothing.
    # Direction controls stay, to be refused: dropping one would change how
    # the rest of the text shows. Marks (Mn) stay too: a variation selector,
    # U+FE0F, ends many emoji.
    return character.isspace() or (
        unicodedata.category(character) == "Cf" and character not in DIRECTION_CONTROLS
    )


def trimmed(text: str) -> str:
    start, end = 0, len(text)
    while start < end and _trims_away(text[start]):
        start += 1
    while end > start and _trims_away(text[end - 1]):
        end -= 1
    return text[start:end]


def _kind(words: str) -> str:
    # "trade-off" names its refusals "trade_off_…", stable for a client to match on.
    return words.replace(" ", "_").replace("-", "_")


def checked_text(noun: str, max_length: int) -> Callable[[str], str]:
    """The check for one kind of text: ``noun`` names it with its article, "a skill"."""
    kind = _kind(noun.split(" ", 1)[1])  # without its article
    named = noun[0].upper() + noun[1:]

    def check(text: str) -> str:
        shown = unicodedata.normalize("NFC", trimmed(text))
        # Half of a surrogate pair is no character at all: JSON can spell one,
        # but no text encoding holds it, and the database would refuse the
        # document.
        if any(unicodedata.category(character) == "Cs" for character in shown):
            raise PydanticCustomError(f"{kind}_invalid_text", f"{named} must be valid text")
        if not any(shows_something(character) for character in shown):
            raise PydanticCustomError(f"{kind}_blank", f"{named} cannot be blank")
        if len(shown) > max_length:
            raise PydanticCustomError(
                f"{kind}_too_long", f"{named} can be at most {max_length} characters"
            )
        # Category Cc is the C0 and C1 controls and DEL: tabs, newlines, nulls
        # and the like, which break how a line of text shows.
        if any(unicodedata.category(character) == "Cc" for character in shown):
            raise PydanticCustomError(
                f"{kind}_control_character", f"{named} cannot contain control characters"
            )
        # Other format characters stay: a zero-width joiner inside a text binds
        # an emoji sequence.
        if not DIRECTION_CONTROLS.isdisjoint(shown):
            raise PydanticCustomError(
                f"{kind}_direction_control", f"{named} cannot contain text direction controls"
            )
        return shown

    return check


def fold(text: str) -> str:
    """The key two texts share when they differ only in case or composition."""
    # Folding case can decompose a composed letter again, so the key is
    # composed after folding.
    return unicodedata.normalize("NFC", text.casefold())


def distinct_and_capped[Item](
    plural: str, cap: int, key: Callable[[Item], Hashable]
) -> Callable[[list[Item]], list[Item]]:
    """The check for one kind of list: repeats by ``key`` dropped, then at most ``cap`` left."""

    def check(items: list[Item]) -> list[Item]:
        seen: set[Hashable] = set()
        distinct: list[Item] = []
        for item in items:
            folded = key(item)
            if folded not in seen:
                seen.add(folded)
                distinct.append(item)
        if len(distinct) > cap:
            raise PydanticCustomError(
                f"{_kind(plural)}_too_many",
                f"You can list at most {cap} {plural}",
            )
        return distinct

    return check
