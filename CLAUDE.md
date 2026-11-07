# job-board

## Build and test

Database, from the repository root: `docker compose up -d --wait db` (PostgreSQL 18 on `127.0.0.1:55432`).

Backend, from `backend/`:

- `uv sync` installs; `uv sync --locked` is what CI runs
- `uv run pytest` (needs the database; each run creates and drops its own)
- `uv run ruff check` and `uv run ruff format --check`
- `uv run mypy`
- `uv run alembic upgrade head`; `uv run alembic revision -m "<what changes>"` for a new migration
- `uv run uvicorn job_board.app:create_app --factory --reload` serves on port 8000
- `uv run python -m job_board.openapi_description` rewrites `backend/openapi.json` from the app's routes and models; a test fails while it is out of date
- `DATABASE_URL` takes the form `postgresql://user:password@host:port/database`. The service reads it or `backend/.env`; the tests read it or `backend/.env.example`, never `.env`
- The service also needs `CLERK_ISSUER`, `CLERK_JWT_KEY`, `CLERK_AUTHORIZED_PARTIES` and `MODEL_KEY_ENCRYPTION_KEY` (see `backend/.env.example`, which gives the command that makes the last) and refuses to start without them; migrations need only `DATABASE_URL`, and the tests build their own values with a key each run generates
- `uv run python -m job_board.scoring` rates up to 25 unscored open postings for each person with a working key and a target title, on their own key, and exits: 0 finished, 1 a batch stopped on a failure or no key opened under this service key, 2 refused to start. It needs only `DATABASE_URL` and `MODEL_KEY_ENCRYPTION_KEY`, and refuses to start while any of `LANGSMITH_TRACING`, `LANGCHAIN_TRACING` or either with `_V2` is `true`, `1` or `yes`, or while `ANTHROPIC_CUSTOM_HEADERS` is set; the tests run with all five unset

Front end, from `frontend/` (Node 24.15 or newer on the 24 line, or 26 or newer):

- `npm ci` installs from the lock file
- `npm ci --prefix codegen` installs the type generator, again after each change to `codegen/package-lock.json`; `npm run api:types` then regenerates `src/api/schema.ts` from `backend/openapi.json`
- CI runs `npm ci`, regenerates the API types and fails if they differ from the committed file, then `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`, in that order
- `npm run dev` serves the app and passes `/api/…` to the backend on port 8000
- `VITE_CLERK_PUBLISHABLE_KEY` in `frontend/.env.local` turns sign-in on; the tests mock `@clerk/react`

Fetcher, from `fetcher/` (Go 1.27.3 or newer):

- `test -z "$(gofmt -l .)"`, `go vet ./...` and `go run honnef.co/go/tools/cmd/staticcheck@2026.2.2 ./...`
- `go test -race ./...` (needs the database and uv: each test package creates its own database, migrates it with `uv run --locked alembic upgrade head` in `backend/`, and drops it; the server is `DATABASE_URL`'s, or else `backend/.env.example`'s)
- `DATABASE_URL=… GREENHOUSE_BOARDS=<token>,<token> go run ./cmd/fetcher` reads those Greenhouse boards once into a migrated database; tests never ask Greenhouse, they serve `internal/greenhouse/testdata/board.json`
- The fetcher never creates or alters a table: a schema change is a backend Alembic revision

Public-content check, from the repository root:

- `python3 -m unittest discover -s tools/tests`
- `python3 tools/public_check.py --tracked`, `--history` and `--refs`

## Code conventions

- Typed throughout: mypy runs in strict mode over the source and the tests.
- Small modules, each with one job.
- A change to a route rewrites `backend/openapi.json` and regenerates the front end's types in the same commit. Front end code and test fixtures use the generated types, never hand-written body shapes.
- Tests at every layer, written first; tests that need a database use the per-run database fixture, never a shared one.
- Test data uses `example.com` email addresses and `555-0100` to `555-0199` phone numbers.
- No test or tool reaches Clerk's or Anthropic's servers: backend tests sign tokens with a key they generate, answer the model key check through a fake, and score with a fake model, the real one tested against a local server through `base_url`, and front end tests mock `@clerk/react` and `fetch`.
- No private names, personal email addresses or phone numbers in any file, path, commit message or branch name: this repository is public, and the public-content check enforces it.
- Commit under the repository's configured identity; never pass `--author`.
- Comments explain the code and commit messages say what changed; neither refers to documents outside this repository.
