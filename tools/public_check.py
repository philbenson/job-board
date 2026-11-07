#!/usr/bin/env python3
"""Keep private names and personal contact details out of this public repository.

Invariant: no tracked file, file path, commit message or commit identity names
the private companion repository or carries a personal email address or phone
number. The git hooks in .githooks run this on every local commit and the
public-check workflow runs it on every push.

It runs on the standard library of Python 3.9 or newer, because the hooks start
whatever python3 is on the PATH and macOS still ships 3.9.

Its output may land in a public CI log, so a finding never repeats what it
found: it prints a location, a rule and a redacted form, and a path that holds
a finding is printed with that part masked.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# The private repository's name is never written here in any spelling; only
# SHA-256 hashes of its words joined with hyphens and joined with nothing.
PRIVATE_NAME_HASHES = frozenset(
    {
        "7781e9d11c675d2f8ae103ea9b15d3c604166794ebc8a3f8c12bd845e274b672",
        "49be571d794b8ab0f838052f6162a9b367c39f427acc05b8e466a20020d80b69",
    }
)
PRIVATE_NAME_WORDS = 3

BINARY_SNIFF_BYTES = 8192  # git's own heuristic: a NUL in the first 8 KB marks a binary file
MASK = "***"

EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"(?P<local>[A-Za-z0-9._%+-]+)@"
    r"(?P<domain>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})"
    r"(?![A-Za-z0-9-])"
)
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
ALLOWED_EMAIL_SUFFIX = "users.noreply.github.com"
ALLOWED_EMAIL_ADDRESSES = frozenset({"noreply@github.com"})

# Neither shape may touch a letter, digit or underscore, or sit beside a dot
# that joins it to more digits: dates, versions, addresses, hashes and
# lock-file integrity strings stay quiet, while a number ending a sentence
# is still found.
_BEFORE = r"(?<![\w+])(?<!\d\.)"
_AFTER = r"(?![\w])(?!\.\d)"
PHONE = re.compile(
    _BEFORE
    + r"(?:"
    + r"(?:\+1[ .-]?)?(?:\(\d{3}\) ?|\d{3}[ .-])\d{3}[ .-]\d{4}"  # North American, with separators
    + r"|\+\d{10,15}"  # international, digits only
    + r")"
    + _AFTER
)
FICTIONAL_EXCHANGE = "555"
FICTIONAL_LINES = range(100, 200)  # 555-0100 to 555-0199 are reserved for fiction

_WORD = re.compile(r"[A-Za-z0-9]+")
# git commit --verbose puts the diff below this line
SCISSORS = "------------------------ >8 ------------------------"


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    rule: str
    redacted: str


@dataclass(frozen=True)
class Finding:
    location: str
    rule: str
    redacted: str

    def __str__(self) -> str:
        return f"{self.location}: {self.rule}: {self.redacted}"


def _name_matches(text: str, name_hashes: frozenset[str], name_words: int) -> Iterator[Match]:
    """Find the name in any spelling: any case, any separators, or run together.

    The text is lowercased and split into words at every character outside
    a-z0-9. Every window of up to ``name_words`` consecutive words is hashed
    joined with nothing, and every full-length window joined with hyphens, so
    "a-b-c", "A_B C", "ABC" and "ab-c" are all caught.
    """
    words = [(word.group().lower(), word.start(), word.end()) for word in _WORD.finditer(text)]
    for first in range(len(words)):
        for size in range(1, name_words + 1):
            window = words[first : first + size]
            if len(window) < size:
                break
            spellings = ["".join(word for word, _, _ in window)]
            if size == name_words:
                spellings.append("-".join(word for word, _, _ in window))
            if any(
                hashlib.sha256(spelling.encode()).hexdigest() in name_hashes
                for spelling in spellings
            ):
                yield Match(window[0][1], window[-1][2], "private-name", "(withheld)")
                break


def _email_allowed(local: str, domain: str) -> bool:
    domain = domain.lower()
    if f"{local.lower()}@{domain}" in ALLOWED_EMAIL_ADDRESSES:
        return True
    if domain == ALLOWED_EMAIL_SUFFIX or domain.endswith("." + ALLOWED_EMAIL_SUFFIX):
        return True
    return any(
        domain == allowed or domain.endswith("." + allowed) for allowed in ALLOWED_EMAIL_DOMAINS
    )


def _email_matches(text: str) -> Iterator[Match]:
    for email in EMAIL.finditer(text):
        local, domain = email.group("local"), email.group("domain")
        if not _email_allowed(local, domain):
            yield Match(
                email.start(), email.end(), "email-address", f"{local[0]}***@{domain[0]}***"
            )


def _phone_allowed(digits: str) -> bool:
    national = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
    return (
        len(national) == 10
        and national[3:6] == FICTIONAL_EXCHANGE
        and int(national[6:]) in FICTIONAL_LINES
    )


def _phone_matches(text: str) -> Iterator[Match]:
    for phone in PHONE.finditer(text):
        digits = re.sub(r"\D", "", phone.group())
        if not _phone_allowed(digits):
            yield Match(phone.start(), phone.end(), "phone-number", MASK + digits[-2:])


def _matches(text: str, name_hashes: frozenset[str], name_words: int) -> list[Match]:
    found = [
        *_name_matches(text, name_hashes, name_words),
        *_email_matches(text),
        *_phone_matches(text),
    ]
    return sorted(found, key=lambda match: match.start)


def mask(
    text: str,
    name_hashes: frozenset[str] = PRIVATE_NAME_HASHES,
    name_words: int = PRIVATE_NAME_WORDS,
) -> str:
    """The text with every finding replaced by a mask, safe to print."""
    masked, position = [], 0
    for match in _matches(text, name_hashes, name_words):
        if match.start >= position:
            masked.append(text[position : match.start] + MASK)
            position = match.end
    return "".join(masked) + text[position:]


def scan_text(
    text: str,
    location: str,
    name_hashes: frozenset[str] = PRIVATE_NAME_HASHES,
    name_words: int = PRIVATE_NAME_WORDS,
) -> list[Finding]:
    """Every finding in the text, located as ``location:line``."""
    line_starts = [0] + [index + 1 for index, character in enumerate(text) if character == "\n"]
    return [
        Finding(
            f"{location}:{bisect.bisect_right(line_starts, match.start)}",
            match.rule,
            match.redacted,
        )
        for match in _matches(text, name_hashes, name_words)
    ]


def scan_path(
    path: str,
    name_hashes: frozenset[str] = PRIVATE_NAME_HASHES,
    name_words: int = PRIVATE_NAME_WORDS,
) -> list[Finding]:
    """Findings in a file's path itself, printed with the findings masked."""
    location = f"{mask(path, name_hashes, name_words)} (path)"
    return [
        Finding(location, match.rule, match.redacted)
        for match in _matches(path, name_hashes, name_words)
    ]


