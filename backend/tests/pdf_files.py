"""PDF files built for the tests, from raw objects, holding only invented text.

Each text page draws its lines in Helvetica, one ``Tj`` a line, top to bottom,
the way a word processor stores a single column.
"""

import io
import zlib

from pypdf import PdfReader, PdfWriter

BOMB_BYTES = 100 * 1024 * 1024  # past pypdf's own cap on what one stream may inflate to


def _stream(data: bytes, dictionary: bytes = b"") -> bytes:
    return b"<< /Length %d %s>>\nstream\n" % (len(data), dictionary) + data + b"\nendstream"


def _file(objects: list[bytes]) -> bytes:
    """A PDF of ``objects``, numbered from 1, the first of them the catalog."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    table = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % table
    return bytes(out)


def _drawn(lines: list[str]) -> bytes:
    def escaped(line: str) -> bytes:
        return (
            line.encode("latin-1")
            .replace(b"\\", b"\\\\")
            .replace(b"(", b"\\(")
            .replace(b")", b"\\)")
        )

    shown = b"".join(b"(%s) Tj 0 -14 Td\n" % escaped(line) for line in lines)
    return b"BT\n/F1 11 Tf 14 TL 50 780 Td\n" + shown + b"ET"


def _bomb() -> bytes:
    """A Flate stream of zeros that inflates to ``BOMB_BYTES``, built without holding them."""
    squeeze = zlib.compressobj(9)
    megabyte = bytes(1024 * 1024)
    deflated = b"".join(squeeze.compress(megabyte) for _ in range(BOMB_BYTES // len(megabyte)))
    return deflated + squeeze.flush()


def pdf(*pages: list[str] | bytes) -> bytes:
    """One page for each of ``pages``: lines of text, or a page's raw content stream."""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, written once its pages are numbered
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        _stream(
            b"\x80",
            b"/Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceGray /BitsPerComponent 8 ",
        ),
    ]
    kids = []
    for page in pages:
        content = _stream(_drawn(page)) if isinstance(page, list) else page
        objects.append(content)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> >>" % len(objects)
        )
        kids.append(b"%d 0 R" % len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(kids), len(kids))
    return _file(objects)


def image_page() -> bytes:
    """A page's content that paints one image and draws no text, as a scanned page does."""
    return _stream(b"q 612 0 0 792 0 0 cm /Im1 Do Q")


def costly_page() -> bytes:
    """A page's content stream of 640,000 text moves, under 5 MiB, that pypdf
    spends seconds of processor time walking and finds no text in."""
    return _stream(b"BT /F1 11 Tf 50 780 Td\n" + b"0 0 Td\n" * 640_000 + b"ET")


def bomb_page() -> bytes:
    """A page's content stream that inflates past pypdf's cap."""
    return _stream(_bomb(), b"/Filter /FlateDecode ")


def encrypted(file: bytes, user_password: str) -> bytes:
    """``file`` encrypted with AES under an owner password and ``user_password``."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(file)))
    writer.encrypt(user_password=user_password, owner_password="owner-only", algorithm="AES-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def resume_lines() -> list[str]:
    return [
        "Avery Example",
        "avery@example.com  555-0142",
        "Experience",
        "Staff Engineer, Example Widgets, 2021 to now",
        "Led the move of the ordering system to a queue of small services.",
        "Education",
        "BSc Computer Science, Example State University",
    ]
