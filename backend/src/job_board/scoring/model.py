"""The rating a model gives one posting, and the real model that gives it.

Invariant: the person's key goes only to Anthropic's API, in the request's
authorization header. The base URL and that header are set here, over anything
the environment says. Unlike the model key check, this cannot also remove an
``X-Api-Key`` header that ``ANTHROPIC_CUSTOM_HEADERS`` adds: LangChain takes
header values as text only, with no way to say "omit".
"""

from collections.abc import Callable
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ConfigDict, Field, field_validator

from job_board.model_key.check import ANTHROPIC_API, CHECK_MODEL

SCORING_MODEL = CHECK_MODEL  # the model a person's key was checked against
MIN_SCORE = 1
MAX_SCORE = 5
MAX_REASON_LENGTH = 200  # one sentence, short enough to show beside a posting's title
# A score and one sentence take well under this; it caps what a runaway reply costs.
MAX_TOKENS = 1024
TIMEOUT_SECONDS = 60.0  # one rating; the schedule's next run tries again

# A model that takes the prompt's messages and answers a Rating, or raises.
type RatingModel = Runnable[LanguageModelInput, Any]
# Builds the model for one batch from that person's key.
type ModelFactory = Callable[[str], RatingModel]


class Rating(BaseModel):
    """How well one posting fits the titles a person seeks, and why.

    The schema sent to the model carries the bounds only as descriptions, so
    these validators are what hold a reply to them. Strict, so a score sent as
    text or as a fraction is no score.
    """

    model_config = ConfigDict(strict=True)

    score: int = Field(
        description=(
            f"How well the posting fits the titles sought: a whole number from {MIN_SCORE}, "
            f"a poor fit, to {MAX_SCORE}, a strong fit."
        )
    )
    reason: str = Field(
        description=(
            f"One plain sentence saying why, on one line, at most {MAX_REASON_LENGTH} characters."
        )
    )

    @field_validator("score")
    @classmethod
    def _within_the_scale(cls, score: int) -> int:
        if not MIN_SCORE <= score <= MAX_SCORE:
            raise ValueError(f"the score must be from {MIN_SCORE} to {MAX_SCORE}")
        return score

    @field_validator("reason")
    @classmethod
    def _one_short_line(cls, reason: str) -> str:
        trimmed = reason.strip()
        if not trimmed:
            raise ValueError("the reason is empty")
        if len(trimmed) > MAX_REASON_LENGTH:
            raise ValueError(f"the reason is longer than {MAX_REASON_LENGTH} characters")
        if len(trimmed.splitlines()) > 1:  # every line break Python knows, not only \n
            raise ValueError("the reason runs over more than one line")
        return trimmed


def anthropic_model(
    key: str, *, base_url: str = ANTHROPIC_API, timeout: float = TIMEOUT_SECONDS
) -> RatingModel:
    """Claude on the person's own key, answering a Rating through a JSON schema.

    The schema goes as structured output rather than a forced tool call, which
    the model does not support. No retries: the schedule is the retry, and a
    retried call costs the person twice. ``base_url`` and ``timeout`` are for
    the tests, which point it at a local server.
    """
    chat = init_chat_model(
        SCORING_MODEL,
        model_provider="anthropic",
        api_key=key,
        base_url=base_url,
        default_headers={"Authorization": f"Bearer {key}"},
        max_tokens=MAX_TOKENS,
        max_retries=0,
        timeout=timeout,
    )
    return chat.with_structured_output(Rating, method="json_schema")
