"""The rules a resume's text keeps, whether read from the file or saved by the person.

Reading and saving share one cleaning, so a text read from a file always
passes a save unchanged, and the person can save back what they were shown.
The cleaning runs in an order that makes a second pass change nothing:

1. ``\\r\\n``, then a lone ``\\r``, become ``\\n``.
2. The refused characters go: every control except the line break and the
   tab, every text direction control, and every half of a surrogate pair. A
   reading drops them; a save is refused for them.
3. The text is composed to NFC, so a letter dropped characters had split
   joins up again.
4. Spaces and tabs at the end of each line go.
5. Three or more line breaks in a row become two.
6. The whole is trimmed of whitespace and invisible format characters at its
   ends, the profile's trim.

This module is imported by the reading's own process, so it imports the
standard library and the profile's rules alone, and nothing of the web
framework, the database or the settings.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic_core import PydanticCustomError

from job_board.profile_rules import DIRECTION_CONTROLS, shows_something, trimmed

MAX_RESUME_TEXT_LENGTH = 15_000  # twice a dense two-page resume; the table checks the same bound
# A resume has a handful of pages; the cap bounds what a crafted file of
# thousands costs the reading, since each page costs it some processor time.
MAX_RESUME_PAGES = 50
FEWEST_LETTERS = 50  # fewer than a short paragraph: page numbers and stray marks, not a resume

type ReadState = Literal["found", "cut", "none_found", "failed"]

LINE_ENDS = re.compile(r"[ \t]+$", re.MULTILINE)
BLANK_RUNS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Reading:
    """What reading a file gave: text for ``found`` and ``cut``, and none otherwise."""

    state: ReadState
    text: str | None


def _line_breaks(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_control(character: str) -> bool:
    # Category Cc is the C0 and C1 controls and DEL. Line breaks and tabs lay
    # out a resume; the rest break how a line shows.
    return unicodedata.category(character) == "Cc" and character not in "\n\t"


def _is_refused(character: str) -> bool:
    return (
        _is_control(character)
        or unicodedata.category(character) == "Cs"
        or character in DIRECTION_CONTROLS
    )


def _laid_out(text: str) -> str:
    """Rules 3 to 5, for a text that holds no refused character."""
    composed = unicodedata.normalize("NFC", text)
    return BLANK_RUNS.sub("\n\n", LINE_ENDS.sub("", composed))


def _after_the_refused(text: str) -> str:
    """Rules 3 to 6, for a text that holds no refused character."""
    return trimmed(_laid_out(text))


def cleaned_page(text: str) -> str:
    """A page of a longer text as rules 1 to 5 leave it: every rule but the trim.

    A page's ends are not the text's, so they keep what the trim would take.
    Pages cleaned so and joined by line breaks, then cleaned whole, give the
    text that cleaning the pages joined raw gives: no rule reaches across a
    line break, and the whole's cleaning only joins up blank lines where pages
    meet and trims the ends, so it is never longer than the pages and the
    line breaks between them.
    """
    kept = "".join(character for character in _line_breaks(text) if not _is_refused(character))
    return _laid_out(kept)


def cleaned(text: str) -> str:
    """The text as every rule above leaves it, with the refused characters dropped."""
    return trimmed(cleaned_page(text))


def checked_resume_text(text: str) -> str:
    """The text a person saves, cleaned, or the refusal of the first rule it breaks.

    Each refusal names its rule alone and quotes nothing of the text.
    """
    text = _line_breaks(text)
    # Half of a surrogate pair is no character at all: JSON can spell one,
    # but no text encoding holds it, and the database would refuse the text.
    if any(unicodedata.category(character) == "Cs" for character in text):
        raise PydanticCustomError("resume_text_invalid_text", "The resume text must be valid text")
    if any(_is_control(character) for character in text):
        raise PydanticCustomError(
            "resume_text_control_character",
            "The resume text cannot contain control characters other than line breaks and tabs",
        )
    if not DIRECTION_CONTROLS.isdisjoint(text):
        raise PydanticCustomError(
            "resume_text_direction_control",
            "The resume text cannot contain text direction controls",
        )
    shown = _after_the_refused(text)
    if not any(shows_something(character) for character in shown):
        raise PydanticCustomError("resume_text_blank", "The resume text cannot be blank")
    if len(shown) > MAX_RESUME_TEXT_LENGTH:
        raise PydanticCustomError(
            "resume_text_too_long",
            f"The resume text can be at most {MAX_RESUME_TEXT_LENGTH:,} characters",
        )
    return shown


def reading_of(text: str, *, pages_unread: bool = False) -> Reading:
    """What a cleaned text read from a file gives.

    Over the cap, it keeps the first ``MAX_RESUME_TEXT_LENGTH`` characters,
    cleaned again so the cut ends trimmed. A file with pages left unread, past
    ``MAX_RESUME_PAGES``, is cut too, its text kept whole.
    Letters are counted in what is kept, so a reading that gives text gives
    some a save takes.
    """
    too_long = len(text) > MAX_RESUME_TEXT_LENGTH
    kept = cleaned(text[:MAX_RESUME_TEXT_LENGTH]) if too_long else text
    if sum(character.isalpha() for character in kept) < FEWEST_LETTERS:
        return Reading("none_found", None)
    return Reading("cut" if too_long or pages_unread else "found", kept)
