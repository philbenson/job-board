# job-board

A job board that reads postings for you. You describe the work you want; every day it fetches new postings and scores each one against your profile, using your own model key, so the best matches come first.

## Where it stands

It is early. What exists today is the backend's skeleton:

- a FastAPI service with one route, `GET /health`, which reports whether the database answers;
- PostgreSQL for local development in Docker, with Alembic migrations (one empty first revision so far);
- tests, lint, format and strict type checks, run on every push by GitHub Actions;
- a check that keeps personal contact details and private names out of this public repository.

Fetching postings, profiles and scoring come next.

## Running it

You need [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/); uv installs Python 3.14 if you do not have it.

```sh
git clone https://github.com/philbenson/job-board.git
cd job-board
docker compose up -d --wait db        # PostgreSQL 18 on 127.0.0.1:55432

cd backend
cp .env.example .env                  # the local database URL
uv sync
uv run alembic upgrade head           # apply the migrations
uv run uvicorn job_board.app:create_app --factory --reload
```

Then `curl http://127.0.0.1:8000/health` answers `{"status":"ok","database":"ok"}`. With the database stopped it answers `503` and `{"status":"unavailable","database":"unreachable"}`, within two seconds.

## Testing it

From `backend/`, with the database running:

```sh
uv run pytest                 # each run creates its own database and drops it afterwards
uv run ruff check
uv run ruff format --check
uv run mypy
```

From the repository root, the public-content check and its tests (see [tools/README.md](tools/README.md)):

```sh
python3 -m unittest discover -s tools/tests
python3 tools/public_check.py --tracked
sh tools/install-hooks.sh     # once per clone: run the check on every commit
```

## How it's built

- **FastAPI**: request and response types are ordinary Python types, checked at the edge and published as an OpenAPI description, and the framework is async throughout.
- **PostgreSQL with Alembic**: one dependable relational store, with every schema change a versioned migration that is reviewed and tested like code.
- **Async SQLAlchemy on psycopg 3**: the service waits on the database without holding up other requests, through a query layer that stays readable as the schema grows.
- **uv, ruff and strict mypy**: one tool and one lock file for Python and its dependencies, so every machine and every CI run installs the same thing; lint, formatting and strict typing catch mistakes before the tests run.
- **GitHub Actions**: every push runs the same checks as a developer does, against a real PostgreSQL rather than a stand-in.
- **The public-content check**: this repository is public, so a git hook and a CI job read every file, path and commit for personal email addresses, phone numbers and private names, and print only redacted findings.
