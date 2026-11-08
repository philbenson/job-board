"""The rules a person's answer to the interviewer keeps.

An answer is the profile's kind of text over several lines: it is trimmed,
composed to NFC, must show something and has a cap, as a profile value does,
and it keeps a resume text's line rules. ``\\r\\n`` and a lone ``\\r`` become
``\\n``; line breaks and tabs stay; every other control character, every text
direction control and every half of a surrogate pair is refused. Each
refusal names its rule alone and quotes nothing of the answer.
"""

import unicodedata

from pydantic_core import PydanticCustomError

from job_board.profile_rules import DIRECTION_CONTROLS, shows_something, trimmed
from job_board.resumes.text_rules import is_refused_control, unified_line_breaks

# Room for an answer that covers several sections at once, and a bound on what
# one answer adds to every later request of the interview. It counts the
# answer as stored, after its line endings change.
MAX_ANSWER_LENGTH = 4000


def checked_answer(text: str) -> str:
    """The answer as it is stored, or the refusal of the first rule it breaks."""
    shown = unicodedata.normalize("NFC", trimmed(unified_line_breaks(text)))
    # Half of a surrogate pair is no character at all: JSON can spell one, but
    # no text encoding holds it, and the saver could not store the answer.
    if any(unicodedata.category(character) == "Cs" for character in shown):
        raise PydanticCustomError("answer_invalid_text", "An answer must be valid text")
    if not any(shows_something(character) for character in shown):
        raise PydanticCustomError("answer_blank", "An answer cannot be blank")
    if len(shown) > MAX_ANSWER_LENGTH:
        raise PydanticCustomError(
            "answer_too_long", f"An answer can be at most {MAX_ANSWER_LENGTH} characters"
        )
    if any(is_refused_control(character) for character in shown):
        raise PydanticCustomError(
            "answer_control_character",
            "An answer cannot contain control characters other than line breaks and tabs",
        )
    if not DIRECTION_CONTROLS.isdisjoint(shown):
        raise PydanticCustomError(
            "answer_direction_control", "An answer cannot contain text direction controls"
        )
    return shown
