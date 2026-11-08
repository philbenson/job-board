# job-board

A job board that reads postings for you. You describe the work you want; every day it fetches new postings and scores each one against your profile, using your own model key, so the best matches come first.

## Where it stands

It is early. What exists today is the skeleton of the backend and the web app, sign-in, the model key, the profile, saved through the service, the posting fetcher, scoring, resume upload, with the resume's text read and checked, the leads list, and the onboarding interview, so far in the service alone:

- a FastAPI service with `GET /health`, which reports whether the database answers, `GET /me`, which answers the signed-in person's id, `/model-key`, where the signed-in person reads, saves and removes their own Anthropic API key, `GET /profile`, which reads the signed-in person's profile, with a `PUT` route under `/profile/` for each of its sections, `GET /leads`, which answers the open postings scored for the signed-in person, best first, the best 100 with a count of all, and `/interview`, where the signed-in person starts, answers, retries, reads and removes their onboarding interview;
- sign-in through Clerk: the web app signs a person in, and the service checks their session token on every request that needs a person and keeps one row per person, added on their first request;
- the profile, in ten sections, each replaced whole through its own route: the job titles they are looking for; nearby titles and whether a role one level down is fine; where they will work; pay; skills and years of each; requirements they lack but would apply without, and what they would give up; deal-breakers among industries, company sizes and recruiting agencies; companies to watch and jobs already applied to; how many postings a day, and from what score a posting gets a written brief; and rules of their own. Every section but the titles reads as null until its first save, each has its own limits, and saving one leaves the rest as they were. Pay is annual base pay in whole US dollars, and places are US states, by postal code, and city names as the person typed them;
- the model key: the service checks a person's Anthropic API key with Anthropic before saving it, keeps it sealed so only the service can open it, and from then on shows only its last four characters;
- the resume: `/resume`, where the signed-in person uploads one PDF of up to 5 MB, replacing any before it, reads its size and when it was uploaded, and removes it; the service keeps the file in an S3-compatible bucket, such as Cloudflare R2 or Amazon S3, with a row describing it in PostgreSQL. At upload the service reads the file's text, up to 15,000 characters, and keeps it beside that row; `/resume/text` reads it back and saves the person's checked copy, corrected or typed in where nothing could be read, and refuses a save once a newer file has replaced the one the text came from. The web app has a panel for all of it;
- scoring: a command that rates each open posting from 1 to 5 against the person's profile, with a one-line reason, for each person with a working key and at least one target title, on that person's own key, up to 25 new postings per person each run, and exits; when Anthropic refuses a key, it stops using that key and the model key panel tells the person why, until they save a new one;
- the onboarding interview: once a person has a working key and has checked their resume's text, `POST /interview` starts an interviewer that reads the resume and their profile and asks one question at a time, on the person's own key, saving what it learns into the profile a section at a time, each save held to the rules of that section's own route. `POST /interview/answer` sends an answer, `POST /interview/retry` runs a failed interview again from its last saved step, `GET /interview` reads its status, the question it waits on and the conversation so far, and `DELETE /interview` removes it with every step saved of it. Each turn runs in the service after the route has answered, one at a time per person, and the interview stops after 60 model calls;
- PostgreSQL for local development in Docker, with Alembic migrations (so far, the tables of people, of model keys, of profiles, of postings, of fetch runs, of scores, of resumes and of interviews, and those in which the interviewer keeps its steps);
- a Go command that reads Greenhouse job boards into PostgreSQL once and exits, storing each board whole or not at all and recording every attempt;
- a React and TypeScript web app that shows whether the service answers, offers sign-in, and once signed in says whether the service recognised the person, lets them save, replace or remove their model key, lets them edit every section of their profile (target titles, nearby titles, places, pay, skills, gaps and trade-offs, deal-breakers, companies, pace and rules of their own), each saved on its own, all of them read by scoring except pace, lets them upload, replace or remove their resume, see its size and when it was uploaded, and check, correct and save the text read from it, and lists their leads: the open postings scored for them, best first, each with its score, its one-line reason and a link to the posting;
- tests, lint and strict type checks for each part, run by GitHub Actions on every push that changes that part;
- a check that keeps personal contact details and private names out of this public repository.

