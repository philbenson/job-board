"""A local HTTP server that answers like Anthropic's Messages API, from canned replies.

The real model factory is pointed at it through its base URL, so the tests
drive the real client and LangChain's handling of each answer while no request
leaves the machine.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from job_board.model_key.check import CHECK_MODEL


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class Reply:
    status: int
    body: dict[str, Any]


def message(text: str) -> Reply:
    """A finished reply whose one text block is ``text``."""
    return Reply(
        200,
        {
            "id": "msg_canned",
            "type": "message",
            "role": "assistant",
            "model": CHECK_MODEL,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


def rating(score: int, reason: str) -> Reply:
    return message(json.dumps({"score": score, "reason": reason}))


def error(status: int, kind: str) -> Reply:
    return Reply(status, {"type": "error", "error": {"type": kind, "message": "refused in a test"}})


@dataclass
class CannedAnthropic:
    """Answers each request with the next reply, the last one again once they run out."""

    url: str
    replies: list[Reply] = field(default_factory=list)
    received: list[Received] = field(default_factory=list)

    def answer(self, request: Received) -> Reply:
        self.received.append(request)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@contextmanager
def canned_anthropic(*replies: Reply) -> Iterator[CannedAnthropic]:
    canned = CannedAnthropic(url="", replies=list(replies))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            reply = canned.answer(
                Received(self.path, {name.lower(): v for name, v in self.headers.items()}, body)
            )
            encoded = json.dumps(reply.body).encode()
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # the test's own output stays readable

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    canned.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield canned
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
