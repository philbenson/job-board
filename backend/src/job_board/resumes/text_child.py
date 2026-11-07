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

from job_board.resumes.text_rules import MAX_RESUME_TEXT_LENGTH, Reading, cleaned, reading_of

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


def text_of(file: bytes) -> str:
    """The file's text, page by page, read no further than the page that runs past the cap."""
    from pypdf import PasswordType, PdfReader

    reader = PdfReader(io.BytesIO(file))
    # A file locked only against changes opens with the empty password; one
    # that needs a password to open cannot be read, and fails.
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise ValueError("the file needs a password")
    pages: list[str] = []
    text = ""
    for page in reader.pages:
        pages.append(page.extract_text(extraction_mode="plain"))
        text = cleaned(PAGES_APART.join(pages))
        if len(text) > MAX_RESUME_TEXT_LENGTH:
            break
    return text


def main(arguments: list[str]) -> int:
    cpu_seconds, address_space_bytes, largest_file_bytes = map(int, arguments)
    limited(cpu_seconds, address_space_bytes)
    file = sys.stdin.buffer.read(largest_file_bytes + 1)
    if len(file) > largest_file_bytes:
        return 1
    reading: Reading = reading_of(text_of(file))
    answer = json.dumps(
        {"state": reading.state, "text": reading.text}, ensure_ascii=False, separators=(",", ":")
    )
    sys.stdout.buffer.write(answer.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
