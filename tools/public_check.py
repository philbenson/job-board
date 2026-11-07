#!/usr/bin/env python3
"""Keep private names and personal contact details out of this public repository.

Invariant: no tracked file, file path, commit message, commit identity or ref
name names the private companion repository or carries a personal email
address or phone number. The git hooks in .githooks run this on every local
commit and push, before the remote has anything, and the public-check workflow
runs it over the whole history on every push.

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
ALLOWED_EMAIL_ADDRESSES = frozenset({"noreply@github.com", "git@github.com"})

# Neither shape may touch a letter, digit or underscore, or sit beside a dot
# that joins it to more digits: dates, versions, addresses, hashes and
# lock-file integrity strings stay quiet, while a number ending a sentence
# is still found. A North American area code and exchange start with 2 to 9,
# so runs such as 100-200-3000 are not numbers.
_BEFORE = r"(?<![\w+])(?<!\d\.)"
_AFTER = r"(?![\w])(?!\.\d)"
PHONE = re.compile(
    _BEFORE
    + r"(?:"
    + r"(?:\+1[ .-]?)?(?:\([2-9]\d\d\) ?|[2-9]\d\d[ .-])[2-9]\d\d[ .-]\d{4}"  # North American
    + r"|\+\d{10,15}"  # international, digits only
    + r")"
    + _AFTER
)
FICTIONAL_EXCHANGE = "555"
FICTIONAL_LINES = range(100, 200)  # 555-0100 to 555-0199 are reserved for fiction

_WORD = re.compile(r"[A-Za-z0-9]+")
_LINE = re.compile(r"[^\n]+")
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
    """Find the name in any spelling on one line: any case, any separators, or run together.

    Each line is lowercased and split into words at every character outside
    a-z0-9. Every window of up to ``name_words`` consecutive words is hashed
    joined with nothing, and every full-length window joined with hyphens, so
    "a-b-c", "A_B C", "a_b.c", "ABC" and "ab-c" are all caught. A window never
    spans a line break, so the words on separate lines or headings are not a
    finding.
    """
    for line in _LINE.finditer(text):
        yield from _name_matches_in_line(line, name_hashes, name_words)


def _name_matches_in_line(
    line: re.Match[str], name_hashes: frozenset[str], name_words: int
) -> Iterator[Match]:
    offset = line.start()
    words = [
        (word.group().lower(), offset + word.start(), offset + word.end())
        for word in _WORD.finditer(line.group())
    ]
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
    """The text with every finding replaced by a mask, safe to print.

    Findings that overlap, such as the name run into an email address, are
    merged into one masked span, so no tail of either is printed.
    """
    masked, position = [], 0
    for match in _matches(text, name_hashes, name_words):
        if match.start >= position:
            masked.append(text[position : match.start] + MASK)
        position = max(position, match.end)
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
    kind: str = "path",
) -> list[Finding]:
    """Findings in a name itself, a file path or a ref, printed with the findings masked."""
    location = f"{mask(path, name_hashes, name_words)} ({kind})"
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
    refs: int = 0
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
    """A commit message up to the scissors line, comment lines included.

    git strips lines starting with # only when it opens an editor; for
    ``git commit -m`` and ``-F`` it keeps them, so they are scanned too.
    """
    lines = []
    for line in raw.splitlines():
        if line.startswith("#") and line[1:].strip() == SCISSORS:
            break
        lines.append(line)
    return "\n".join(lines)


def check_message(path: str, tally: Tally) -> Iterator[Finding]:
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise UsageError(f"cannot read the message file: {error.strerror}") from error
    tally.commits += 1
    yield from scan_text(message_text(raw), "commit message")


def _commit_exists(repository: Path, revision: str) -> bool:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        cwd=repository,
        capture_output=True,
    )
    return found.returncode == 0


def _check_messages(repository: Path, revisions: list[str], tally: Tally) -> Iterator[Finding]:
    """The message, author and committer of every commit in the revisions."""
    fields = ("%H", "%an <%ae>", "%cn <%ce>", "%B")
    output = _git(repository, "log", "-z", "--format=" + "%x00".join(fields), *revisions)
    values = output.decode("utf-8", "replace").split("\x00")
    for index in range(0, len(values) - len(fields) + 1, len(fields)):
        commit, author, committer, message = values[index : index + len(fields)]
        tally.commits += 1
        label = f"commit {commit[:12]}"
        for role, identity in (("author", author), ("committer", committer)):
            for finding in scan_text(identity, label):
                yield Finding(f"{label} {role}", finding.rule, finding.redacted)
        yield from scan_text(message, f"{label} message")


def _check_paths(repository: Path, revisions: list[str]) -> Iterator[Finding]:
    """Every path any commit in the revisions adds or changes, each once.

    Every path in a commit's tree was added by that commit or an ancestor, so
    the paths each commit changes, renames counted as additions and merges
    against each parent, cover every path the commits reach.
    """
    output = _git(
        repository,
        "log",
        "-z",
        "--format=",
        "--name-only",
        "--no-renames",
        "-m",
        "--root",
        *revisions,
    )
    for path in sorted(set(_split_nul(output))):
        yield from scan_path(path)


def _check_blobs(repository: Path, revisions: list[str], tally: Tally) -> Iterator[Finding]:
    """The content of every file version the revisions reach, each blob once.

    git rev-list lists each object once, and git cat-file streams them, so the
    memory held is one blob at a time, whatever the history's size.
    """
    listing = subprocess.Popen(
        ["git", "rev-list", "--objects", "--filter=object:type=blob", *revisions],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    reader = subprocess.Popen(
        ["git", "cat-file", "--batch=%(objectname) %(objecttype) %(objectsize) %(rest)"],
        cwd=repository,
        stdin=listing.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert listing.stdout is not None and reader.stdout is not None
    listing.stdout.close()  # cat-file owns the pipe now
    try:
        while True:
            header = reader.stdout.readline()
            if not header:
                break
            parts = header.decode("utf-8", "surrogateescape").rstrip("\n").split(" ", 3)
            if len(parts) < 3:
                raise UsageError("git cat-file could not read an object")
            name, kind, size = parts[0], parts[1], int(parts[2])
            content = reader.stdout.read(size)
            reader.stdout.read(1)  # the newline after each object
            if kind != "blob":
                continue  # rev-list's filter still lists the commits themselves
            path = parts[3] if len(parts) > 3 else ""
            tally.files += 1
            text = decode_text(content)
            if text is None:
                tally.skipped += 1
                continue
            yield from scan_text(text, f"{mask(path)} (blob {name[:12]})")
    finally:
        reader.stdout.close()
        failures = [
            process.stderr.read().decode("utf-8", "replace").strip()
            for process in (listing, reader)
            if process.wait() != 0 and process.stderr is not None
        ]
        for process in (listing, reader):
            if process.stderr is not None:
                process.stderr.close()
    if failures:
        raise UsageError(f"git could not list the history's files: {mask(failures[0])}")


def _check_commits(repository: Path, revisions: list[str], tally: Tally) -> Iterator[Finding]:
    yield from _check_messages(repository, revisions, tally)
    yield from _check_paths(repository, revisions)
    yield from _check_blobs(repository, revisions, tally)


def check_history(tally: Tally) -> Iterator[Finding]:
    """Every commit reachable from HEAD: messages, identities, and every path and file version."""
    repository = _top_level()
    if not _commit_exists(repository, "HEAD"):
        return
    yield from _check_commits(repository, ["HEAD"], tally)


def _is_no_commit(sha: str) -> bool:
    return set(sha) == {"0"}


def check_pushed(remote: str, lines: Iterable[str], tally: Tally) -> Iterator[Finding]:
    """What a push would publish, as the pre-push hook describes it.

    Each line is ``<local ref> <local sha> <remote ref> <remote sha>``. A
    deletion publishes nothing and is skipped. Otherwise the remote ref name is
    checked, and so is every commit the push sends that the remote is not known
    to have: not reachable from the remote's tracking refs or from the remote's
    current commit, when that commit is here.
    """
    repository = _top_level()
    sending, known = [], []
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4:
            raise UsageError(
                "each line on standard input must be "
                "'<local ref> <local sha> <remote ref> <remote sha>'"
            )
        _, local_sha, remote_ref, remote_sha = fields
        if _is_no_commit(local_sha):
            continue
        tally.refs += 1
        yield from scan_path(remote_ref, kind="ref")
        sending.append(local_sha)
        if not _is_no_commit(remote_sha) and _commit_exists(repository, remote_sha):
            known.append(remote_sha)
    if sending:
        revisions = [*sending, "--not", f"--remotes={remote}", *known]
        yield from _check_commits(repository, revisions, tally)


def check_refs(tally: Tally) -> Iterator[Finding]:
    """The name of every branch, tag and remote-tracking ref."""
    repository = _top_level()
    for ref in _git(repository, "for-each-ref", "--format=%(refname)").decode().splitlines():
        tally.refs += 1
        yield from scan_path(ref, kind="ref")


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
    mode.add_argument(
        "--history",
        action="store_true",
        help="every commit reachable from HEAD, with every path and file version it reaches",
    )
    mode.add_argument(
        "--pushed",
        metavar="REMOTE",
        help="what a push sends (the pre-push hook), with git's ref lines on standard input",
    )
    mode.add_argument("--refs", action="store_true", help="every branch, tag and remote ref name")
    return parser.parse_args(argv)


def _findings(arguments: argparse.Namespace, tally: Tally) -> Iterable[Finding]:
    if arguments.staged:
        return check_staged(tally)
    if arguments.message_file is not None:
        return check_message(arguments.message_file, tally)
    if arguments.tracked:
        return check_tracked(tally)
    if arguments.pushed is not None:
        return check_pushed(arguments.pushed, sys.stdin.read().splitlines(), tally)
    if arguments.refs:
        return check_refs(tally)
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
        f"public check: {tally.files} files, {tally.commits} commits, {tally.refs} refs, "
        f"{count} findings, {tally.skipped} skipped as binary"
    )
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main())
