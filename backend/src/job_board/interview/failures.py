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
    # The reply reached the token limit, or held neither text nor a tool call.
    "cut-off",
    "empty-reply",
    # The person's key was sealed under another service key, or will not open.
    "not-sealed-here",
    "unopenable",
    # Another run took over this one's stale claim.
    "lost-claim",
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
