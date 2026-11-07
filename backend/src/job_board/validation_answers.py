"""One answer for every request the service cannot read, and it never quotes the request.

When a body or a parameter fails validation, FastAPI's own 422 repeats what was
sent: for a missing field, or a body that is not an object, that is the whole
body, and a body can carry a secret such as a person's model key. This answer
keeps only each problem's type, location and message.

The answer is written in ASCII alone, with every other character escaped. JSON
can spell half of a surrogate pair, and no UTF-8 text can hold one. The
validation library refuses one today before it reaches a location or a message,
but if one ever did, writing it unescaped would turn a refusal into a server
error.
"""

import json
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

KEPT = ("type", "loc", "msg")  # "input" and "ctx" can quote what was sent


class AsciiJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, allow_nan=False, separators=(",", ":")).encode("ascii")


async def answer_quietly(request: Request, refusal: Exception) -> AsciiJSONResponse:
    assert isinstance(refusal, RequestValidationError)  # registered for this class only
    problems = [
        {name: problem[name] for name in KEPT if name in problem} for problem in refusal.errors()
    ]
    return AsciiJSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(problems)},
    )


def answer_refused_requests(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, answer_quietly)
