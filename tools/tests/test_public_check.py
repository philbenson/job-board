"""Tests for the public-content check.

Every positive case is assembled at run time from pieces (see ``joined``), so
this file never holds a complete finding itself and the check passes over it
like any other tracked file. The private-name rule is tested with a made-up
name and hashes computed here: the real name appears nowhere in this file.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
REPOSITORY = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import public_check  # noqa: E402

SCRIPT = TOOLS / "public_check.py"

MADE_UP_NAME = ("alpha", "bravo", "charlie")
MADE_UP_HASHES = frozenset(
    hashlib.sha256(separator.join(MADE_UP_NAME).encode()).hexdigest() for separator in ("-", "")
)


def joined(*parts: str) -> str:
    """Assemble a test value from pieces that are each harmless alone."""
    return "".join(parts)


def scan(text: str) -> list[public_check.Finding]:
    return public_check.scan_text(
        text, "sample.txt", name_hashes=MADE_UP_HASHES, name_words=len(MADE_UP_NAME)
    )


def rules(text: str) -> list[str]:
    return [finding.rule for finding in scan(text)]


class PrivateNameTest(unittest.TestCase):
    def test_finds_every_spelling(self) -> None:
        spellings = [
            "alpha-bravo-charlie",
            "alpha_bravo_charlie",
            "Alpha Bravo Charlie",
            "ALPHA-bravo_Charlie",
            "AlphaBravoCharlie",
            "alphabravo-charlie",
            "alpha bravocharlie",
            "see ../alpha-bravo-charlie/plans/first.md",
            "alpha\nbravo\ncharlie",
        ]
        for spelling in spellings:
            with self.subTest(spelling=spelling):
                self.assertEqual(rules(spelling), ["private-name"])

    def test_ignores_near_misses(self) -> None:
        for text in [
            "alpha bravo delta",
            "alpha-bravo",
            "bravo charlie alpha",
            "alphabet bravo charlie",
        ]:
            with self.subTest(text=text):
                self.assertEqual(rules(text), [])

    def test_never_prints_the_name(self) -> None:
        findings = scan("notes live in Alpha_Bravo_Charlie/plans")
        self.assertEqual(len(findings), 1)
        printed = str(findings[0]).lower()
        for word in MADE_UP_NAME:
            self.assertNotIn(word, printed)

    def test_a_path_is_printed_with_the_name_masked(self) -> None:
        findings = public_check.scan_path(
            "docs/Alpha_Bravo_Charlie/plan.md",
            name_hashes=MADE_UP_HASHES,
            name_words=len(MADE_UP_NAME),
        )
        self.assertEqual(
            [str(finding) for finding in findings],
            ["docs/***/plan.md (path): private-name: (withheld)"],
        )

    def test_reports_the_line_the_name_starts_on(self) -> None:
        findings = scan("first line\nsecond alpha-bravo-charlie\n")
        self.assertEqual(findings[0].location, "sample.txt:2")

    def test_the_real_hashes_are_the_default(self) -> None:
        self.assertEqual(len(public_check.PRIVATE_NAME_HASHES), 2)
        self.assertEqual(public_check.scan_text("alpha-bravo-charlie", "sample.txt"), [])


class EmailTest(unittest.TestCase):
    def test_finds_a_personal_address(self) -> None:
        for address in [
            joined("jane.doe", "@", "mail.invalid"),
            joined("someone", "@", "notexample.com"),
            joined("someone", "@", "example.com.invalid"),
            joined("other", "@", "github.com"),
            joined("x", "@", "noreply.github.com"),
        ]:
            with self.subTest(address=address):
                self.assertEqual(rules("contact " + address + " today"), ["email-address"])

    def test_allows_documentation_and_no_reply_addresses(self) -> None:
        for address in [
            joined("jane", "@", "example.com"),
            joined("jane", "@", "mail.example.org"),
            joined("jane", "@", "example.net"),
            joined("12345+someone", "@", "users.noreply.github.com"),
            joined("noreply", "@", "github.com"),
        ]:
            with self.subTest(address=address):
                self.assertEqual(rules("contact " + address), [])

    def test_ignores_shapes_that_are_not_addresses(self) -> None:
        for text in [
            "uses: actions/checkout@v7",
            "go run example/cmd/tool@v1.7.12",
            "@pytest.fixture",
            "a @ b.com",
        ]:
            with self.subTest(text=text):
                self.assertEqual(rules(text), [])

    def test_prints_only_a_redacted_form(self) -> None:
        findings = scan(joined("jane.doe", "@", "gmail.invalid"))
        printed = str(findings[0])
        self.assertIn("j***@g***", printed)
        self.assertNotIn("jane", printed)
        self.assertNotIn("gmail", printed)


class PhoneTest(unittest.TestCase):
    def test_finds_every_shape(self) -> None:
        for number in [
            joined("(212)", " 555-0234"),
            joined("212", "-555-0234"),
            joined("212", ".555.0234"),
            joined("+1 212", " 555 0234"),
            joined("+4479", "11123456"),
            joined("call 212", "-555-0234."),
        ]:
            with self.subTest(number=number):
                self.assertEqual(rules(number), ["phone-number"])

    def test_allows_the_fictional_range(self) -> None:
        for number in [
            joined("(212)", " 555-0100"),
            joined("212", "-555-0199"),
            joined("+1 212", " 555 0150"),
            joined("+1212", "5550142"),
        ]:
            with self.subTest(number=number):
                self.assertEqual(rules(number), [])

    def test_ignores_dates_versions_and_hashes(self) -> None:
        for text in [
            "released 2026-11-07 at 10:36",
            "version 212.555.0234.4",
            "address 10.212.555.0234",
            "commit 3a212-555-0234b",
            joined("sha512-AbC+1234", "5678902344/xyz=="),
            "id 1212555023445678901",
            "+12345",
            "212-555-012",
        ]:
            with self.subTest(text=text):
                self.assertEqual(rules(text), [])

    def test_prints_only_the_last_two_digits(self) -> None:
        findings = scan(joined("212", "-555-0287"))
        printed = str(findings[0])
        self.assertIn("87", printed)
        self.assertNotIn("0287", printed)
        self.assertNotIn("212", printed)


def git_environment(home: str) -> dict[str, str]:
    """An environment in which git sees only the test's own repository.

    Inherited repository and identity variables would point git at the real
    checkout or stamp real identities; user and system configuration could add
    hooks or rewrite paths. All of it is cleared, and identities use example.com.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        {
            "HOME": home,
            "XDG_CONFIG_HOME": home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": "author@example.com",
            "GIT_COMMITTER_NAME": "Test Committer",
            "GIT_COMMITTER_EMAIL": "committer@example.com",
        }
    )
    return environment


