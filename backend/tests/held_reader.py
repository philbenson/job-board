"""A resume text reader whose readings wait for the test, for testing the wait for a turn."""

import asyncio
from dataclasses import dataclass, field

from job_board.resumes.text_reading import ResumeTextReader
from job_board.resumes.text_rules import Reading

# A line of a resume with enough letters, 52, to count as text read.
FILLER = "Moved the whole ordering system onto a queue of small services"


@dataclass
class HeldReader(ResumeTextReader):
    """A reader whose every reading waits until the test lets go, takes ``takes``
    seconds more, then finds ``FILLER``. The bounds on the wait are the real ones."""

    let_go: asyncio.Event = field(default_factory=asyncio.Event)
    takes: float = 0
    begun: int = 0
    _begins: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def _read(self, file: bytes | bytearray) -> Reading:
        async with self._begins:
            self.begun += 1
            self._begins.notify_all()
        await self.let_go.wait()
        await asyncio.sleep(self.takes)
        return Reading("found", FILLER)

    async def reading_begins(self, count: int) -> None:
        """Wait until ``count`` readings have begun."""
        async with asyncio.timeout(5), self._begins:
            await self._begins.wait_for(lambda: self.begun >= count)
