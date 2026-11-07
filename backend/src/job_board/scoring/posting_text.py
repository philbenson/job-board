"""The text of one posting as the model reads it.

A posting's description arrives as HTML. The model gets its words only: tags
gone, entities decoded, scripts and styles dropped with their contents, and
whitespace collapsed to single spaces. Every field is cut, the description at
its own length and the title, company and location at a shorter one, so the
whole text never passes MAX_POSTING_TEXT_CHARACTERS and one long posting costs
no more than any other.
"""

from html.parser import HTMLParser

MAX_DESCRIPTION_CHARACTERS = 6000  # a long posting's substance, at a bounded cost
MAX_FIELD_CHARACTERS = 300  # a title, company or location; far past any real one
NOT_GIVEN = "not given"
_LABELS = ("Title: ", "Company: ", "Location: ", "Description: ")
# The labels, three fields, the description and the line breaks between them.
MAX_POSTING_TEXT_CHARACTERS = (
    sum(map(len, _LABELS)) + 3 * MAX_FIELD_CHARACTERS + MAX_DESCRIPTION_CHARACTERS + 3
)

# Elements whose contents are never words a reader sees.
_HIDDEN = frozenset({"script", "style", "template", "noscript"})
# Elements that start a new block, so the words either side stay apart.
_BLOCKS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header",
        "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "td", "th",
        "tr", "ul",
    }
)  # fmt: skip


class _Words(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self._hidden_depth += 1
        elif tag in _BLOCKS:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        elif tag in _BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def plain_text(html: str) -> str:
    """The words of an HTML description on one line, cut at the limit."""
    words = _Words()
    words.feed(html)
    words.close()
    return " ".join("".join(words.parts).split())[:MAX_DESCRIPTION_CHARACTERS]


def _field(value: str | None) -> str:
    return " ".join(value.split())[:MAX_FIELD_CHARACTERS] if value else ""


def posting_text(
    *, title: str, company_name: str | None, location: str | None, content_html: str | None
) -> str:
    """The posting's title, company, location and description, one to a line, each cut."""
    fields = (
        _field(title),
        _field(company_name),
        _field(location),
        plain_text(content_html) if content_html else "",
    )
    return "\n".join(
        f"{label}{value or NOT_GIVEN}" for label, value in zip(_LABELS, fields, strict=True)
    )
