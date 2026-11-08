"""Reads a resume's text, in a process of its own, under limits it sets first.

Run as ``python -I -m job_board.resumes.text_child <processor seconds>
<address-space bytes> <largest file bytes>`` with the file on standard input
and an empty environment. It caps its processor time and, where the system
allows, its address space, and only then imports the PDF library, so nothing
the library does runs without them. It writes one JSON object,
``{"state": ..., "text": ...}``, and exits 0. Anything that goes wrong exits
non-zero with nothing written; the parent treats that, and any answer it
cannot check, as a reading that failed.

This module imports the standard library and the text's rules alone: the
process holds the file and nothing that reaches the database or the secrets.
"""

import contextlib
import io
import json
import resource
import sys

from job_board.resumes.text_rules import (
    MAX_RESUME_PAGES,
    MAX_RESUME_TEXT_LENGTH,
    Reading,
    cleaned,
    cleaned_page,
    reading_of,
)

PAGES_APART = "\n\n"


def limited(cpu_seconds: int, address_space_bytes: int) -> None:
    """Cap this process's processor time and, where the system allows, its address space.

    Past the soft processor limit the system sends SIGXCPU, which ends the
    process; the hard limit a second later ends it with SIGKILL. macOS refuses
    an address-space limit, so there only the processor limit and the
    parent's wall clock hold.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (address_space_bytes, address_space_bytes))


def text_of(file: bytes) -> tuple[str, bool]:
    """The file's text, cleaned, and whether pages were left unread.

    It reads at most ``MAX_RESUME_PAGES`` pages, and no further than the page
    that takes the text past the length cap. Each page is cleaned once, and
    the whole only once the pages are long enough to pass the cap, so a file
    of many pages costs the cleaning no more than one page of its length.
    """
    from pypdf import PasswordType, PdfReader

    reader = PdfReader(io.BytesIO(file))
    # A file locked only against changes opens with the empty password; one
    # that needs a password to open cannot be read, and fails.
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise ValueError("the file needs a password")
    pages: list[str] = []
    length = -len(PAGES_APART)  # the pages read so far and the breaks between them
    for number, page in enumerate(reader.pages):
        if number == MAX_RESUME_PAGES:
            return cleaned(PAGES_APART.join(pages)), True
        pages.append(cleaned_page(page.extract_text(extraction_mode="plain")))
        length += len(PAGES_APART) + len(pages[-1])
        # The cleaned text is never longer than this, and can be shorter, so
        # only its own length says it is past the cap and the reading stops.
        if length > MAX_RESUME_TEXT_LENGTH:
            text = cleaned(PAGES_APART.join(pages))
            if len(text) > MAX_RESUME_TEXT_LENGTH:
                return text, number + 1 < len(reader.pages)
    return cleaned(PAGES_APART.join(pages)), False


def main(arguments: list[str]) -> int:
    cpu_seconds, address_space_bytes, largest_file_bytes = map(int, arguments)
    limited(cpu_seconds, address_space_bytes)
    file = sys.stdin.buffer.read(largest_file_bytes + 1)
    if len(file) > largest_file_bytes:
        return 1
    text, pages_unread = text_of(file)
    reading: Reading = reading_of(text, pages_unread=pages_unread)
    answer = json.dumps(
        {"state": reading.state, "text": reading.text}, ensure_ascii=False, separators=(",", ":")
    )
    sys.stdout.buffer.write(answer.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
