import tracemalloc

from starlette.requests import Request
from starlette.types import Message

from job_board.resumes.upload import MAX_RESUME_BYTES, PDF_SIGNATURE, read_pdf

CHUNK = 64 * 1024


def arriving(length: int) -> Request:
    """A request whose body of ``length`` bytes arrives a chunk at a time, each made as it comes."""
    left = length

    async def receive() -> Message:
        nonlocal left
        size = min(CHUNK, left)
        # Made here, as a server makes each chunk it reads off the socket.
        first = left == length
        chunk = PDF_SIGNATURE + bytes(size - len(PDF_SIGNATURE)) if first else bytes(size)
        left -= size
        return {"type": "http.request", "body": chunk, "more_body": left > 0}

    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/resume",
        "headers": [
            (b"content-type", b"application/pdf"),
            (b"content-length", str(length).encode()),
        ],
    }
    return Request(scope, receive)


async def test_holds_the_file_once_while_it_arrives() -> None:
    request = arriving(MAX_RESUME_BYTES)

    tracemalloc.start()
    try:
        file = await read_pdf(request)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(file) == MAX_RESUME_BYTES
    assert file.startswith(PDF_SIGNATURE)
    # The file, and a chunk or two on its way in; never a second copy of it.
    assert peak < MAX_RESUME_BYTES + 4 * CHUNK
