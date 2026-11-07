import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from per_run_database import per_run_database, server_url

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """The URL of a database that exists for this test run only."""
    with per_run_database(server_url()) as url:
        yield url


def _migrated_database() -> Iterator[str]:
    with per_run_database(server_url()) as url:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", url)  # the migrations read it, as the service does
            command.upgrade(Config(ALEMBIC_INI), "head")
        yield url


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """A second database for this run, at the migrations' head.

    Its own, so the migration tests can take theirs down to nothing and back
    without touching rows another test is reading.
    """
    yield from _migrated_database()


@pytest.fixture(scope="module")
def module_database_url() -> Iterator[str]:
    """A database at the migrations' head for one test module alone.

    For tests that read every row of a table, such as all open postings, and
    so may empty the tables between tests without touching another module's.
    """
    yield from _migrated_database()


@pytest.fixture
def closed_port() -> int:
    """A loopback port with nothing listening on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


@pytest.fixture
def silent_port() -> Iterator[int]:
    """A loopback port that accepts connections and never answers."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port: int = server.getsockname()[1]
        yield port
