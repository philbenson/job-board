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
- `DATABASE_URL` takes the form `postgresql://user:password@host:port/database`. The service reads it or `backend/.env`; the tests read it or `backend/.env.example`, never `.env`

Public-content check, from the repository root:

- `python3 -m unittest discover -s tools/tests`
- `python3 tools/public_check.py --tracked`, `--history` and `--refs`

## Code conventions

- Typed throughout: mypy runs in strict mode over the source and the tests.
- Small modules, each with one job.
- Tests at every layer, written first; tests that need a database use the per-run database fixture, never a shared one.
- Test data uses `example.com` email addresses and `555-0100` to `555-0199` phone numbers.
- No private names, personal email addresses or phone numbers in any file, path, commit message or branch name: this repository is public, and the public-content check enforces it.
- Commit under the repository's configured identity; never pass `--author`.
- Comments explain the code and commit messages say what changed; neither refers to documents outside this repository.
