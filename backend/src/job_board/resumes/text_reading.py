"""Reading a resume's text, in a child process the service limits and checks.

A PDF is a program of sorts: a hostile one can inflate a stream to gigabytes,
nest objects until a parser runs out of stack, or loop. So the service never
parses one itself. It starts ``job_board.resumes.text_child`` with nothing in
its environment, hands it the file and limits on processor time and memory,
waits at most ``wall_seconds``, and kills it past that.

One reading runs at a time, so a burst of uploads queues rather than
multiplying the memory taken, and the queue is bounded too: a few uploads
wait for a turn, each for a while, one person has one upload in it, and past
any of these the reading is refused as busy. So a burst holds at most a few
files in memory, and an upload's wait has an end. The wait for a turn is
outside the wall clock: that bounds the reading alone.

The child's answer is checked as though anyone had written it: it must be one
JSON object of exactly the state and the text, no longer than the longest
answer the cap allows, with text the rules would leave unchanged. Anything
else, an exit that is not clean, or a reading past its time is a reading that
failed, logged by kind and never with the text.
"""

import asyncio
import json
import logging
import signal
import sys
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field

from job_board.resumes.text_rules import FEWEST_LETTERS, MAX_RESUME_TEXT_LENGTH, Reading, cleaned
from job_board.resumes.upload import MAX_RESUME_BYTES

logger = logging.getLogger(__name__)

FAILED = Reading("failed", None)
# Four bytes is the most UTF-8 spends on a character, and two the most JSON
# escaping spends on one the rules keep; 64 holds the keys, the state and the
# punctuation around them.
LONGEST_ANSWER_BYTES = 64 + 4 * MAX_RESUME_TEXT_LENGTH
CHUNK_BYTES = 64 * 1024
# Uploads that may wait beside the one being read. Each holds its file, up to
# 5 MB, while it waits, so this bounds what a burst holds; two lets a few
# people uploading at once each get a turn.
WAITING_READINGS = 2
# How long an upload waits for its turn: a reading at its longest, so one
# waiting behind it still gets one.
TURN_WAIT_SECONDS = 15


class ReadingBusy(Exception):
    """The reading was refused: too many wait, the person has one already, or no turn came."""


def _answer_of(answer: bytes) -> Reading | None:
    """The reading the child's answer gives, or None if the parent cannot vouch for it."""
    try:
        value = json.loads(answer)
    except ValueError, RecursionError:
        return None
    if not isinstance(value, dict) or value.keys() != {"state", "text"}:
        return None
    state, text = value["state"], value["text"]
    if state == "none_found" and text is None:
        return Reading("none_found", None)
    if (
        state in ("found", "cut")
        and isinstance(text, str)
        and 0 < len(text) <= MAX_RESUME_TEXT_LENGTH
        and sum(character.isalpha() for character in text) >= FEWEST_LETTERS
        and cleaned(text) == text
    ):
        return Reading(state, text)
    return None


async def _send(stdin: asyncio.StreamWriter, file: bytes | bytearray) -> None:
    # A child that ends before it reads the whole file breaks the pipe; its
    # exit says what happened, so the broken pipe says nothing more.
    try:
        stdin.write(file)
        await stdin.drain()
        stdin.close()
        await stdin.wait_closed()
    except BrokenPipeError, ConnectionResetError:
        pass


async def _bounded(stdout: asyncio.StreamReader) -> bytes | None:
    """All the child writes, or None once it writes past the longest answer."""
    answer = bytearray()
    while chunk := await stdout.read(CHUNK_BYTES):
        answer += chunk
        if len(answer) > LONGEST_ANSWER_BYTES:
            return None
    return bytes(answer)


def _busy(bound: str) -> ReadingBusy:
    logger.warning("resume text reading refused as busy: %s", bound)
    return ReadingBusy(bound)


def _ending(code: int) -> str:
    if code >= 0:
        return f"exited with code {code}"
    try:
        return f"ended by signal {signal.Signals(-code).name}"
    except ValueError:
        return f"ended by signal {-code}"


@dataclass
class ResumeTextReader:
    """Reads resumes' text one at a time, each in a child process under these limits.

    Invariant: an upload counts in ``_holding`` and its person in ``_people``
    from the moment it is let wait until it is read, refused for no turn,
    timed out or cancelled, and on every one of those paths it is freed.
    """

    command: Sequence[str] = (sys.executable, "-I", "-m", "job_board.resumes.text_child")
    wall_seconds: float = 15  # a long resume reads in under a second
    cpu_seconds: int = 10
    address_space_bytes: int = 256 * 1024 * 1024  # pypdf reading a 5 MB file needs far less
    waiting_readings: int = WAITING_READINGS
    turn_wait_seconds: float = TURN_WAIT_SECONDS
    one_at_a_time: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    _holding: int = field(default=0, init=False)  # the upload being read and those waiting
    _people: set[Hashable] = field(default_factory=set, init=False)

    async def read(self, file: bytes | bytearray, person: Hashable | None = None) -> Reading:
        """The file's text and what reading it gave; ``failed`` for anything that went wrong.

        ``person`` is whose upload it is, of whom one upload may be read or
        waiting at once; None for a reading that is no one's upload. Raises
        ``ReadingBusy``, logged with the bound that refused it, past the wait.
        """
        if person is not None and person in self._people:
            raise _busy("that person's upload is already being read or waiting")
        if self._holding > self.waiting_readings:
            raise _busy(f"{self.waiting_readings} uploads already wait for a turn")
        self._holding += 1
        if person is not None:
            self._people.add(person)
        try:
            try:
                async with asyncio.timeout(self.turn_wait_seconds):
                    await self.one_at_a_time.acquire()
            except TimeoutError:
                raise _busy(f"no turn came within {self.turn_wait_seconds} seconds") from None
            try:
                async with asyncio.timeout(self.wall_seconds):
                    return await self._read(file)
            except TimeoutError:
                logger.warning(
                    "resume text reading did not finish within %s seconds", self.wall_seconds
                )
                return FAILED
            finally:
                self.one_at_a_time.release()
        finally:
            self._holding -= 1
            self._people.discard(person)

    async def _read(self, file: bytes | bytearray) -> Reading:
        limits = (self.cpu_seconds, self.address_space_bytes, MAX_RESUME_BYTES)
        child = await asyncio.create_subprocess_exec(
            *self.command,
            *map(str, limits),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={},
        )
        assert child.stdin is not None and child.stdout is not None
        sending = asyncio.create_task(_send(child.stdin, file))
        try:
            answer = await _bounded(child.stdout)
            if answer is None:
                logger.warning(
                    "resume text reading answered more than %d bytes", LONGEST_ANSWER_BYTES
                )
                return FAILED
            code = await child.wait()
        finally:
            # A timeout, a cancel or an answer past its bound leaves the child
            # running: it is killed and waited for, so none outlives its reading.
            if child.returncode is None:
                child.kill()
                await child.wait()
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
        if code != 0:
            logger.warning("resume text reading %s", _ending(code))
            return FAILED
        reading = _answer_of(answer)
        if reading is None:
            logger.warning("resume text reading answered in the wrong shape")
            return FAILED
        return reading
