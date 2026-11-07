"""``python -m job_board.scoring``: one batch for each person to be scored.

Exits 0 when every batch finished, or had nothing it could do (another run held
the person, or the key was sealed under another service key); 1 when any batch
stopped on a failure; 2 when it refused to start. It needs only DATABASE_URL and
MODEL_KEY_ENCRYPTION_KEY, read from the environment or a .env file in the
working directory.
"""

import asyncio
import logging

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from job_board.database import make_sessionmaker
from job_board.logging_setup import configure_logging
from job_board.scoring.batch import score_everyone
from job_board.scoring.model import ModelFactory, anthropic_model
from job_board.scoring.tracing import tracing_turned_on
from job_board.settings import ScoringSettings

EXIT_FINISHED = 0
EXIT_STOPPED = 1
EXIT_REFUSED = 2

log = logging.getLogger(__name__)


def refuse_tracing() -> bool:
    """Log the refusal and answer True when LangSmith tracing is on."""
    configure_logging()
    variable = tracing_turned_on()
    if variable is not None:
        log.error(
            "refusing to start: %s turns on LangSmith tracing, which would send postings, "
            "titles and the model's replies to LangSmith; unset it or set it to false",
            variable,
        )
    return variable is not None


def _settings() -> ScoringSettings | None:
    try:
        return ScoringSettings()
    except ValidationError as error:  # its text never repeats a value: hide_input_in_errors
        for problem in error.errors():
            name = ".".join(str(part) for part in problem["loc"]).upper()
            log.error("refusing to start: %s: %s", name, problem["msg"])
        return None


async def _score(settings: ScoringSettings, model_factory: ModelFactory) -> int:
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        results = await score_everyone(
            engine,
            make_sessionmaker(engine),
            service_key=settings.model_key_encryption_key.get_secret_value(),
            model_factory=model_factory,
        )
    finally:
        await engine.dispose()
    return EXIT_STOPPED if any(result.failed for result in results) else EXIT_FINISHED


def main(model_factory: ModelFactory = anthropic_model) -> int:
    """Score everyone once and give the exit code. ``model_factory`` is for the tests."""
    if refuse_tracing():
        return EXIT_REFUSED
    settings = _settings()
    if settings is None:
        return EXIT_REFUSED
    return asyncio.run(_score(settings, model_factory))
