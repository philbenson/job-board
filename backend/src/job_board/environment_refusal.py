"""The settings under which neither the web service nor the scoring command runs.

Each one could carry a person's text out: a LangSmith trace would hold each
resume, profile, answer and posting the model reads and every reply it gives;
``ANTHROPIC_CUSTOM_HEADERS`` adds headers to every request to Anthropic, which
could send another credential beside the person's own key; the Anthropic
library's own log, at debug, writes every request's whole body. Each is refused
by name, never by its value, which may be a credential.

LangSmith turns tracing on from any of ``TRACING_VARIABLES``, read as
``TRACING_V2`` first and ``TRACING`` second under either prefix; it takes only
the exact text ``true``, and the refusal takes more, so no spelling slips past.
"""

import logging
import os
from collections.abc import Mapping

TRACING_VARIABLES = (
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
)
_TRUE = frozenset({"true", "1", "yes"})

# The Anthropic SDK adds these headers to every request, over the client's own.
CUSTOM_HEADERS = "ANTHROPIC_CUSTOM_HEADERS"
# The Anthropic SDK's own logging; at debug it writes every request's whole body.
LIBRARY_LOG = "ANTHROPIC_LOG"

log = logging.getLogger(__name__)


class RefusedEnvironment(RuntimeError):
    """The web service will not start under these settings, named in ``names``."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(f"refusing to start under {', '.join(names)}; see the log for why")
        self.names = names


def tracing_turned_on(environment: Mapping[str, str] = os.environ) -> str | None:
    """The first variable that turns tracing on, or None when none does."""
    for name in TRACING_VARIABLES:
        if environment.get(name, "").strip().lower() in _TRUE:
            return name
    return None


def refused_settings(environment: Mapping[str, str] = os.environ) -> list[str]:
    """Log each setting refused here, by name, and give their names; empty when none is."""
    refused = []
    variable = tracing_turned_on(environment)
    if variable is not None:
        log.error(
            "refusing to start: %s turns on LangSmith tracing, which would send each person's "
            "resume, profile and answers, the postings and the model's replies to LangSmith; "
            "unset it or set it to false",
            variable,
        )
        refused.append(variable)
    # The SDK's own OpenTelemetry spans are no-ops while only opentelemetry-api is installed;
    # with an OpenTelemetry SDK added and their content mode set to "content", they would carry
    # the prompts.
    if CUSTOM_HEADERS in environment:
        log.error(
            "refusing to start: %s adds headers to every request to Anthropic, which could "
            "send another credential beside each person's own key; unset it",
            CUSTOM_HEADERS,
        )
        refused.append(CUSTOM_HEADERS)
    if environment.get(LIBRARY_LOG, ""):
        log.error(
            "refusing to start: %s turns on the Anthropic library's own logging, which "
            "would write each person's resume, profile and answers, the postings and the "
            "model's replies to the log; unset it",
            LIBRARY_LOG,
        )
        refused.append(LIBRARY_LOG)
    return refused
