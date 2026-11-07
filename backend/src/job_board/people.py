"""The signed-in person, for any route that needs one.

Invariant: every route that depends on ``current_person`` gets exactly the
person whose valid session token came with the request, or answers 401. Every
refusal answers alike, so a caller learns nothing about why; the reason goes
to the log as a short code and never with the token or its claims.

Invariant: one row per person, even when their first two requests arrive at
once. Clerk's user id is unique in the table, and the insert yields to a row
another request has just written.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.models import Person
from job_board.settings import Settings
from job_board.tokens import TokenRefused, verify_session_token

logger = logging.getLogger(__name__)

# Declares the bearer token in the API description. It never refuses itself
# (auto_error=False), so every refusal goes through the one path below.
BEARER = HTTPBearer(auto_error=False, description="A Clerk session token.")


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def signed_in_user_id(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(BEARER)],
) -> str:
    """The Clerk user id of a valid ``Authorization: Bearer`` token, or 401."""
    try:
        if credentials is None:
            # No header, or one that is not "Bearer" followed by a token.
            present = bool(request.headers.get("Authorization"))
            raise TokenRefused("malformed" if present else "missing")
        return verify_session_token(credentials.credentials, settings)
    except TokenRefused as refusal:
        logger.info("sign-in refused: %s", refusal.reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="sign-in required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


async def current_person(
    clerk_user_id: Annotated[str, Depends(signed_in_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Person:
    """The person the token names, added on their first request.

    The token is checked before the session opens, so a refused request never
    touches the database. A known person costs one read; the insert runs only
    when the read finds nobody, which also keeps the id sequence from
    advancing on every request.
    """
    by_user_id = select(Person).where(Person.clerk_user_id == clerk_user_id)
    person = await session.scalar(by_user_id)
    if person is not None:
        return person
    await session.execute(
        insert(Person)
        .values(clerk_user_id=clerk_user_id)
        .on_conflict_do_nothing(index_elements=[Person.clerk_user_id])
    )
    await session.commit()
    # The row is ours or a concurrent first request's; either way it is committed.
    return (await session.scalars(by_user_id)).one()
