# job-board

A job board that reads postings for you. You describe the work you want; every day it fetches new postings and scores each one against your profile, using your own model key, so the best matches come first.

## Where it stands

It is early. What exists today is the skeleton of the backend and the web app, sign-in, the model key, the first part of the profile, the posting fetcher, scoring, and the leads list:

- a FastAPI service with `GET /health`, which reports whether the database answers, `GET /me`, which answers the signed-in person's id, `/model-key`, where the signed-in person reads, saves and removes their own Anthropic API key, `GET /profile` and `PUT /profile/target-titles`, which read the signed-in person's profile and replace the job titles they are looking for, and `GET /leads`, which answers the open postings scored for the signed-in person, best first, the best 100 with a count of all;
- sign-in through Clerk: the web app signs a person in, and the service checks their session token on every request that needs a person and keeps one row per person, added on their first request;
- the model key: the service checks a person's Anthropic API key with Anthropic before saving it, keeps it sealed so only the service can open it, and from then on shows only its last four characters;
- scoring: a command that rates each open posting from 1 to 5, with a one-line reason, for each person with a working key and at least one target title, on that person's own key, up to 25 new postings per person each run, and exits; when Anthropic refuses a key, it stops using that key and the model key panel tells the person why, until they save a new one;
- PostgreSQL for local development in Docker, with Alembic migrations (so far, the tables of people, of model keys, of profiles, of postings, of fetch runs and of scores);
- a Go command that reads Greenhouse job boards into PostgreSQL once and exits, storing each board whole or not at all and recording every attempt;
- a React and TypeScript web app that shows whether the service answers, offers sign-in, and once signed in says whether the service recognised the person, lets them save, replace or remove their model key, lets them list, add, remove and save their target titles, and lists their leads: the open postings scored for them, best first, each with its score, its one-line reason and a link to the posting;
- tests, lint and strict type checks for each part, run by GitHub Actions on every push that changes that part;
- a check that keeps personal contact details and private names out of this public repository.

Running the fetcher and scoring on a schedule, and the rest of the profile, come next.

## Running it

You need [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/); uv installs Python 3.14 if you do not have it.

