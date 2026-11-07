"""Reading a resume's text, in a child process the service limits and checks.

A PDF is a program of sorts: a hostile one can inflate a stream to gigabytes,
nest objects until a parser runs out of stack, or loop. So the service never
parses one itself. It starts ``job_board.resumes.text_child`` with nothing in
its environment, hands it the file and limits on processor time and memory,
waits at most ``wall_seconds``, and kills it past that. One reading runs at a
time, so a burst of uploads queues rather than multiplying the memory taken.
The wait for a turn is outside the wall clock: it bounds the reading alone.

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
from collections.abc import Sequence
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


def _ending(code: int) -> str:
    if code >= 0:
        return f"exited with code {code}"
    try:
        return f"ended by signal {signal.Signals(-code).name}"
    except ValueError:
        return f"ended by signal {-code}"


@dataclass
class ResumeTextReader:
    """Reads resumes' text one at a time, each in a child process under these limits."""

    command: Sequence[str] = (sys.executable, "-I", "-m", "job_board.resumes.text_child")
    wall_seconds: float = 15  # a long resume reads in under a second
    cpu_seconds: int = 10
    address_space_bytes: int = 256 * 1024 * 1024  # pypdf reading a 5 MB file needs far less
    one_at_a_time: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))

    async def read(self, file: bytes | bytearray) -> Reading:
        """The file's text and what reading it gave; ``failed`` for anything that went wrong."""
        async with self.one_at_a_time:
            try:
                async with asyncio.timeout(self.wall_seconds):
                    return await self._read(file)
            except TimeoutError:
                logger.warning(
                    "resume text reading did not finish within %s seconds", self.wall_seconds
                )
                return FAILED

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
