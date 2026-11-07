# Repository tools

## The public-content check

This repository is public. `public_check.py` keeps three things out of it:

- the name of the private repository that holds this project's planning notes, in any spelling within one line: any case, hyphens, underscores, dots, spaces, inside a path, or run together. The script holds only SHA-256 hashes of the name, never the name itself;
- email addresses, except documentation domains (`example.com`, `example.org`, `example.net` and their subdomains), GitHub's no-reply addresses (`…@users.noreply.github.com`), `noreply@github.com` and `git@github.com`. A URL with a user and password has the same shape as an address, so test and deployment URLs use `example.com` hosts;
- phone numbers: North American numbers written with separators, whose area code and exchange start with 2 to 9, and `+` followed by 10 to 15 digits. Numbers in the fictional range `555-0100` to `555-0199` are allowed, so test data uses those.

It looks at file contents, file paths, commit messages (comment lines included, since git keeps them for `git commit -m` and `-F`) and commit authors and committers. A file with a NUL byte in its first 8 KB, or that is not UTF-8, is skipped as binary; its path is still checked.

Its output can end up in a public CI log, so a finding never repeats what it found. Each finding prints a location, a rule and a redacted form (an email as `j***@g***`, a phone number as its last two digits, the private name not at all), and a path holding a finding is printed with that part masked. The last line counts the files, commits, findings and binary files skipped.

It needs only Python 3.9 or newer and its standard library, since the git hooks run whatever `python3` is on the `PATH`.

### Running it

From anywhere inside the repository:

```sh
python3 tools/public_check.py --tracked              # every tracked file and its path
python3 tools/public_check.py --history              # message, author and committer of every commit reachable from HEAD
python3 tools/public_check.py --staged               # what the next commit would add (the pre-commit hook)
python3 tools/public_check.py --message-file <path>  # a commit message (the commit-msg hook)
```

It exits 0 when clean, 1 with findings, and 2 when it could not run (no mode, an unreadable message file, not inside a git repository).

The workflow `.github/workflows/public-check.yml` runs the tests, `--tracked` and `--history` on every push.

### Its tests

```sh
python3 -m unittest discover -s tools/tests
```

The tests build throwaway git repositories in a temporary folder, with git's user and system configuration ignored and `example.com` identities, and never run `git commit`. Every positive case is assembled from pieces at run time, so the test file passes the check itself.

### The git hooks

`.githooks/pre-commit` runs the check with `--staged` and `.githooks/commit-msg` with `--message-file`. Turn them on once per clone:

```sh
sh tools/install-hooks.sh
```