Sign-in needs a [Clerk](https://clerk.com/) application; a development instance is free. Create one, then open its dashboard's API keys page, which holds the issuer and both keys below; the permitted origins are the web app's own addresses:

- `CLERK_ISSUER`, in `backend/.env`: the Frontend API URL, such as `https://your-app.clerk.accounts.dev`.
- `CLERK_JWT_KEY`, in `backend/.env`: the JWT public key, in PEM form, which the service checks session tokens with. Keep it in double quotes, either on its lines as copied or on one line with `\n` between them.
- `CLERK_AUTHORIZED_PARTIES`, in `backend/.env`: the origins of the pages allowed to send session tokens, comma-separated. `.env.example` already holds `http://localhost:5173`, the web app's dev server; open the app at that address, not `127.0.0.1`, or the service refuses its tokens.
- `VITE_CLERK_PUBLISHABLE_KEY`, in `frontend/.env.local`: the publishable key, which is public by design.

Sign-up is by invitation: in the Clerk dashboard, set the application's sign-up mode to Invite-only, then invite each person who will use it by email. Left at Open, anyone who finds the page can make an account.

The model key needs one more backend value, `MODEL_KEY_ENCRYPTION_KEY`, in `backend/.env`: 32 random bytes in URL-safe base64, which seals each person's key in the database. Make one with `python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'`. Keep it safe and keep it fixed: if it is lost or changed, no saved key can be opened, and the model key panel asks each person to enter theirs again.

The service will not start without the four backend values, and names whichever is missing or malformed. The web app runs without its key, and says sign-in is not configured.

```sh
git clone https://github.com/philbenson/job-board.git
cd job-board
docker compose up -d --wait db        # PostgreSQL 18 on 127.0.0.1:55432

cd backend
cp .env.example .env                  # the local database URL; add the Clerk values and the encryption key
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

Open `http://localhost:5173`. The page says "Service is up"; stop the backend and switch away from the tab and back, or reload, and it says "Service is unavailable". Sign in, and it says "Signed in" once the service has recognised you.

The fetcher needs [Go](https://go.dev/dl/) 1.27.3 or newer. With the database migrated as above, it reads the Greenhouse boards you name, by their tokens, and exits (see [fetcher/README.md](fetcher/README.md)):

```sh
cd fetcher
DATABASE_URL=postgresql://job_board:job_board@127.0.0.1:55432/job_board \
GREENHOUSE_BOARDS=<token>,<another token> \
go run ./cmd/fetcher
```

Scoring is a command meant to be started on a schedule: each run rates up to 25 unscored open postings for each person who has saved a working key and chosen at least one target title, on that person's own key, then exits. It needs only `DATABASE_URL` and `MODEL_KEY_ENCRYPTION_KEY`, read from the environment or from `.env` in the folder it runs in, and no Clerk values. It refuses to start while LangSmith tracing is on (`LANGSMITH_TRACING`, `LANGCHAIN_TRACING`, or either with `_V2`, set to `true`, `1` or `yes`), since a trace would send postings, titles and the model's replies to LangSmith, and while `ANTHROPIC_CUSTOM_HEADERS` is set, since those headers would go with every person's key. It exits 0 when every person's batch finished or had nothing to do, 1 when any stopped on a failure, such as a key Anthropic refused or a model Anthropic no longer finds, or when no person's key opens under this `MODEL_KEY_ENCRYPTION_KEY`, and 2 when it refused to start; it logs one line per person. To run it once by hand, with the backend's `.env` in place and the database migrated:

```sh
cd backend
uv run python -m job_board.scoring
```

## Testing it

Backend, from `backend/`, with the database running:

```sh
uv run pytest                 # each run creates its own database and drops it afterwards
uv run ruff check
uv run ruff format --check
uv run mypy
```

`DATABASE_URL` takes the plain form `postgresql://user:password@host:port/database` (`postgres://` works too). The service reads it, or `backend/.env`. The tests read it, or else the URL in `backend/.env.example`, which is the compose database; they never read `.env`, so a `.env` pointed at another database is never touched by a test run. The tests need no Clerk application: they sign their own session tokens with a key each run generates. Nor do they need an Anthropic key or reach Anthropic: the routes' tests stand in for the key check, the check's own tests answer it through a fake transport, scoring's tests rate postings with a stand-in model, and the real model is tested against a small server the tests run on this machine.

Web app, from `frontend/` (the tests replace the network, so they need no backend; see [frontend/README.md](frontend/README.md)):

```sh
npm run lint
npm run typecheck
npm test
npm run build
```

Fetcher, from `fetcher/`, with the database running and uv installed (each test package creates its own database and migrates it with the backend's migrations; the tests serve an invented board and never ask Greenhouse):

```sh
test -z "$(gofmt -l .)"
go vet ./...
go run honnef.co/go/tools/cmd/staticcheck@2026.2.2 ./...
go test -race ./...
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
- **The profile as one document per person**: the profile grows a section at a time, so each person's is one JSON document in PostgreSQL rather than a table per section, and a new section needs no migration. A save sets only its own section inside the stored document, in the statement that adds the row when there is none, so two saves of different sections never undo each other.
- **Async SQLAlchemy on psycopg 3**: the service waits on the database without holding up other requests, through a query layer that stays readable as the schema grows.
- **Clerk, with tokens checked in the service**: sign-in, accounts and their security are a product of their own, so Clerk runs them, and the service keeps only its own row per person. The service checks each session token itself, against the public key, the issuer and the permitted origins it was started with, so checking a request costs no call to Clerk and no wait on one.
- **Each person's own model key, checked and sealed**: scoring runs on the person's own Anthropic key, so the service keeps it sealed with AES-256-GCM, bound to its owner and provider so a sealed key copied to another row will not open, and checks it before saving by reading the metadata of the model the app runs, which Anthropic answers only for a working key allowed that model and which generates nothing, so the check costs nothing.
- **Scoring as a scheduled command on each person's own key**: rating postings costs model calls, so each person pays for their own on their own key, in a small batch per run that bounds what one run can cost them; a command that a schedule starts, works through everyone once and exits keeps that work out of the web service, so a slow or failing model never holds up a page, and a posting whose request fails is simply left for the next run.
- **uv, ruff and strict mypy**: one tool and one lock file for Python and its dependencies, so every machine and every CI run installs the same thing; lint, formatting and strict typing catch mistakes before the tests run.
- **React and TypeScript, built with Vite**: typed components from the API's edge to the screen, with a dev server that reloads in place and passes API requests to the backend under its own origin, so the backend never has to allow requests from another one.
- **A committed OpenAPI contract**: the web app's types are generated from the backend's own description instead of written by hand, so renaming a field fails a type check rather than the page.
- **oxlint**: a fast linter that understands TypeScript and React, and keeps up with the newest TypeScript compiler.
- **Vitest with Testing Library**: tests share Vite's configuration and run in a simulated browser, and they check what a person sees on the page rather than how a component is written.
- **Go with pgx for the fetcher**: the fetcher is a batch job a scheduler starts and stops, so it suits a single compiled binary that starts at once, with HTTP and JSON from the standard library; pgx speaks PostgreSQL's own protocol directly, so a board's postings go to the database as one batch inside one transaction.
- **GitHub Actions**: every push that changes a part runs the same checks as a developer does; the backend's and the fetcher's run against a real PostgreSQL rather than a stand-in.
- **The public-content check**: this repository is public, so git hooks on every commit and push, and a CI job over the whole history, read every file, path, commit and branch name for personal email addresses, phone numbers and private names, and print only redacted findings.
