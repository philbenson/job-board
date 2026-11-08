"""Why an interview's last run stopped short, as one list the table and the answers share."""

from typing import Literal, get_args

InterviewFailure = Literal[
    # Anthropic's answer, read the way scoring reads it, without its details.
    "timed-out",
    "connection-error",
    "rejected",
    "not-permitted",
    "model-not-found",
    "no-credit",
    "rate-limited",
    "server-error",
    "refused",
    # The reply reached the token limit, the model declined to give one, or it
    # held neither text nor a tool call.
    "cut-off",
    "declined",
    "empty-reply",
    # The person's key was sealed under another service key, or will not open.
    "not-sealed-here",
    "unopenable",
    # The service stopped while the run was in flight.
    "interrupted",
    # Anything else, logged by its type's name.
    "unexpected",
]
INTERVIEW_FAILURES: tuple[InterviewFailure, ...] = get_args(InterviewFailure)


def failure_is_known(column: str) -> str:
    """The check constraint's condition: the column holds one of the codes or nothing."""
    codes = ", ".join(f"'{code}'" for code in INTERVIEW_FAILURES)
    return f"{column} IN ({codes})"


class ReplyCutOff(Exception):
    """The model's reply stopped at the token limit; nothing of it is kept."""

    code: InterviewFailure = "cut-off"


class ModelDeclined(Exception):
    """The model stopped its reply by declining to go on; nothing of it is kept.

    Not ``refused``, which is Anthropic refusing the request itself.
    """

    code: InterviewFailure = "declined"


class EmptyReply(Exception):
    """The model's reply held neither text nor a tool call; nothing of it is kept."""

    code: InterviewFailure = "empty-reply"


class LostClaim(Exception):
    """Another run took over this run's claim when it went stale, so this run must stop.

    It records no failure: the interview belongs to the run that took it over.
    """
