"""A prompt block's tags written so plain matching misses them, and text read as a model might."""

import unicodedata
from collections.abc import Iterator

import pytest

# Invisible format characters a board's HTML entities or a saved profile can carry.
HIDDEN = {
    "zero-width-space": "\u200b",
    "soft-hyphen": "\u00ad",
    "word-joiner": "\u2060",
    "byte-order-mark": "\ufeff",
}


def fullwidth(text: str) -> str:
    return "".join(chr(ord(character) + 0xFEE0) for character in text)


def hidden_tags(*names: str) -> Iterator[object]:
    """Each named block's tags, opening and closing, written so plain matching misses them."""
    for name in names:
        for slash in ("", "/"):
            side = "closing" if slash else "opening"
            for kind, mark in HIDDEN.items():
                tag = f"<{slash}{name[:3]}{mark}{name[3:]}>"
                yield pytest.param(tag, id=f"{side}-{name}-{kind}")
            yield pytest.param(f"\uff1c{slash}{name}\uff1e", id=f"{side}-{name}-fullwidth-brackets")
            yield pytest.param(f"<{slash}{fullwidth(name)}>", id=f"{side}-{name}-fullwidth-letters")


def as_a_model_might_read(text: str) -> str:
    """``text`` with fullwidth forms made plain and invisible format characters gone."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(character for character in folded if unicodedata.category(character) != "Cf")
