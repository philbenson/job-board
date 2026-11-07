"""Validation refusals that never quote what was sent.

FastAPI's own 422 for a body it cannot read repeats the offending input, and
for a missing field or a body that is not an object that input is the whole
body. A body carrying a secret must not come back, so routes built with
``QuietValidationRoute`` answer the same list of problems with only each
one's type, location and message.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

KEPT = ("type", "loc", "msg")  # "input" and "ctx" can quote the body


class QuietValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def quiet_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as refusal:
                problems = [
                    {name: problem[name] for name in KEPT if name in problem}
                    for problem in refusal.errors()
                ]
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"detail": jsonable_encoder(problems)},
                )

        return quiet_handler