The interview's screen in the web app, and running the fetcher and scoring on a schedule, come next.

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

Nor will the service start while LangSmith tracing is on (`LANGSMITH_TRACING`, `LANGCHAIN_TRACING`, or either with `_V2`, set to `true`, `1` or `yes`), while `ANTHROPIC_CUSTOM_HEADERS` is set, or while `ANTHROPIC_LOG` is set to anything but empty. The interview sends each person's resume, profile and answers to Anthropic: a trace would send them, and the model's replies, to LangSmith as well, the headers would go with every person's key, and the Anthropic library's own logging would write them to the log. It names each setting it refuses in the log, never its value.

Resume upload needs a bucket in an S3-compatible store and five more values in `backend/.env`, all five or none:

- `S3_ENDPOINT_URL`: the store's `https` address, with no path (`http` is accepted only for this machine, for a local stand-in). For Cloudflare R2, `https://<account id>.r2.cloudflarestorage.com`; for Amazon S3, `https://s3.<region>.amazonaws.com`.
- `S3_REGION`: `auto` for R2; for S3, the bucket's region.
- `S3_BUCKET`: the bucket's name.
- `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`: a key allowed to write and delete objects in that bucket.

Without them the service starts as before, logs once that resume storage is not set up, and answers `503` on its resume routes, and the resume panel says storage is not set up. Given some but not all five, it will not start, and names the ones missing. It reads the store's address and credentials from these five alone, never from `AWS_` environment variables or `~/.aws`, so settings made for another project cannot send resumes elsewhere.

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

Scoring is a command meant to be started on a schedule: each run rates up to 25 unscored open postings for each person who has saved a working key and chosen at least one target title, on that person's own key, then exits. It needs only `DATABASE_URL` and `MODEL_KEY_ENCRYPTION_KEY`, read from the environment or from `.env` in the folder it runs in, and no Clerk values. It refuses to start while LangSmith tracing is on (`LANGSMITH_TRACING`, `LANGCHAIN_TRACING`, or either with `_V2`, set to `true`, `1` or `yes`), since a trace would send postings, the person's profile and the model's replies to LangSmith, while `ANTHROPIC_CUSTOM_HEADERS` is set, since those headers would go with every person's key, and while `ANTHROPIC_LOG` is set to anything but empty, since the Anthropic library's own logging would write postings, the person's profile and the model's replies to the log. It exits 0 when every person's batch finished or had nothing to do, 1 when any stopped on a failure, such as a key Anthropic refused or a model Anthropic no longer finds, or when no person's key opens under this `MODEL_KEY_ENCRYPTION_KEY`, and 2 when it refused to start; it logs one line per person, and one more for each reply cut off at the model's token limit. To run it once by hand, with the backend's `.env` in place and the database migrated:

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

`DATABASE_URL` takes the plain form `postgresql://user:password@host:port/database` (`postgres://` works too). The service reads it, or `backend/.env`. The tests read it, or else the URL in `backend/.env.example`, which is the compose database; they never read `.env`, so a `.env` pointed at another database is never touched by a test run. The tests need no Clerk application: they sign their own session tokens with a key each run generates. Nor do they need an Anthropic key or reach Anthropic: the routes' tests stand in for the key check, the check's own tests answer it through a fake transport, scoring's tests rate postings and the interview's tests ask and save with stand-in models, and the real models are tested against a small server the tests run on this machine.

