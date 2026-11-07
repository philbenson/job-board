"""A database created for one test run and dropped after it.

Invariant: parallel test runs never share a database. Each run creates its own
uniquely named database on the shared server and drops it at the end, so
several checkouts can test against one PostgreSQL at once. A run killed before
its end leaves its database behind, so each run first drops test databases
older than STALE_AFTER.
"""

import os
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import URL, Connection, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from job_board.settings import sqlalchemy_url

# The tests read DATABASE_URL, else this file's URL; never backend/.env, which
# is the service's own and may point at a database the tests must not touch.
EXAMPLE_FILE = Path(__file__).resolve().parents[1] / ".env.example"
START_COMMAND = "docker compose up -d --wait db"
CONNECT_TIMEOUT_SECONDS = 5  # a server that is down should fail the run promptly, not hang it
NAME_PREFIX = "job_board_test_"
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"  # UTC
# Far longer than any test run, so a live parallel run's database is never dropped.
STALE_AFTER = timedelta(hours=24)
_NAME = re.compile(rf"{NAME_PREFIX}(\d{{14}})_[0-9a-f]+")


def example_database_url() -> str:
    for line in EXAMPLE_FILE.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "DATABASE_URL":
            return value.strip()
    raise RuntimeError(f"{EXAMPLE_FILE.name} has no DATABASE_URL= line")


def server_url() -> URL:
    """The server the tests use, converted the way the service converts its URL."""
    raw = os.environ.get("DATABASE_URL") or example_database_url()
    return make_url(sqlalchemy_url(raw))


def created_at(name: str) -> datetime | None:
    """When a test database was created, from its name; None for a name without a time."""
    match = _NAME.fullmatch(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def drop_stale_databases(connection: Connection, now: datetime) -> list[str]:
    """Drop test databases left by runs that never finished, and name them."""
    names = connection.execute(
        text("SELECT datname FROM pg_database WHERE starts_with(datname, :prefix)"),
        {"prefix": NAME_PREFIX},
    ).scalars()
    stale = [
        name
        for name in names
        if (created := created_at(name)) is not None and now - created > STALE_AFTER
    ]
    for name in stale:  # each name matched _NAME, so it is digits and hex only
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    return stale


@contextmanager
def per_run_database(server: URL) -> Iterator[str]:
    """Create ``job_board_test_<UTC time>_<random hex>``, yield its URL, then drop it.

    A server that cannot be reached fails the run with the command that starts
    the local one, never with the URL; it never skips, since a skipped database
    test is a silent gap.
    """
    now = datetime.now(UTC)
    name = f"{NAME_PREFIX}{now:{TIMESTAMP_FORMAT}}_{secrets.token_hex(6)}"
    admin = create_engine(
        server,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )
    try:
        try:
            with admin.connect() as connection:
                drop_stale_databases(connection, now)
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        except OperationalError:
            reachable = False
        else:
            reachable = True
        if not reachable:  # failed outside the except block, so no driver message rides along
            pytest.fail(
                "could not connect to PostgreSQL for the tests. If it is the local "
                f"database, start it from the repository root with: {START_COMMAND}",
                pytrace=False,
            )
        try:
            yield server.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()