class RepositoryTestCase(unittest.TestCase):
    """A throwaway git repository per test, removed afterwards."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="public-check-"))
        self.addCleanup(shutil.rmtree, self.folder)
        self.environment = git_environment(str(self.folder / "home"))
        self.repository = self.folder / "repository"
        self.repository.mkdir()
        self.git("init", "--quiet")

    def git(self, *arguments: str, environment: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            env=environment or self.environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def write(self, path: str, content: str | bytes) -> None:
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    def commit(self, message: str, **identity: str) -> None:
        """Record the index as a commit without running any hooks."""
        environment = dict(self.environment, **identity)
        tree = self.git("write-tree")
        parents = []
        if (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
                cwd=self.repository,
                env=self.environment,
                capture_output=True,
            ).returncode
            == 0
        ):
            parents = ["-p", self.git("rev-parse", "HEAD")]
        commit = self.git("commit-tree", tree, *parents, "-m", message, environment=environment)
        self.git("update-ref", "HEAD", commit)

    def check(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
        )


class StagedModeTest(RepositoryTestCase):
    def test_clean_staged_files_pass(self) -> None:
        self.write("notes.md", "write to someone@example.com\n")
        self.git("add", "notes.md")
        result = self.check("--staged")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 files, 0 commits, 0 findings, 0 skipped as binary", result.stdout)

    def test_reads_the_staged_content_not_the_working_tree(self) -> None:
        self.write("notes.md", joined("call 212", "-555-0234\n"))
        self.git("add", "notes.md")
        self.write("notes.md", "fixed in the working tree only\n")
        result = self.check("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("notes.md:1: phone-number: ***34", result.stdout)
        self.assertNotIn("0234", result.stdout)

    def test_checks_the_path_of_a_renamed_file(self) -> None:
        self.write("plain.md", "nothing here\n")
        self.git("add", "plain.md")
        self.commit("add a file")
        self.git("mv", "plain.md", joined("someone", "@", "mail.invalid.md"))
        result = self.check("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("*** (path): email-address: s***@m***", result.stdout)
        self.assertNotIn("someone", result.stdout)

    def test_skips_deleted_and_binary_files(self) -> None:
        self.write("gone.md", joined("call 212", "-555-0234\n"))
        self.git("add", "gone.md")
        self.commit("add a file")
        self.git("rm", "--quiet", "gone.md")
        self.write("image.bin", b"\x89PNG\x00" + joined("212", "-555-0234").encode())
        self.write("latin.txt", joined("212", "-555-0234 caf\xe9").encode("latin-1"))
        self.git("add", "image.bin", "latin.txt")
        result = self.check("--staged")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("2 files, 0 commits, 0 findings, 2 skipped as binary", result.stdout)


class MessageModeTest(RepositoryTestCase):
    def test_finds_an_address_in_the_message(self) -> None:
        self.write("message.txt", joined("ask jane", "@", "mail.invalid\n"))
        result = self.check("--message-file", "message.txt")
        self.assertEqual(result.returncode, 1)
        self.assertIn("commit message:1: email-address: j***@m***", result.stdout)

    def test_ignores_comment_lines_and_the_diff_below_the_scissors(self) -> None:
        message = "\n".join(
            [
                "add the health route",
                joined("# call 212", "-555-0234"),
                "# ------------------------ >8 ------------------------",
                joined("+ contact jane", "@", "mail.invalid"),
                "",
            ]
        )
        self.write("message.txt", message)
        result = self.check("--message-file", "message.txt")
        self.assertEqual(result.returncode, 0, result.stdout)


class TrackedModeTest(RepositoryTestCase):
    def test_checks_every_tracked_file_and_ignores_untracked_ones(self) -> None:
        self.write("clean.md", "nothing here\n")
        self.write("dirty/notes.md", joined("line one\nemail jane", "@", "mail.invalid\n"))
        self.write("untracked.md", joined("call 212", "-555-0234\n"))
        self.git("add", "clean.md", "dirty/notes.md")
        result = self.check("--tracked")
        self.assertEqual(result.returncode, 1)
        self.assertIn("dirty/notes.md:2: email-address: j***@m***", result.stdout)
        self.assertNotIn("untracked.md", result.stdout)
        self.assertIn("2 files, 0 commits, 1 findings, 0 skipped as binary", result.stdout)

    def test_works_from_a_subfolder(self) -> None:
        self.write("sub/clean.md", "nothing here\n")
        self.git("add", "sub/clean.md")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--tracked"],
            cwd=self.repository / "sub",
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 files, 0 commits, 0 findings", result.stdout)


class HistoryModeTest(RepositoryTestCase):
    def test_checks_messages_and_identities_of_every_commit(self) -> None:
        self.write("a.md", "a\n")
        self.git("add", "a.md")
        self.commit("first commit")
        self.write("b.md", "b\n")
        self.git("add", "b.md")
        self.commit(
            "second commit",
            GIT_AUTHOR_EMAIL=joined("jane", "@", "mail.invalid"),
        )
        self.commit(joined("third commit, call 212", "-555-0234"))
        result = self.check("--history")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(
            result.stdout, r"commit [0-9a-f]{12} author: email-address: j\*\*\*@m\*\*\*"
        )
        self.assertRegex(result.stdout, r"commit [0-9a-f]{12} message:1: phone-number: \*\*\*34")
        self.assertIn("0 files, 3 commits, 2 findings", result.stdout)

    def test_an_empty_repository_has_no_history(self) -> None:
        result = self.check("--history")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 files, 0 commits, 0 findings", result.stdout)


class UsageTest(RepositoryTestCase):
    def test_a_mode_is_required(self) -> None:
        self.assertEqual(self.check().returncode, 2)

    def test_modes_are_exclusive(self) -> None:
        self.assertEqual(self.check("--tracked", "--history").returncode, 2)

    def test_a_missing_message_file_is_a_usage_error(self) -> None:
        self.assertEqual(self.check("--message-file", "absent.txt").returncode, 2)

    def test_outside_a_repository_is_a_usage_error(self) -> None:
        outside = self.folder / "outside"
        outside.mkdir()
        environment = dict(self.environment, GIT_CEILING_DIRECTORIES=str(self.folder))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--tracked"],
            cwd=outside,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_a_git_error_never_repeats_a_finding(self) -> None:
        address = joined("jane", "@", "mail.invalid")
        with mock.patch.dict(os.environ, self.environment, clear=True):
            with self.assertRaises(public_check.UsageError) as raised:
                public_check._git(self.repository, "show", ":" + address)
        self.assertIn("***", str(raised.exception))
        self.assertNotIn("jane", str(raised.exception))


class HooksTest(RepositoryTestCase):
    """The tracked hooks, run directly against a copy of the check."""

    def setUp(self) -> None:
        super().setUp()
        shutil.copytree(REPOSITORY / ".githooks", self.repository / ".githooks")
        (self.repository / "tools").mkdir()
        shutil.copy2(SCRIPT, self.repository / "tools" / "public_check.py")

    def hook(self, name: str, *arguments: str) -> int:
        return subprocess.run(
            [str(self.repository / ".githooks" / name), *arguments],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
        ).returncode

    def test_pre_commit_judges_the_staged_files(self) -> None:
        self.write("notes.md", "nothing here\n")
        self.git("add", "notes.md")
        self.assertEqual(self.hook("pre-commit"), 0)
        self.write("notes.md", joined("call 212", "-555-0234\n"))
        self.git("add", "notes.md")
        self.assertEqual(self.hook("pre-commit"), 1)

    def test_commit_msg_judges_the_message(self) -> None:
        self.write("clean.txt", "add the health route\n")
        self.write("dirty.txt", joined("ask jane", "@", "mail.invalid\n"))
        self.assertEqual(self.hook("commit-msg", "clean.txt"), 0)
        self.assertEqual(self.hook("commit-msg", "dirty.txt"), 1)

    def test_hooks_are_executable_in_git(self) -> None:
        listing = subprocess.run(
            ["git", "ls-files", "--stage", ".githooks"],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        modes = {line.split()[-1]: line.split()[0] for line in listing.splitlines()}
        self.assertEqual(
            modes, {".githooks/commit-msg": "100755", ".githooks/pre-commit": "100755"}
        )


if __name__ == "__main__":
    unittest.main()
