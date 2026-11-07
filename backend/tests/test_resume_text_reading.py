import ast
import asyncio
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pdf_files import (
    bomb_page,
    costly_page,
    encrypted,
    image_page,
    one_page_many_times,
    pdf,
    resume_lines,
)
from pypdf import PdfReader

from job_board.resumes.text_child import text_of
from job_board.resumes.text_reading import LONGEST_ANSWER_BYTES, ResumeTextReader
from job_board.resumes.text_rules import (
    MAX_RESUME_PAGES,
    MAX_RESUME_TEXT_LENGTH,
    Reading,
    cleaned,
    reading_of,
)
from job_board.resumes.upload import MAX_RESUME_BYTES

FAILED = Reading("failed", None)
OURS = "job_board.resumes.text_reading"
# A line of a resume with enough letters, 52, to count as text read.
FILLER = "Moved the whole ordering system onto a queue of small services"
# The modules the reading's process must never load: what it holds is the
# file and the limits, and nothing that can reach the database or the secrets.
NEVER_IMPORTED = ("fastapi", "starlette", "sqlalchemy", "pydantic", "pydantic_settings")


def stub(program: str) -> ResumeTextReader:
    """A reader whose process runs ``program`` in place of the real reading."""
    return ResumeTextReader(command=(sys.executable, "-I", "-c", program))


def answer(state: str, text: str | None) -> str:
    return f"import sys; sys.stdout.write({json.dumps({'state': state, 'text': text})!r})"


def logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == OURS]


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def pid_in(pid_file: Path) -> int | None:
    written = pid_file.read_text() if pid_file.exists() else ""
    return int(written) if written else None


async def started(pid_file: Path) -> int:
    for _ in range(1000):  # ten seconds
        if (pid := pid_in(pid_file)) is not None:
            return pid
        await asyncio.sleep(0.01)
    raise AssertionError("the reading's process never started")


def sleeper(pid_file: Path) -> str:
    return f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"


async def test_a_one_column_resume_reads_as_its_lines() -> None:
    reading = await ResumeTextReader().read(pdf(resume_lines()))

    assert reading == Reading("found", "\n".join(resume_lines()))


async def test_pages_are_read_in_order_a_blank_line_apart() -> None:
    first, second = resume_lines()[:4], resume_lines()[4:]

    reading = await ResumeTextReader().read(pdf(first, second))

    assert reading == Reading("found", "\n".join(first) + "\n\n" + "\n".join(second))


@pytest.mark.parametrize(
    "file",
    [pdf(image_page()), pdf(["1"]), pdf(["1"], ["2"], image_page())],
    ids=["a scanned page", "a page number alone", "page numbers and a scan"],
)
async def test_a_file_with_no_text_to_speak_of_is_none_found(file: bytes) -> None:
    assert await ResumeTextReader().read(file) == Reading("none_found", None)


async def test_text_past_the_cap_is_cut_and_the_pages_after_it_are_never_read() -> None:
    page = [FILLER] * 100  # 6,300 characters a page
    # Three pages run past the cap; the fourth would fail the reading if read.
    file = pdf(page, page, page, bomb_page())

    reading = await ResumeTextReader().read(file)

    assert reading.state == "cut"
    assert reading.text is not None
    assert len(reading.text) <= MAX_RESUME_TEXT_LENGTH
    assert reading.text == cleaned("\n\n".join(["\n".join(page)] * 3)[:MAX_RESUME_TEXT_LENGTH])


async def test_pages_past_the_page_cap_are_never_read_and_make_a_cut() -> None:
    words = [f"Word{number}" for number in range(1, MAX_RESUME_PAGES + 2)]

    reading = await ResumeTextReader().read(pdf(*[[word] for word in words]))

    assert reading == Reading("cut", "\n\n".join(words[:MAX_RESUME_PAGES]))


