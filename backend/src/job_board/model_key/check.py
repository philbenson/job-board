"""Checking a model key with Anthropic before it is saved.

The check reads the metadata of the model the app runs: Anthropic answers it
only for a key that is real and allowed that model, and it generates nothing,
so it costs the key's owner nothing.

Invariant: the key goes only to Anthropic's API, in the request's
authorization header. No outcome, log line or exception from here carries it.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

import anthropic

CHECK_MODEL = "claude-opus-5-5"  # the model the app runs; a key that cannot use it is no use here
# Named here so that no environment variable can send people's keys anywhere else.
ANTHROPIC_API = "https://api.anthropic.com"
ATTEMPT_TIMEOUT_SECONDS = 10.0  # one request; the metadata read answers in well under this
RETRIES = 1  # one more try for a rate limit, an overload or a dropped connection
# The whole check, retries included: Anthropic may ask the client to wait before
# a retry, and the client would wait as long as it is told while the person waits.
CHECK_CEILING_SECONDS = 25.0

CheckOutcome = Literal["accepted", "rejected", "not-permitted", "unavailable"]
KeyChecker = Callable[[str], Awaitable[CheckOutcome]]

logger = logging.getLogger(__name__)


async def check_with_anthropic(
    key: str, *, http_client: anthropic.DefaultAsyncHttpxClient | None = None
) -> CheckOutcome:
    """What Anthropic makes of a key: accepted, rejected, not permitted the model, or no answer.

    ``http_client`` is for the tests, which hand in a fake transport.
    """
    try:
        async with asyncio.timeout(CHECK_CEILING_SECONDS):
            async with anthropic.AsyncAnthropic(
                api_key=key,
                base_url=ANTHROPIC_API,
                timeout=ATTEMPT_TIMEOUT_SECONDS,
                max_retries=RETRIES,
                http_client=http_client,
            ) as client:
                await client.models.retrieve(CHECK_MODEL)
    except anthropic.AuthenticationError:
        return "rejected"
    except anthropic.PermissionDeniedError, anthropic.NotFoundError:
        return "not-permitted"
    except Exception as failure:
        # Anything else is no answer. Only the class is logged: a message may
        # quote the request, and the request carries the key.
        logger.warning("model key check had no answer: %s", type(failure).__name__)
        return "unavailable"
    return "accepted"


def get_key_checker() -> KeyChecker:
    """The checker the routes use; tests replace this dependency with their own."""
    return check_with_anthropic
