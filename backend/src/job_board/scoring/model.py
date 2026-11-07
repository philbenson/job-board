"""The rating a model gives one posting, and the real model that gives it.

Invariant: the person's key goes only to Anthropic's API, as the request's
only credential. The base URL is set here, over anything the environment says,
and the key goes only as ``api_key``, which LangChain keeps as a secret: out of
the model's repr and its serialized form, which every callback is handed. The
SDK would add headers from ``ANTHROPIC_CUSTOM_HEADERS`` over the client's own,
so the scoring command refuses to start while that variable is set.
"""

import json
import unicodedata
from collections.abc import Callable
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, ConfigDict, Field, field_validator

from job_board.model_key.check import ANTHROPIC_API, CHECK_MODEL
from job_board.profile_rules import DIRECTION_CONTROLS

SCORING_MODEL = CHECK_MODEL  # the model a person's key was checked against
MIN_SCORE = 1
MAX_SCORE = 5
MAX_REASON_LENGTH = 200  # one sentence, short enough to show beside a posting's title
# A score and one sentence are a small judgement, paid for from the person's own
# key; raise it only if a measured set of postings rates better at a higher one.
EFFORT = "low"
# Thinking counts toward the limit on this model: this leaves room for short
# thinking at that effort and still bounds what a runaway reply costs.
MAX_TOKENS = 4096
# Thinking is always on; once an effort is set the library would ask for its
# summaries, which nothing reads and which would carry text drawn from the
# person's profile through every callback. Leaving them out changes only what
# is returned, not what is thought or billed.
THINKING = {"type": "adaptive", "display": "omitted"}
TIMEOUT_SECONDS = 60.0  # one rating; the schedule's next run tries again
CUT_OFF = "max_tokens"  # the stop reason of a reply that reached the token limit

# A model that takes the prompt's messages and answers a Rating, or raises.
type RatingModel = Runnable[LanguageModelInput, Any]
# Builds the model for one batch from that person's key.
type ModelFactory = Callable[[str], RatingModel]


class ReplyCutOff(Exception):
    """The reply stopped at the token limit before it was a whole rating.

    It carries none of the reply, so it can be logged or raised anywhere.
    """


class Rating(BaseModel):
    """How well one posting fits the person's profile, and why.

    The schema sent to the model carries the bounds only as descriptions, so
    these validators are what hold a reply to them. Strict, so a score sent as
    text or as a fraction is no score.
    """

    model_config = ConfigDict(strict=True)

    score: int = Field(
        description=(
            f"How well the posting fits the person's profile: a whole number from {MIN_SCORE}, "
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
        # Controls (NUL among them, which PostgreSQL text cannot hold) and lone
        # surrogates would fail the insert; direction controls would reorder
        # the sentence where it is shown, as they would a target title.
        if any(unicodedata.category(character) in {"Cc", "Cs"} for character in trimmed):
            raise ValueError("the reason holds a control character")
        if not DIRECTION_CONTROLS.isdisjoint(trimmed):
            raise ValueError("the reason holds a text direction control")
        return trimmed


def _is_whole_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _one_rating(answer: dict[str, Any]) -> Any:
    """The rating in a reply, or the reason there is none, raised.

    The parser mends unclosed JSON, so a reply cut off inside its reason would
    read as a rating with half a sentence: a reply that stopped at the limit
    counts only when its text is whole JSON on its own. Otherwise the parser's
    own error is raised as it came; it quotes the reply, so it is never logged.
    """
    raw: AIMessage = answer["raw"]
    if raw.response_metadata.get("stop_reason") == CUT_OFF and not _is_whole_json(raw.text):
        raise ReplyCutOff
    error: BaseException | None = answer["parsing_error"]
    if error is not None:
        raise error
    return answer["parsed"]


def anthropic_model(
    key: str, *, base_url: str = ANTHROPIC_API, timeout: float = TIMEOUT_SECONDS
) -> RatingModel:
    """Claude on the person's own key, answering a Rating through a JSON schema.

    The schema goes as structured output rather than a forced tool call, which
    the model does not support. No retries: the schedule is the retry, and a
    retried call costs the person twice. ``base_url`` and ``timeout`` are for
    the tests, which point it at a local server. The raw reply comes back
    beside the parsed one only so a reply cut off at the limit can be told
    apart; what leaves this model is a Rating, or an exception.
    """
    chat = init_chat_model(
        SCORING_MODEL,
        model_provider="anthropic",
        api_key=key,
        base_url=base_url,
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        thinking=THINKING,
        max_retries=0,
        timeout=timeout,
    )
    structured = chat.with_structured_output(Rating, method="json_schema", include_raw=True)
    return structured | RunnableLambda(_one_rating)
