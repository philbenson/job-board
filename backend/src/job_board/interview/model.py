"""The real model the interviewer talks through, on the person's own key.

Invariant: the person's key goes only to Anthropic's API, as the request's only
credential, the way scoring sends it: the base URL is set here over anything
the environment says, and the key goes only as ``api_key``, which LangChain
keeps as a secret, out of the model's repr and its serialized form. The web
service refuses to start while ``ANTHROPIC_CUSTOM_HEADERS`` is set.
"""

from collections.abc import Callable
from functools import cached_property

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from job_board.model_key.check import ANTHROPIC_API, CHECK_MODEL
from job_board.scoring.model import INPUT_READING_SECONDS, SLOWEST_TOKENS_PER_SECOND

INTERVIEW_MODEL = CHECK_MODEL  # the model a person's key was checked against
# Each turn reads a resume and a conversation and picks the next question or a
# section to save: more judgement than a rating's, still paid for from the
# person's own key at every answer.
EFFORT = "medium"
# Thinking counts toward the limit: this leaves room for thinking at that
# effort, a question and a section's whole save in one reply, and still bounds
# what a runaway reply costs.
MAX_TOKENS = 8192
# Thinking is always on; its summaries are left out, since nothing reads them
# and they would carry text drawn from the resume and the answers through every
# callback. Leaving them out changes only what is returned.
THINKING = {"type": "adaptive", "display": "omitted"}
# Sized, as scoring's is, to let the whole token limit arrive at a speed this
# model is sure to beat, plus the time to read the input: 8,192 tokens at 25 a
# second and 30 seconds more make about 358 seconds. A reply that times out
# fails the run, and the person retries it.
TIMEOUT_SECONDS = MAX_TOKENS / SLOWEST_TOKENS_PER_SECOND + INPUT_READING_SECONDS
# An unreachable host fails the run in seconds rather than after the whole
# reply's timeout; a reachable one connects in well under a second.
CONNECT_SECONDS = 5.0
CUT_OFF = "max_tokens"  # the stop reason of a reply that reached the token limit
DECLINED = "refusal"  # the stop reason of a reply the model declined to go on with

# Builds the chat model for one run from the person's key.
type InterviewModelFactory = Callable[[str], BaseChatModel]


_REQUEST_TIMEOUT = anthropic.Timeout(TIMEOUT_SECONDS, connect=CONNECT_SECONDS)


class _Interviewer(ChatAnthropic):
    """LangChain's Claude, its requests connecting within ``CONNECT_SECONDS``.

    LangChain takes the timeout as one number, which the client applies to
    connecting as much as to reading. Each client here is LangChain's own,
    copied with the two set apart, so it keeps LangChain's shared connections.
    """

    @cached_property
    def _client(self) -> anthropic.Client:
        return super()._client.with_options(timeout=_REQUEST_TIMEOUT)

    @cached_property
    def _async_client(self) -> anthropic.AsyncClient:
        return super()._async_client.with_options(timeout=_REQUEST_TIMEOUT)


def anthropic_interviewer(key: str, *, base_url: str = ANTHROPIC_API) -> BaseChatModel:
    """Claude on the person's own key, to be bound to the interviewer's tools.

    No retries: a retried call costs the person twice, and a failed run is
    retried by the person, from its last saved step. ``base_url`` is for the
    tests, which point it at a local server.
    """
    return _Interviewer(
        model=INTERVIEW_MODEL,
        api_key=key,
        base_url=base_url,
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        thinking=THINKING,
        max_retries=0,
        timeout=TIMEOUT_SECONDS,
    )
