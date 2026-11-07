"""How often one person may have a model key checked with Anthropic.

Each check is a request to Anthropic from the service's own address, and its
answer says whether a key is live, so checks are limited per person: one at a
time, and at most ten in any rolling hour. Only checks that go to Anthropic are
counted; a key refused as malformed never gets here.

The counts are kept in this process's memory. A service run as several
processes keeps one count in each, so it lets each person check that many
times as many keys. Nothing here touches the database, so nothing is held
there while a check runs.

The service runs on one event loop, and nothing here awaits, so a check and
its admission happen with no other request in between: no lock is needed.
"""

import time
from collections import deque
from collections.abc import Callable
from typing import Literal

CHECKS_PER_HOUR = 10
WINDOW_SECONDS = 3600.0

LimitReason = Literal["check-running", "too-many-checks"]


class CheckLimits:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._running: set[int] = set()
        # The times of each person's checks in the last hour, oldest first.
        self._recent: dict[int, deque[float]] = {}

    def admit(self, person_id: int) -> LimitReason | None:
        """Start a check for this person, or say why not; ``done`` must follow a start."""
        self._forget_before(self._clock() - WINDOW_SECONDS)
        if person_id in self._running:
            return "check-running"
        recent = self._recent.setdefault(person_id, deque())
        if len(recent) >= CHECKS_PER_HOUR:
            return "too-many-checks"
        recent.append(self._clock())
        self._running.add(person_id)
        return None

    def done(self, person_id: int) -> None:
        self._running.discard(person_id)

    def __len__(self) -> int:
        """How many people are remembered, which stays no more than those active this hour."""
        return len(self._recent)

    def _forget_before(self, cutoff: float) -> None:
        for person_id in list(self._recent):
            recent = self._recent[person_id]
            while recent and recent[0] <= cutoff:
                recent.popleft()
            if not recent:
                del self._recent[person_id]
