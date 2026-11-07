"""The database engine's sessions, one per request.

The engine and its session maker live on the application's state, made and
disposed of by the lifespan in ``app.py``.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # Rows read before a commit stay readable after it, without another query.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session for one request, closed when the request ends.

    Nothing is committed here: the dependency that writes commits its own
    work, so a request that only reads never opens a write.
    """
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
