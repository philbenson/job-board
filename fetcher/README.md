# The posting fetcher

A Go command that reads job postings from [Greenhouse](https://www.greenhouse.com/) job boards into PostgreSQL, once, and exits. A scheduler runs it; it keeps no state of its own between runs.

For each board it is given, it asks Greenhouse's public Job Board API once for every posting with its description, checks every posting, and then stores the whole board in one transaction:

- a posting it has not seen before is added;
- a posting it has seen is brought up to date, and marked as seen;
- a posting that the board no longer lists is closed, and reopened if it comes back.

A board is stored whole or not at all: if the request fails, the answer is not the feed, or any one posting fails a check, nothing on that board changes. One board failing never stops the next. Every attempt, successful or not, is recorded in the `fetch_runs` table with what it counted, or a short code saying what failed.

The tables belong to the backend's Alembic migrations; the fetcher never creates or changes one, so migrate the database first.

## Settings

Both come from the environment, and are checked before anything else happens:

| Setting | What it holds |
| --- | --- |
| `DATABASE_URL` | the database, in the form `postgresql://user:password@host:port/database` (`postgres://` works too). The fetcher does not read `backend/.env`. |
| `GREENHOUSE_BOARDS` | the boards to read: board tokens separated by commas, each lower-case letters, digits, `_` and `-`, at most 100 characters. A board's token is the last part of its address, `boards.greenhouse.io/<token>`. |

## Running it once by hand

With the database running and migrated (see the [root README](../README.md)), from this folder:

```sh
DATABASE_URL=postgresql://job_board:job_board@127.0.0.1:55432/job_board \
GREENHOUSE_BOARDS=<token>,<another token> \
go run ./cmd/fetcher
```

It sends one request per board to Greenhouse, with a 30-second limit and a 64 MiB cap on the answer, and logs one line per board to standard error:

```text
time=2026-11-07T12:00:00.000-05:00 level=INFO msg="board fetched" board=<token> outcome=succeeded seen=42 new=42 closed=0
```

Run it again while the board is unchanged and `new` is 0: nothing changes but when each posting was last seen. To see the postings and a run row for each attempt, from the repository root:

```sh
docker compose exec db psql -U job_board -d job_board \
  -c "SELECT board, outcome, failure, postings_seen, postings_new, postings_closed FROM fetch_runs ORDER BY id" \
  -c "SELECT board, title, location, closed_at FROM postings ORDER BY first_seen_at DESC LIMIT 10"
```

It exits 0 when every board succeeded, 1 when any board failed, and 2 when the settings are refused or the database cannot be reached, before any board is tried. Ctrl-C or `SIGTERM` stops it: the board in hand is rolled back and recorded as `interrupted`, and no other board is started. If the database drops the connection, only the board in hand fails: the fetcher reconnects to record it and to go on with the next board.

A failed run's code is one of `request` (no answer, or it timed out), `status` (an answer other than 200), `too-large`, `decode` (not the feed's JSON), `invalid-posting`, `database` and `interrupted` (stopped while the board was fetched or written).

## Testing it

The tests need the database running (`docker compose up -d --wait db` from the repository root) and [uv](https://docs.astral.sh/uv/). Each test package creates its own database, migrates it with the backend's migrations, and drops it at the end, so test runs never share one. They use `DATABASE_URL`'s server, or else the one in `backend/.env.example`.

No test talks to Greenhouse: each serves an invented board, `internal/greenhouse/testdata/board.json`, from a local test server.

```sh
test -z "$(gofmt -l .)"
go vet ./...
go run honnef.co/go/tools/cmd/staticcheck@2026.2.2 ./...
go test -race ./...
```
