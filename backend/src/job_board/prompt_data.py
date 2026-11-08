"""Text put between tags in a prompt, so that nothing inside can close or open a block.

Invariant: text from a person or a stranger cannot close or open one of the
prompt's blocks. Any of the blocks' tags inside it is broken first, in any
case or spacing, and however hidden by an invisible format character or
written in fullwidth forms. Text holding no such tag is sent as it was, byte
for byte.
"""

import re
import unicodedata
from collections.abc import Callable

_FORMAT = "Cf"  # the category of invisible format characters, such as a zero-width space


def _folded(text: str) -> tuple[str, list[int]]:
    """``text`` as a model might read it, and where each of its characters came from.

    Each character is put in its compatibility form, so fullwidth brackets and
    letters read as plain ones, and every format character is dropped, so none
    can hide a tag. The list gives each folded character's index in ``text``.
    """
    folded: list[str] = []
    origins: list[int] = []
    for index, character in enumerate(text):
        for part in unicodedata.normalize("NFKC", character):
            if unicodedata.category(part) != _FORMAT:
                folded.append(part)
                origins.append(index)
    return "".join(folded), origins


def tag_breaker(*names: str) -> Callable[[str], str]:
    """A function giving text with the opening bracket of every tag named here broken."""
    # A tag in any case or spacing, the way a model might still read one.
    tag = re.compile(rf"<\s*/?\s*(?:{'|'.join(map(re.escape, names))})\b", re.IGNORECASE)

    def as_data(text: str) -> str:
        folded, origins = _folded(text)
        brackets = {origins[found.start()] for found in tag.finditer(folded)}
        if not brackets:
            return text
        return "".join("&lt;" if index in brackets else c for index, c in enumerate(text))

    return as_data
