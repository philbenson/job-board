"""A cap on the size of every request body, applied before anything reads it.

Invariant: no route runs with a body over the cap, or with part of one. A body
declared larger than the cap is refused at once, unread. Any other body is read
here, counting its bytes as they arrive, and refused as soon as it passes the
cap; only a body read in full under the cap reaches the app, which then reads
it from here. So the refusal comes before the sign-in check, and costs at most
the cap in memory per request, which a route reading the body would hold anyway.

The service has no proxy in front of it yet to cap bodies; this is that cap.
"""

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LARGEST_BODY_BYTES = 64 * 1024  # far above any body a route here takes
TOO_LARGE = json.dumps({"detail": "The request body is too large"}).encode()


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > LARGEST_BODY_BYTES:
            await refuse(send)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away before sending the whole body
            chunk: bytes = message.get("body", b"")
            size += len(chunk)
            if size > LARGEST_BODY_BYTES:
                await refuse(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        whole: Message | None = {"type": "http.request", "body": b"".join(chunks)}

        async def replay() -> Message:
            nonlocal whole
            if whole is not None:
                message, whole = whole, None
                return message
            return await receive()  # after the body, only a disconnect is left to hear

        await self.app(scope, replay, send)


async def refuse(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(TOO_LARGE)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": TOO_LARGE})
