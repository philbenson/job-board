from job_board.scoring.posting_text import (
    MAX_DESCRIPTION_CHARACTERS,
    MAX_FIELD_CHARACTERS,
    MAX_POSTING_TEXT_CHARACTERS,
    plain_text,
    posting_text,
)

MEGABYTE = 1024 * 1024


def test_drops_the_tags_and_keeps_the_words_apart_across_blocks() -> None:
    html = (
        "<h2>About</h2><p>We build <strong>boards</strong>.</p><ul><li>Python</li><li>Go</li></ul>"
    )
    assert plain_text(html) == "About We build boards. Python Go"


def test_decodes_entities() -> None:
    assert plain_text("<p>Salt &amp; pepper &lt;3 caf&eacute; &#8212; &#x41;</p>") == (
        "Salt & pepper <3 café — A"
    )


def test_drops_scripts_and_styles_with_their_contents() -> None:
    html = (
        "<style>p { color: red }</style><p>Kept</p>"
        "<script>alert('dropped')</script><SCRIPT type='x'>also dropped</SCRIPT> and this"
    )
    assert plain_text(html) == "Kept and this"


def test_collapses_whitespace() -> None:
    assert plain_text("  one\n\n\ttwo  <br>  three&nbsp; four ") == "one two three four"


def test_cuts_the_description_to_its_limit() -> None:
    long = "<p>" + "word " * MAX_DESCRIPTION_CHARACTERS + "</p>"
    text = plain_text(long)
    assert len(text) == MAX_DESCRIPTION_CHARACTERS
    assert text.startswith("word word")


def test_gives_the_title_company_location_and_description() -> None:
    text = posting_text(
        title="Staff Engineer",
        company_name="Example Co",
        location="Remote",
        content_html="<p>Build things.</p>",
    )
    assert text == (
        "Title: Staff Engineer\nCompany: Example Co\nLocation: Remote\nDescription: Build things."
    )


def test_says_what_the_source_left_out() -> None:
    text = posting_text(title="Engineer", company_name=None, location=None, content_html=None)
    assert text == (
        "Title: Engineer\nCompany: not given\nLocation: not given\nDescription: not given"
    )


def test_keeps_words_apart_where_a_block_or_a_break_opens() -> None:
    assert plain_text("one<br>two<br/>three<div>four</div>five") == "one two three four five"


def test_cuts_the_title_company_and_location_so_the_whole_text_has_a_bound() -> None:
    text = posting_text(
        title="t" * MEGABYTE,
        company_name="c" * MEGABYTE,
        location="l" * MEGABYTE,
        content_html="<p>" + "d" * MEGABYTE + "</p>",
    )
    assert len(text) == MAX_POSTING_TEXT_CHARACTERS
    title, company, location, _ = text.split("\n")
    assert title == "Title: " + "t" * MAX_FIELD_CHARACTERS
    assert company == "Company: " + "c" * MAX_FIELD_CHARACTERS
    assert location == "Location: " + "l" * MAX_FIELD_CHARACTERS


def test_bounds_the_text_of_a_megabyte_title_alone() -> None:
    text = posting_text(title="t" * MEGABYTE, company_name=None, location=None, content_html=None)
    assert len(text) < MAX_POSTING_TEXT_CHARACTERS
