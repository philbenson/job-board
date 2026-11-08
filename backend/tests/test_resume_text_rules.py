import unicodedata

import pytest
from pydantic_core import PydanticCustomError

from job_board.resumes.text_rules import (
    MAX_RESUME_TEXT_LENGTH,
    Reading,
    checked_resume_text,
    cleaned,
    reading_of,
)

# Enough letters to count as text read; reading_of wants at least fifty.
WORDS = "Ada Lovelace wrote the first published program for an engine of numbers"
CHARACTER_REFUSALS = {
    "resume_text_invalid_text",
    "resume_text_control_character",
    "resume_text_direction_control",
}


def refusal(text: str) -> tuple[str, str]:
    with pytest.raises(PydanticCustomError) as raised:
        checked_resume_text(text)
    return raised.value.type, raised.value.message()


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("one\r\ntwo\rthree", "one\ntwo\nthree"),
        ("one\r\r\ntwo", "one\n\ntwo"),
        ("a\x00b\x07c\x7fd\x85e\x9ff", "abcdef"),
        ("left‮right⁦mid⁩", "leftrightmid"),
        ("half\ud800pair\udfff", "halfpair"),
        ("tab\tand\nline", "tab\tand\nline"),
        ("Café", "Café"),
        ("e\x00́", "é"),
        ("Cafe\u202e\u0301", "Caf\u00e9"),
        ("Cafe\x07\u0301", "Caf\u00e9"),
        ("end of line \t\nnext", "end of line\nnext"),
        ("one\n\n\n\ntwo", "one\n\ntwo"),
        ("one\n \n\t\n \ntwo", "one\n\ntwo"),
        ("one\n\ntwo", "one\n\ntwo"),
        ("​﻿ \n\t text ​\n", "text"),
        ("in​side", "in​side"),
    ],
    ids=[
        "line breaks",
        "a lone return before a pair",
        "controls",
        "direction controls",
        "halves of surrogate pairs",
        "tabs and line breaks stay",
        "composed",
        "composed once a dropped character goes",
        "composed once a dropped direction control goes",
        "composed once a dropped control goes",
        "spaces and tabs at line ends",
        "runs of blank lines",
        "lines of only spaces",
        "one blank line stays",
        "trimmed at both ends",
        "a format character inside stays",
    ],
)
def test_each_rule_cleans_the_text(raw: str, clean: str) -> None:
    assert cleaned(raw) == clean


@pytest.mark.parametrize(
    "raw",
    [
        "e\x00́ and a‮̈",
        "́ starts with a mark",
        "a\rb\r",
        "x\t\n\ty\t\n\t",
        "le⁧ft",
        "x ​",
        "a \n \n \n b ​ \n\n\n",
        "\r\n\r\n\r\n",
        "😀 split pair",
        "Å and क़ change under composition",
    ],
)
def test_cleaning_twice_changes_nothing_more(raw: str) -> None:
    once = cleaned(raw)
    assert cleaned(once) == once


def test_an_extraction_drops_exactly_the_characters_a_save_refuses() -> None:
    candidates = [*map(chr, range(0x3000)), *map(chr, range(0xD800, 0xE000)), "﻿", "\U0001f600"]
    for character in candidates:
        # Digits around it, which compose with no mark, so only a drop removes it.
        sent = f"12{character}34"
        dropped = cleaned(sent) == "1234"
        try:
            checked_resume_text(sent)
            refused = False
        except PydanticCustomError as error:
            refused = error.type in CHARACTER_REFUSALS
        assert dropped == refused, f"U+{ord(character):04X}"


@pytest.mark.parametrize(
    ("text", "kind", "message"),
    [
        (f"{WORDS}\ud800", "resume_text_invalid_text", "The resume text must be valid text"),
        (
            f"{WORDS}\x00",
            "resume_text_control_character",
            "The resume text cannot contain control characters other than line breaks and tabs",
        ),
        (
            f"{WORDS}‮",
            "resume_text_direction_control",
            "The resume text cannot contain text direction controls",
        ),
        (" ​\n\t́ ", "resume_text_blank", "The resume text cannot be blank"),
        (
            "x" * (MAX_RESUME_TEXT_LENGTH + 1),
            "resume_text_too_long",
            "The resume text can be at most 15,000 characters",
        ),
    ],
    ids=["not text", "a control", "a direction control", "blank", "too long"],
)
def test_a_save_names_the_rule_it_breaks_and_quotes_nothing(
    text: str, kind: str, message: str
) -> None:
    assert refusal(text) == (kind, message)


def test_a_save_is_cleaned_and_measured_once_cleaned() -> None:
    assert checked_resume_text("  one\r\ntwo  \n\n\n\nthree \t") == "one\ntwo\n\nthree"
    longest = "x" * MAX_RESUME_TEXT_LENGTH
    assert checked_resume_text(longest + " " * 100) == longest
    decomposed = "é" * MAX_RESUME_TEXT_LENGTH
    assert checked_resume_text(decomposed) == "é" * MAX_RESUME_TEXT_LENGTH


def test_text_with_fewer_than_fifty_letters_is_none_found() -> None:
    forty_nine = "ab " * 24 + "c"
    assert reading_of(cleaned(forty_nine)) == Reading("none_found", None)
    assert reading_of("1") == Reading("none_found", None)
    assert reading_of("") == Reading("none_found", None)
    fifty = forty_nine + "d"
    assert reading_of(fifty) == Reading("found", fifty)


def test_text_over_the_cap_is_cut_to_it_and_trimmed_again() -> None:
    # Every word is five characters and a space, so the cut lands on a space.
    text = cleaned("words " * 3000)

    reading = reading_of(text)

    assert reading.state == "cut"
    assert reading.text is not None
    assert len(reading.text) == MAX_RESUME_TEXT_LENGTH - 1
    assert reading.text == text[: MAX_RESUME_TEXT_LENGTH - 1]
    assert cleaned(reading.text) == reading.text


def test_a_cut_with_too_few_letters_left_is_none_found() -> None:
    text = "1" * MAX_RESUME_TEXT_LENGTH + " " + WORDS
    assert reading_of(text) == Reading("none_found", None)


def test_a_reading_always_passes_the_save_unchanged() -> None:
    raw = f"‮{WORDS}\r\n\x00é \t\n\n\n\n" * 400
    reading = reading_of(cleaned(raw))
    assert reading.text is not None
    assert checked_resume_text(reading.text) == reading.text
    assert unicodedata.is_normalized("NFC", reading.text)
