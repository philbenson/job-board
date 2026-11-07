"""The text of one posting as the model reads it.

A posting's description arrives as HTML. The model gets its words only: tags
gone, entities decoded, scripts and styles dropped with their contents, and
whitespace collapsed to single spaces. The description is then cut, so one
long posting costs no more than any other.
"""

from html.parser import HTMLParser

MAX_DESCRIPTION_CHARACTERS = 6000  # a long posting's substance, at a bounded cost
NOT_GIVEN = "not given"

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


def posting_text(
    *, title: str, company_name: str | None, location: str | None, content_html: str | None
) -> str:
    """The posting's title, company, location and description, one to a line."""
    description = plain_text(content_html) if content_html else ""
    return "\n".join(
        [
            f"Title: {' '.join(title.split())}",
            f"Company: {' '.join(company_name.split()) if company_name else NOT_GIVEN}",
            f"Location: {' '.join(location.split()) if location else NOT_GIVEN}",
            f"Description: {description or NOT_GIVEN}",
        ]
    )
