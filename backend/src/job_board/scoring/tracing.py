"""The refusal to score while LangSmith tracing is on.

A trace would carry each posting, the person's profile and the model's reply to
LangSmith. LangSmith turns tracing on from any of these variables, read as
``TRACING_V2`` first and ``TRACING`` second under either prefix; it takes only
the exact text ``true``, and the refusal takes more, so no spelling slips past.
"""

import os
from collections.abc import Mapping

TRACING_VARIABLES = (
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
)
_TRUE = frozenset({"true", "1", "yes"})


def tracing_turned_on(environment: Mapping[str, str] = os.environ) -> str | None:
    """The first variable that turns tracing on, or None when none does."""
    for name in TRACING_VARIABLES:
        if environment.get(name, "").strip().lower() in _TRUE:
            return name
    return None
