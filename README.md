# job-board

A job board that reads postings for you. You describe the work you want; every day it fetches new postings and scores each one against your profile, using your own model key, so the best matches come first.

## Where it stands

It is early. What exists today is the skeleton of the backend and the web app, and sign-in:

- a FastAPI service with two routes: `GET /health`, which reports whether the database answers, and `GET /me`, which answers the signed-in person's id;
- sign-in through Clerk: the web app signs a person in, and the service checks their session token on every request that needs a person and keeps one row per person, added on their first request;
- PostgreSQL for local development in Docker, with Alembic migrations (so far, the table of people);
- a React and TypeScript web app that shows whether the service answers, offers sign-in, and once signed in says whether the service recognised the person;
- tests, lint and strict type checks for each part, run by GitHub Actions on every push that changes that part;
- a check that keeps personal contact details and private names out of this public repository.

Fetching postings, profiles and scoring come next.

## Running it

You need [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/); uv installs Python 3.14 if you do not have it.

Sign-in needs a [Clerk](https://clerk.com/) application; a development instance is free. Create one, then open its dashboard's API keys page, which holds the issuer and both keys below; the permitted origins are the web app's own addresses:

- `CLERK_ISSUER`, in `backend/.env`: the Frontend API URL, such as `https://your-app.clerk.accounts.dev`.
- `CLERK_JWT_KEY`, in `backend/.env`: the JWT public key, in PEM form, which the service checks session tokens with. Keep it in double quotes, either on its lines as copied or on one line with `\n` between them.
- `CLERK_AUTHORIZED_PARTIES`, in `backend/.env`: the origins of the pages allowed to send session tokens, comma-separated. `.env.example` already holds `http://localhost:5173`, the web app's dev server; open the app at that address, not `127.0.0.1`, or the service refuses its tokens.
- `VITE_CLERK_PUBLISHABLE_KEY`, in `frontend/.env.local`: the publishable key, which is public by design.

The service will not start without the three backend values, and names whichever is missing or malformed. The web app runs without its key, and says sign-in is not configured.

```sh
git clone https://github.com/philbenson/job-board.git
cd job-board
docker compose up -d --wait db        # PostgreSQL 18 on 127.0.0.1:55432

cd backend
cp .env.example .env                  # the local database URL; add the three Clerk values
uv sync
uv run alembic upgrade head           # apply the migrations
uv run uvicorn job_board.app:create_app --factory --reload
```

Then `curl http://127.0.0.1:8000/health` answers `{"status":"ok","database":"ok"}`. With the database stopped it answers `503` and `{"status":"unavailable","database":"unreachable"}`, within two seconds. `curl http://127.0.0.1:8000/me` answers `401` and `{"detail":"sign-in required"}`, since it carries no session token.

The web app needs [Node](https://nodejs.org/) 24.15 or newer on the 24 line, or 26 or newer. In a second terminal, with the backend running:

```sh
cd frontend
cp .env.example .env.local            # add the publishable key
npm ci
npm run dev                           # serves the app and passes /api/… to the backend on port 8000
```

Open `http://localhost:5173`. The page says "Service is up"; stop the backend and reload, and it says "Service is unavailable". Sign in, and it says "Signed in" once the service has recognised you.

## Testing it

Backend, from `backend/`, with the database running:

```sh
uv run pytest                 # each run creates its own database and drops it afterwards
uv run ruff check
uv run ruff format --check
uv run mypy
```

`DATABASE_URL` takes the plain form `postgresql://user:password@host:port/database` (`postgres://` works too). The service reads it, or `backend/.env`. The tests read it, or else the URL in `backend/.env.example`, which is the compose database; they never read `.env`, so a `.env` pointed at another database is never touched by a test run. The tests need no Clerk application: they sign their own session tokens with a key each run generates.

Web app, from `frontend/` (the tests replace the network, so they need no backend; see [frontend/README.md](frontend/README.md)):

```sh
npm run lint
npm run typecheck
npm test
npm run build
```

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
- **Clerk, with tokens checked in the service**: sign-in, accounts and their security are a product of their own, so Clerk runs them, and the service keeps only its own row per person. The service checks each session token itself, against the public key, the issuer and the permitted origins it was started with, so checking a request costs no call to Clerk and no wait on one.
- **uv, ruff and strict mypy**: one tool and one lock file for Python and its dependencies, so every machine and every CI run installs the same thing; lint, formatting and strict typing catch mistakes before the tests run.
- **React and TypeScript, built with Vite**: typed components from the API's edge to the screen, with a dev server that reloads in place and passes API requests to the backend under its own origin, so the backend never has to allow requests from another one.
- **oxlint**: a fast linter that understands TypeScript and React, and keeps up with the newest TypeScript compiler.
- **Vitest with Testing Library**: tests share Vite's configuration and run in a simulated browser, and they check what a person sees on the page rather than how a component is written.
- **GitHub Actions**: every push that changes a part runs the same checks as a developer does; the backend's run against a real PostgreSQL rather than a stand-in.
- **The public-content check**: this repository is public, so git hooks on every commit and push, and a CI job over the whole history, read every file, path, commit and branch name for personal email addresses, phone numbers and private names, and print only redacted findings.
