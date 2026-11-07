"""How the service answers a request its models refuse.

FastAPI answers 422 with each error and the input it refused. A JSON body can
spell half of a surrogate pair (``"\\ud800"``), which no UTF-8 text can hold,
so writing that input back as UTF-8 fails and the refusal becomes a 500. The
answer here is FastAPI's own body, written as JSON that escapes every
character outside ASCII: the same document to any JSON reader, and one that
can carry back whatever the request held.
"""

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class EscapedJSONResponse(JSONResponse):
    """JSON with every character outside ASCII written as an escape."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, allow_nan=False, separators=(",", ":")).encode("ascii")


def answer_refused_requests(app: FastAPI) -> None:
    """Has ``app`` answer every refused request as FastAPI does, in escaped JSON."""

    @app.exception_handler(RequestValidationError)
    async def refused(request: Request, exc: RequestValidationError) -> EscapedJSONResponse:
        return EscapedJSONResponse(
            status_code=422, content={"detail": jsonable_encoder(exc.errors())}
        )
