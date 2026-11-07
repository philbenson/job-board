"""A database created for one test run and dropped after it.

Invariant: parallel test runs never share a database. Each run creates its own
uniquely named database on the shared server and drops it at the end, so
several checkouts can test against one PostgreSQL at once.
"""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

# The URL in backend/.env.example, for a run with no DATABASE_URL set.
LOCAL_DATABASE_URL = "postgresql+psycopg://job_board:job_board@127.0.0.1:55432/job_board"
START_COMMAND = "docker compose up -d --wait db"
CONNECT_TIMEOUT_SECONDS = 5  # a server that is down should fail the run promptly, not hang it


def server_url() -> URL:
    return make_url(os.environ.get("DATABASE_URL", LOCAL_DATABASE_URL))


@contextmanager
def per_run_database(server: URL) -> Iterator[str]:
    """Create ``job_board_test_<random hex>`` on the server, yield its URL, then drop it.

    A server that cannot be reached fails the run with the command that starts
    it; it never skips, since a skipped database test is a silent gap.
    """
    name = f"job_board_test_{secrets.token_hex(6)}"
    admin = create_engine(
        server,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )
    try:
        try:
            with admin.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        except OperationalError:
            pytest.fail(
                "PostgreSQL is not reachable for the tests. "
                f"Start it from the repository root with: {START_COMMAND}",
                pytrace=False,
            )
        try:
            yield server.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()
