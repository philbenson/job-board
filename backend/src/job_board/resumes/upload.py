"""Reading an uploaded resume: the raw PDF as the request body, checked as it arrives.

Invariant: no more of a body is read than its checks need. The media type and
the declared length are checked before any of it is read, a length over the
cap is refused unread, and reading stops at the first chunk that runs past the
declared length or once the first five bytes show the body is not a PDF. The
body cap in front of the app passes this one route through unread, so this is
its cap; the route checks the sign-in before it calls here.
"""

from fastapi import HTTPException, Request, status
from starlette.requests import ClientDisconnect

MAX_RESUME_BYTES = 5 * 1024 * 1024  # longer than any resume; the table checks the same bound
PDF_SIGNATURE = b"%PDF-"  # how every PDF file starts

SEND_A_PDF = "Send the resume as a PDF"
NOT_A_PDF = "That file is not a PDF"
SEND_THE_LENGTH = "Send the file's length"
TOO_LARGE = "A resume can be at most 5 MB"
LONGER_THAN_DECLARED = "The file is longer than its declared length"
ENDED_EARLY = "The file ended before its declared length"


def refused(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def declared_length(request: Request) -> int:
    """The body's declared length, after the checks that need no byte of it."""
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != "application/pdf":
        raise refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, SEND_A_PDF)
    declared = request.headers.get("content-length", "")
    if not (declared.isascii() and declared.isdigit()):  # isdigit alone takes "²"
        raise refused(status.HTTP_411_LENGTH_REQUIRED, SEND_THE_LENGTH)
    length = int(declared)
    if length > MAX_RESUME_BYTES:
        raise refused(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE)
    if length == 0:
        raise refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, NOT_A_PDF)
    return length


async def read_pdf(request: Request) -> bytes:
    """The whole file, at most ``MAX_RESUME_BYTES``, or the refusal that stopped reading it."""
    length = declared_length(request)
    chunks: list[bytes] = []
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > length:  # the declared length is within the cap, so this caps it too
                raise refused(status.HTTP_413_CONTENT_TOO_LARGE, LONGER_THAN_DECLARED)
            seen_before = size - len(chunk)
            chunks.append(chunk)
            first_five_bytes_in = seen_before < len(PDF_SIGNATURE) <= size
            if first_five_bytes_in and not b"".join(chunks).startswith(PDF_SIGNATURE):
                raise refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, NOT_A_PDF)
    except ClientDisconnect:
        # The client went away mid-body: nothing is stored, and no one hears this answer.
        raise refused(status.HTTP_400_BAD_REQUEST, ENDED_EARLY) from None
    if size < len(PDF_SIGNATURE):
        raise refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, NOT_A_PDF)
    if size < length:
        raise refused(status.HTTP_400_BAD_REQUEST, ENDED_EARLY)
    return b"".join(chunks)
