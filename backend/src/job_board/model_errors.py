"""Reading a failed request to Anthropic, and recording what it says of the person's key.

Shared by scoring and the interviewer, which both call the model on the
person's own key. A reason names the failure's kind and never quotes the
error's message, which may quote the request.
"""

import re

import anthropic
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_board.model_key.failure import KeyFailure
from job_board.models import ModelKey

PROVIDER = "anthropic"  # the provider of every key the model is called on
# An error body's type or code is named only when it looks like one; its message never.
_CODE = re.compile(r"[a-z0-9_]{1,64}")


def failure_reason(error: anthropic.APIError) -> tuple[str, KeyFailure | None]:
    """The reason a failed request stops the work, and what it says of the key."""
    if isinstance(error, anthropic.APITimeoutError):  # a kind of connection error
        return "timed-out", None
    if isinstance(error, anthropic.APIConnectionError):
        return "connection-error", None
    if not isinstance(error, anthropic.APIStatusError):
        return f"unexpected: {type(error).__name__}", None
    status = error.status_code
    if status == 401:
        return "rejected", "rejected"
    if status == 403:
        return "not-permitted", "not-permitted"
    if status == 404:
        # Most likely this app names a model Anthropic no longer serves, which is no
        # fault of the key: the key is left as it is and the operator is told.
        return "model-not-found", None
    if status == 402:  # the SDK has no class of its own for it
        return "no-credit", "no-credit"
    if status == 408:
        return "timed-out", None
    if status == 429:
        return "rate-limited", None
    if status >= 500:
        return "server-error", None
    codes = [code for code in (error.type, error.error_code) if code and _CODE.fullmatch(code)]
    return f"refused-{status}" + (f" ({', '.join(codes)})" if codes else ""), None


async def mark_key_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    person_id: int,
    sealed_key: bytes,
    failure: KeyFailure,
) -> None:
    """Record the key's failure, unless the person has saved another key meanwhile."""
    async with sessionmaker() as session, session.begin():
        await session.execute(
            update(ModelKey)
            .where(
                ModelKey.person_id == person_id,
                ModelKey.provider == PROVIDER,
                ModelKey.sealed_key == sealed_key,
                ModelKey.failure.is_(None),
            )
            .values(failure=failure, failed_at=func.now())
        )