async def test_a_file_listing_one_page_twenty_thousand_times_reads_within_a_second() -> None:
    reader = ResumeTextReader(cpu_seconds=1)

    assert await reader.read(one_page_many_times(20_000)) == Reading("none_found", None)


def text_before_the_page_cap(file: bytes) -> str:
    """The text the reading gave before it capped its pages and cleaned each page once.

    It joined every page read so far and cleaned them all again after each
    page. Kept here to check the reading still gives the same text.
    """
    reader = PdfReader(io.BytesIO(file))
    if reader.is_encrypted:
        reader.decrypt("")
    pages: list[str] = []
    text = ""
    for page in reader.pages:
        pages.append(page.extract_text(extraction_mode="plain"))
        text = cleaned("\n\n".join(pages))
        if len(text) > MAX_RESUME_TEXT_LENGTH:
            break
    return text


# A page whose lines take the text within 70 characters of the cap: with the
# line breaks around forty empty pages it passes the cap, which the cleaned
# text, losing those blank lines, does not, so a reading stopping there stops
# early and misses the last page.
NEAR_THE_CAP = [FILLER] * 237

READ_BOTH_WAYS = {
    "one page": pdf(resume_lines()),
    "two pages": pdf(resume_lines()[:4], resume_lines()[4:]),
    "a scanned page": pdf(image_page()),
    "a page number alone": pdf(["1"]),
    "page numbers and a scan": pdf(["1"], ["2"], image_page()),
    "past the length cap": pdf([FILLER] * 100, [FILLER] * 100, [FILLER] * 100, bomb_page()),
    "locked only against changes": encrypted(pdf(resume_lines()), user_password=""),
    "forty pages": pdf(*[[FILLER, f"Page {number}", ""] for number in range(40)]),
    "blank lines and line ends": pdf(
        ["", "Avery Example   ", "", "", "", "\tExperience\t"], [" ", FILLER, "  "], ["", ""]
    ),
    "near the cap after empty pages": pdf(
        *[image_page()] * 40, NEAR_THE_CAP, ["Last line of the resume"]
    ),
}


@pytest.mark.parametrize("file", READ_BOTH_WAYS.values(), ids=READ_BOTH_WAYS.keys())
def test_cleaning_each_page_once_reads_what_cleaning_all_after_each_page_did(file: bytes) -> None:
    before = text_before_the_page_cap(file)

    text, pages_unread = text_of(file)

    assert reading_of(text, pages_unread=pages_unread) == reading_of(before)
    if len(before) <= MAX_RESUME_TEXT_LENGTH:
        assert (text, pages_unread) == (before, False)


async def test_a_file_locked_only_against_changes_reads() -> None:
    file = encrypted(pdf(resume_lines()), user_password="")

    assert await ResumeTextReader().read(file) == Reading("found", "\n".join(resume_lines()))


