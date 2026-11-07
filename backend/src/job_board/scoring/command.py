"""``python -m job_board.scoring``: one batch for each person to be scored.

Exits 0 when every batch finished, or had nothing it could do (another run held
the person, or that one key was sealed under another service key); 1 when any
batch stopped on a failure, or when no person's key was sealed under this
service key, which is the operator's mistake rather than theirs; 2 when it
refused to start. It needs only DATABASE_URL and MODEL_KEY_ENCRYPTION_KEY, read
from the environment or a .env file in the working directory, and refuses to
start while LangSmith tracing is on, ANTHROPIC_CUSTOM_HEADERS is set or
ANTHROPIC_LOG is set to anything but empty.
"""

import asyncio
import logging
import os

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

# The Anthropic SDK adds these headers to every request, over the client's own.
CUSTOM_HEADERS = "ANTHROPIC_CUSTOM_HEADERS"
# The Anthropic SDK's own logging; at debug it writes every request's whole body.
LIBRARY_LOG = "ANTHROPIC_LOG"

log = logging.getLogger(__name__)


def refuse_the_environment() -> bool:
    """Log each setting the command will not run under, and answer True when there is one."""
    configure_logging()
    refused = False
    variable = tracing_turned_on()
    if variable is not None:
        log.error(
            "refusing to start: %s turns on LangSmith tracing, which would send postings, "
            "each person's profile and the model's replies to LangSmith; unset it or set it "
            "to false",
            variable,
        )
        refused = True
    # The SDK's own OpenTelemetry spans are no-ops while only opentelemetry-api is installed;
    # with an OpenTelemetry SDK added and their content mode set to "content", they would carry
    # the prompts.
    if CUSTOM_HEADERS in os.environ:
        log.error(
            "refusing to start: %s adds headers to every request to Anthropic, which could "
            "send another credential beside each person's own key; unset it",
            CUSTOM_HEADERS,
        )
        refused = True
    if os.environ.get(LIBRARY_LOG, ""):
        log.error(
            "refusing to start: %s turns on the Anthropic library's own logging, which "
            "would write postings, each person's profile and the model's replies to the "
            "log; unset it",
            LIBRARY_LOG,
        )
        refused = True
    return refused


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
    if any(result.failed for result in results):
        return EXIT_STOPPED
    if results and all(result.sealed_elsewhere for result in results):
        log.error("no key opens under this MODEL_KEY_ENCRYPTION_KEY: is it the service's own?")
        return EXIT_STOPPED
    return EXIT_FINISHED


def main(model_factory: ModelFactory = anthropic_model) -> int:
    """Score everyone once and give the exit code. ``model_factory`` is for the tests."""
    if refuse_the_environment():
        return EXIT_REFUSED
    settings = _settings()
    if settings is None:
        return EXIT_REFUSED
    return asyncio.run(_score(settings, model_factory))