def decode_text(content: bytes) -> str | None:
    """The content as text, or None for a file the check skips as binary."""
    if b"\x00" in content[:BINARY_SNIFF_BYTES]:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


class UsageError(Exception):
    """A problem with how the check was run, as opposed to a finding."""


@dataclass
class Tally:
    files: int = 0
    commits: int = 0
    skipped: int = 0


def _git(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(["git", *arguments], cwd=repository, capture_output=True)
    if result.returncode != 0:
        # git's errors quote paths, which may hold a finding
        message = mask(result.stderr.decode("utf-8", "replace").strip())
        raise UsageError(f"git {arguments[0]} failed: {message}")
    return result.stdout


def _top_level() -> Path:
    try:
        output = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    except UsageError as error:
        raise UsageError(f"not inside a git working tree ({error})") from error
    return Path(output.decode("utf-8").strip())


def _split_nul(output: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in output.split(b"\x00") if item]


def _scan_file(path: str, content: bytes, tally: Tally) -> Iterator[Finding]:
    tally.files += 1
    yield from scan_path(path)
    text = decode_text(content)
    if text is None:
        tally.skipped += 1
        return
    yield from scan_text(text, mask(path))


def check_staged(tally: Tally) -> Iterator[Finding]:
    """The path and staged content of every added, copied, modified or renamed file."""
    repository = _top_level()
    staged = _git(repository, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    for path in _split_nul(staged):
        yield from _scan_file(path, _git(repository, "show", f":{path}"), tally)


def check_tracked(tally: Tally) -> Iterator[Finding]:
    """The path and working-tree content of every tracked file."""
    repository = _top_level()
    for path in _split_nul(_git(repository, "ls-files", "-z")):
        target = repository / path
        if target.is_symlink():
            content = os.readlink(target).encode("utf-8", "surrogateescape")
        elif target.is_file():
            content = target.read_bytes()
        else:
            continue  # deleted from the working tree, or a submodule
        yield from _scan_file(path, content, tally)


def message_text(raw: str) -> str:
    """A commit message as git records it: no comment lines, nothing below the scissors."""
    lines = []
    for line in raw.splitlines():
        if line.startswith("#") and line[1:].strip() == SCISSORS:
            break
        if not line.startswith("#"):
            lines.append(line)
    return "\n".join(lines)


def check_message(path: str, tally: Tally) -> Iterator[Finding]:
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise UsageError(f"cannot read the message file: {error.strerror}") from error
    tally.commits += 1
    yield from scan_text(message_text(raw), "commit message")


def check_history(tally: Tally) -> Iterator[Finding]:
    """The message, author and committer of every commit reachable from HEAD."""
    repository = _top_level()
    has_head = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=repository, capture_output=True
    )
    if has_head.returncode != 0:
        return
    fields = ("%H", "%an <%ae>", "%cn <%ce>", "%B")
    output = _git(repository, "log", "-z", "--format=" + "%x00".join(fields), "HEAD")
    values = output.decode("utf-8", "replace").split("\x00")
    for index in range(0, len(values) - len(fields) + 1, len(fields)):
        commit, author, committer, message = values[index : index + len(fields)]
        tally.commits += 1
        label = f"commit {commit[:12]}"
        for role, identity in (("author", author), ("committer", committer)):
            for finding in scan_text(identity, label):
                yield Finding(f"{label} {role}", finding.rule, finding.redacted)
        yield from scan_text(message, f"{label} message")


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find private names and personal contact details before they become public."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="the files staged for the next commit")
    mode.add_argument(
        "--message-file",
        metavar="PATH",
        help="a commit message, as the commit-msg hook receives it",
    )
    mode.add_argument(
        "--tracked", action="store_true", help="every tracked file in the working tree"
    )
    mode.add_argument("--history", action="store_true", help="every commit reachable from HEAD")
    return parser.parse_args(argv)


def _findings(arguments: argparse.Namespace, tally: Tally) -> Iterable[Finding]:
    if arguments.staged:
        return check_staged(tally)
    if arguments.message_file is not None:
        return check_message(arguments.message_file, tally)
    if arguments.tracked:
        return check_tracked(tally)
    return check_history(tally)


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 0 when clean, 1 with findings, 2 when the check could not run."""
    arguments = _parse(argv)
    tally = Tally()
    count = 0
    try:
        for finding in _findings(arguments, tally):
            count += 1
            print(finding)
    except UsageError as error:
        print(f"public check: {error}", file=sys.stderr)
        return 2
    print(
        f"public check: {tally.files} files, {tally.commits} commits, "
        f"{count} findings, {tally.skipped} skipped as binary"
    )
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main())
