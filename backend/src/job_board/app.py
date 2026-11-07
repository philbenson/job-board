from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from job_board import health, me, profiles
from job_board.body_limit import BodyLimit
from job_board.database import make_sessionmaker
from job_board.logging_setup import configure_logging
from job_board.model_key import routes as model_key_routes
from job_board.model_key.check_limits import CheckLimits
from job_board.resumes import routes as resume_routes
from job_board.resumes.store import open_store
from job_board.settings import Settings
from job_board.validation_answers import answer_refused_requests


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    With no settings it reads them from the environment, which is how
    ``uvicorn job_board.app:create_app --factory`` calls it. The database
    engine and its session maker live exactly as long as the application:
    created at startup, disposed of at shutdown. So does the resume store's
    client, when the settings name a store.
    """
    resolved = settings if settings is not None else Settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(resolved.database_url.get_secret_value(), pool_pre_ping=True)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        store = open_store(resolved.resume_storage())
        app.state.resume_store = store
        try:
            yield
        finally:
            if store is not None:
                store.close()
            await engine.dispose()

    app = FastAPI(title="Job board", lifespan=lifespan)
    app.state.settings = resolved
    app.state.check_limits = CheckLimits()
    app.add_middleware(BodyLimit)
    answer_refused_requests(app)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(model_key_routes.router)
    app.include_router(profiles.router)
    app.include_router(resume_routes.router)
    return app