@pytest.mark.parametrize(
    "file",
    [
        encrypted(pdf(resume_lines()), user_password="opens-it"),
        pdf(resume_lines(), bomb_page()),
        b"%PDF-1.7\nnot a file at all\n%%EOF\n",
        b"%PDF-1.7\n" + b" " * MAX_RESUME_BYTES,
    ],
    ids=["needs a password", "a stream that inflates past the cap", "not a PDF", "too large"],
)
async def test_a_file_that_cannot_be_read_fails_and_says_how(
    file: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await ResumeTextReader().read(file)

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading exited with code 1"]


async def test_a_reading_that_runs_too_long_is_killed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pid_file = tmp_path / "pid"
    reader = stub(sleeper(pid_file))
    reader.wall_seconds = 0.5

    began = asyncio.get_running_loop().time()
    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await reader.read(pdf(resume_lines()))
    took = asyncio.get_running_loop().time() - began

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading did not finish within 0.5 seconds"]
    assert took < 5  # the child sleeps a minute: it was killed, not waited out
    assert gone(int(pid_file.read_text()))


async def test_a_reading_that_spins_is_stopped_by_its_processor_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = stub(
        "import sys; from job_board.resumes.text_child import limited;"
        " limited(int(sys.argv[1]), int(sys.argv[2]))\nwhile True: pass"
    )
    reader.cpu_seconds = 1

    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await reader.read(pdf(resume_lines()))

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading ended by signal SIGXCPU"]


async def test_the_reading_process_sets_its_own_processor_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    file = pdf(costly_page())
    assert len(file) <= MAX_RESUME_BYTES
    reader = ResumeTextReader(cpu_seconds=1)

    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await reader.read(file)

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading ended by signal SIGXCPU"]


@pytest.mark.skipif(
    sys.platform == "darwin", reason="macOS does not let a process set an address-space limit"
)
async def test_the_reading_process_sets_its_own_memory_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = ResumeTextReader(address_space_bytes=32 * 1024 * 1024)  # below what pypdf needs

    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await reader.read(pdf(resume_lines()))

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading exited with code 1"]


@pytest.mark.skipif(
    sys.platform == "darwin", reason="macOS does not let a process set an address-space limit"
)
async def test_a_reading_that_takes_too_much_memory_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = stub(
        "import sys; from job_board.resumes.text_child import limited;"
        " limited(int(sys.argv[1]), int(sys.argv[2])); bytearray(1024 * 1024 * 1024)"
    )

    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await reader.read(pdf(resume_lines()))

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading exited with code 1"]


@pytest.mark.skipif(
    sys.platform == "darwin", reason="macOS does not let a process set an address-space limit"
)
async def test_a_long_resume_reads_within_the_memory_limit() -> None:
    page = [FILLER] * 60
    file = pdf(*[page] * 4)

    reading = await ResumeTextReader().read(file)

    assert reading.state == "cut"


@pytest.mark.parametrize(
    "program",
    [
        "print('not an answer')",
        "print('[]')",
        answer("failed", None),
        answer("found", None),
        answer("none_found", FILLER),
        answer("found", ""),
        answer("found", " " + FILLER),
        answer("cut", FILLER + "\x00"),
        answer("found", "x" * (MAX_RESUME_TEXT_LENGTH + 1)),
        answer("found", "1 2 3"),
        'import sys; sys.stdout.write(\'{"state": "found", "text": "a", "more": 1}\')',
        'import sys; sys.stdout.buffer.write(b\'{"state": "found", "text": "\\xff"}\')',
        "import sys; sys.stdout.write('[' * 50000)",
    ],
    ids=[
        "not JSON",
        "not an object",
        "a state only the parent gives",
        "found without text",
        "none found with text",
        "empty text",
        "text the rules would trim",
        "text the rules would refuse",
        "text past the cap",
        "too few letters",
        "a key too many",
        "not UTF-8",
        "nested past the recursion limit",
    ],
)
async def test_an_answer_the_parent_cannot_check_fails(
    program: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await stub(program).read(pdf(resume_lines()))

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading answered in the wrong shape"]


async def test_an_answer_past_its_bound_is_not_read_on(caplog: pytest.LogCaptureFixture) -> None:
    program = f"import sys; sys.stdout.write('x' * {LONGEST_ANSWER_BYTES + 1}); sys.stdout.flush()"
    program += "\nimport time; time.sleep(60)"

    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await stub(program).read(pdf(resume_lines()))

    assert reading == FAILED
    assert logged(caplog) == [
        f"resume text reading answered more than {LONGEST_ANSWER_BYTES} bytes"
    ]


async def test_the_bound_holds_the_longest_answer_the_cap_allows() -> None:
    # Four bytes is the most UTF-8 spends on a character, and JSON escapes a
    # quote or a backslash into two.
    longest = "\U0001f600" * (MAX_RESUME_TEXT_LENGTH - 50) + "a" * 50
    spelled = json.dumps({"state": "found", "text": longest}, ensure_ascii=False)
    assert len(spelled.encode()) <= LONGEST_ANSWER_BYTES

    reading = await stub(f"import sys; sys.stdout.write({spelled!r})").read(pdf(resume_lines()))

    assert reading == Reading("found", longest)


async def test_an_ending_that_is_not_a_clean_exit_fails(caplog: pytest.LogCaptureFixture) -> None:
    program = answer("found", FILLER) + "; sys.stdout.flush(); sys.exit(3)"

    with caplog.at_level(logging.WARNING, logger=OURS):
        reading = await stub(program).read(pdf(resume_lines()))

    assert reading == FAILED
    assert logged(caplog) == ["resume text reading exited with code 3"]


async def test_a_reading_that_never_reads_its_file_still_answers() -> None:
    reading = await stub(answer("found", FILLER)).read(b"%PDF-" + b"x" * MAX_RESUME_BYTES)

    assert reading == Reading("found", FILLER)


async def test_a_cancelled_reading_leaves_no_process_and_frees_the_next(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    reader = stub(sleeper(pid_file))
    reading = asyncio.create_task(reader.read(pdf(resume_lines())))
    pid = await started(pid_file)

    reading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reading

    assert gone(pid)
    reader.command = (sys.executable, "-I", "-c", answer("found", FILLER))
    assert await reader.read(pdf(resume_lines())) == Reading("found", FILLER)


async def test_two_readings_at_once_run_one_after_the_other(tmp_path: Path) -> None:
    turns = tmp_path / "turns"
    program = (
        f"import os, time; log = open({str(turns)!r}, 'a')\n"
        "log.write(f'start {os.getpid()}\\n'); log.flush(); time.sleep(0.3)\n"
        "log.write(f'end {os.getpid()}\\n'); log.flush()\n"
    ) + answer("found", FILLER)
    reader = stub(program)

    readings = await asyncio.gather(*(reader.read(pdf(resume_lines())) for _ in range(2)))

    assert readings == [Reading("found", FILLER)] * 2
    steps = [line.split() for line in turns.read_text().splitlines()]
    assert [step for step, _ in steps] == ["start", "end", "start", "end"]
    assert steps[0][1] == steps[1][1] and steps[2][1] == steps[3][1]


async def test_the_reading_sees_no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUME_TEXT_READING_TEST", "visible")
    # Python sets LC_CTYPE itself when it starts with no locale at all, and
    # macOS sets __CF_USER_TEXT_ENCODING in every process it starts.
    program = (
        "import json, os, sys\n"
        "added = {'LC_CTYPE', '__CF_USER_TEXT_ENCODING'}\n"
        "seen = ' '.join(sorted(set(os.environ) - added))\n"
        f"text = ({FILLER!r} + ' ' + seen).strip()\n"
        "sys.stdout.write(json.dumps({'state': 'found', 'text': text}))"
    )

    reading = await stub(program).read(pdf(resume_lines()))

    assert reading == Reading("found", FILLER)


def test_the_reading_loads_nothing_of_the_web_framework_the_database_or_the_settings() -> None:
    program = (
        "import sys\n"
        "import job_board.resumes.text_child as child\n"
        "before = 'pypdf' in sys.modules\n"
        "code = child.main(sys.argv[1:])\n"
        "sys.stderr.write(repr((before, code, sorted(sys.modules))))\n"
    )
    finished = subprocess.run(
        [sys.executable, "-I", "-c", program, "10", str(256 * 1024 * 1024), str(MAX_RESUME_BYTES)],
        input=pdf(resume_lines()),
        capture_output=True,
        check=True,
        env={},
    )

    pypdf_before_limits, code, modules = ast.literal_eval(finished.stderr.decode())
    assert (pypdf_before_limits, code) == (False, 0)
    assert json.loads(finished.stdout) == {"state": "found", "text": "\n".join(resume_lines())}
    loaded = [
        name
        for name in modules
        if any(name == banned or name.startswith(f"{banned}.") for banned in NEVER_IMPORTED)
        or name == "job_board.settings"
    ]
    assert loaded == []
