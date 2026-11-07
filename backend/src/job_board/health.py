"""The health route.

Invariant: ``GET /health`` tells the truth about the database within a bounded
time and never says why it failed. Error messages carry hosts, ports and
sometimes credentials, so neither the response nor the log repeats them.
"""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

HEALTH_CHECK_TIMEOUT_SECONDS = 2.0  # a probe answers promptly; a database this slow counts as down

logger = logging.getLogger(__name__)
router = APIRouter()


class Health(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unreachable"]


OK = Health(status="ok", database="ok")
UNAVAILABLE = Health(status="unavailable", database="unreachable")


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
async def health(engine: Annotated[AsyncEngine, Depends(get_engine)]) -> JSONResponse:
    try:
        async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as error:  # OSError covers TimeoutError from the ceiling
        logger.warning("database health check failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content=UNAVAILABLE.model_dump())
    return JSONResponse(content=OK.model_dump())
