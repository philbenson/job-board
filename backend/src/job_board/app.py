from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from job_board import health
from job_board.database import make_sessionmaker
from job_board.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    With no settings it reads them from the environment, which is how
    ``uvicorn job_board.app:create_app --factory`` calls it. The database
    engine and its session maker live exactly as long as the application:
    created at startup, disposed of at shutdown.
    """
    resolved = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(resolved.database_url.get_secret_value(), pool_pre_ping=True)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Job board", lifespan=lifespan)
    app.include_router(health.router)
    return app