Nor do they reach a storage provider: each run starts a local S3 server, from the moto package that `uv sync` installs, and the resume tests keep every file there.

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
- **The resume as the raw request body, read after the sign-in**: the upload is the PDF itself rather than a form, so the service checks the session token, the declared type and the declared length before it reads a byte, refuses anything over 5 MB unread, stops at the first bytes that are not a PDF, and holds no database connection while the file arrives or the store answers.
- **The resume's text read in a limited child process, then checked by the person**: a PDF can inflate a stream to gigabytes, nest objects past a parser's stack, or loop, so the service never parses one itself. It hands the file to a child process that starts with an empty environment and limits on processor time and, where the system allows, memory, which reads the text with pypdf; the service kills it past 15 seconds, reads one file at a time in each worker with at most two more waiting, each for up to 15 seconds and one to a person, refuses an upload past that as busy, and keeps the answer only if it is of the shape and within the rules a save is held to. Text read from a PDF can come out of order or not at all, so the person checks and corrects it, and the service keeps when they did.
- **Scoring as a scheduled command on each person's own key**: rating postings costs model calls, so each person pays for their own on their own key, in a small batch per run that bounds what one run can cost them; a command that a schedule starts, works through everyone once and exits keeps that work out of the web service, so a slow or failing model never holds up a page, and a posting whose request fails is simply left for the next run.
- **The interviewer as a LangGraph graph on each person's own key**: an interview asks, waits on the person and saves what they said, over many turns, so it is a graph whose state LangGraph saves after every step: waiting on an answer holds nothing open, a person can close the tab and come back, and a failed turn runs again from the last saved step. The model saves through one tool per profile section, whose input is checked by that section's own route's rules and written by the route's own statement, so the interviewer can store only what the person could have saved by hand, and only into their own profile; a refused save goes back to the model with the reasons, to correct.
- **LangGraph's PostgreSQL saver, on tables the migrations make**: the saved steps live in the one database, and removing an interview removes them with it. The saver's own setup, which would create and alter its tables, never runs, so the schema changes only through a reviewed migration, and a test fails when a saver upgrade would build them differently. Pickle is off, and a saved step is read back only into the message types the graph holds and the types on LangGraph's own safe list, such as dates, so a row cannot make loading it run code.
- **Each turn a task of the web service, holding a claim**: a turn is a few model calls, so it runs inside the service after the route has answered, with no queue of its own. The interview's row holds a claim, taken in one statement, so only one turn runs per person at a time; a claim left by a process that died goes stale after ten minutes, and the person's retry takes it over. Stopping the service gives the turns in flight twenty seconds to finish, under the host's thirty before it kills the service, then cuts them off, and the person retries.
- **uv, ruff and strict mypy**: one tool and one lock file for Python and its dependencies, so every machine and every CI run installs the same thing; lint, formatting and strict typing catch mistakes before the tests run.
- **React and TypeScript, built with Vite**: typed components from the API's edge to the screen, with a dev server that reloads in place and passes API requests to the backend under its own origin, so the backend never has to allow requests from another one.
- **A committed OpenAPI contract**: the web app's types are generated from the backend's own description instead of written by hand, so renaming a field fails a type check rather than the page.
- **oxlint**: a fast linter that understands TypeScript and React, and keeps up with the newest TypeScript compiler.
- **Vitest with Testing Library**: tests share Vite's configuration and run in a simulated browser, and they check what a person sees on the page rather than how a component is written.
- **Go with pgx for the fetcher**: the fetcher is a batch job a scheduler starts and stops, so it suits a single compiled binary that starts at once, with HTTP and JSON from the standard library; pgx speaks PostgreSQL's own protocol directly, so a board's postings go to the database as one batch inside one transaction.
- **GitHub Actions**: every push that changes a part runs the same checks as a developer does; the backend's and the fetcher's run against a real PostgreSQL rather than a stand-in.
- **The public-content check**: this repository is public, so git hooks on every commit and push, and a CI job over the whole history, read every file, path, commit and branch name for personal email addresses, phone numbers and private names, and print only redacted findings.
