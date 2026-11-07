# job-board

A job board that reads postings for you. You describe the work you want; every day it fetches new postings and scores each one against your profile, using your own model key, so the best matches come first.

## Where it stands

It is early. What exists today is the skeleton of the backend and the web app:

- a FastAPI service with one route, `GET /health`, which reports whether the database answers;
- PostgreSQL for local development in Docker, with Alembic migrations (one empty first revision so far);
- a React and TypeScript web app that shows whether the service answers;
- tests, lint and strict type checks for each part, run by GitHub Actions on every push that changes that part;
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

The web app needs [Node](https://nodejs.org/) 24.15 or newer on the 24 line, or 26 or newer. In a second terminal, with the backend running:

```sh
cd frontend
npm ci
npm run dev                           # serves the app and passes /api/… to the backend on port 8000
```

The page then says "Service is up"; stop the backend and switch away from the tab and back, or reload, and it says "Service is unavailable".

## Testing it

Backend, from `backend/`, with the database running:

```sh
uv run pytest                 # each run creates its own database and drops it afterwards
uv run ruff check
uv run ruff format --check
uv run mypy
```

`DATABASE_URL` takes the plain form `postgresql://user:password@host:port/database` (`postgres://` works too). The service reads it, or `backend/.env`. The tests read it, or else the URL in `backend/.env.example`, which is the compose database; they never read `.env`, so a `.env` pointed at another database is never touched by a test run.

Web app, from `frontend/` (the tests replace the network, so they need no backend; see [frontend/README.md](frontend/README.md)):

```sh
npm run lint
npm run typecheck
npm test
npm run build
```

The backend's OpenAPI description is committed as `backend/openapi.json`, the contract between the two parts: a backend test fails when the file falls behind the routes, and the web app's request and response types are generated from it, so a change on one side that the other has not taken up fails CI. After changing a route, rewrite the file from `backend/` with `uv run python -m job_board.openapi_description`, then regenerate the types from `frontend/` with `npm run api:types` (after installing the generator with `npm ci --prefix codegen`, and again after each change to `frontend/codegen/package-lock.json`).

From the repository root, the public-content check and its tests (see [tools/README.md](tools/README.md)):

```sh
python3 -m unittest discover -s tools/tests
python3 tools/public_check.py --tracked
python3 tools/public_check.py --history
sh tools/install-hooks.sh     # once per clone: run the check on every commit and push
```

## How it's built

- **FastAPI**: request and response types are ordinary Python types, checked at the edge and published as an OpenAPI description, and the framework is async throughout.
- **PostgreSQL with Alembic**: one dependable relational store, with every schema change a versioned migration that is reviewed and tested like code.
- **Async SQLAlchemy on psycopg 3**: the service waits on the database without holding up other requests, through a query layer that stays readable as the schema grows.
- **uv, ruff and strict mypy**: one tool and one lock file for Python and its dependencies, so every machine and every CI run installs the same thing; lint, formatting and strict typing catch mistakes before the tests run.
- **React and TypeScript, built with Vite**: typed components from the API's edge to the screen, with a dev server that reloads in place and passes API requests to the backend under its own origin, so the backend never has to allow requests from another one.
- **A committed OpenAPI contract**: the web app's types are generated from the backend's own description instead of written by hand, so renaming a field fails a type check rather than the page.
- **oxlint**: a fast linter that understands TypeScript and React, and keeps up with the newest TypeScript compiler.
- **Vitest with Testing Library**: tests share Vite's configuration and run in a simulated browser, and they check what a person sees on the page rather than how a component is written.
- **GitHub Actions**: every push that changes a part runs the same checks as a developer does; the backend's run against a real PostgreSQL rather than a stand-in.
- **The public-content check**: this repository is public, so git hooks on every commit and push, and a CI job over the whole history, read every file, path, commit and branch name for personal email addresses, phone numbers and private names, and print only redacted findings.
