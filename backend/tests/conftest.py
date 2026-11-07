import socket
from collections.abc import Iterator

import pytest
from per_run_database import per_run_database, server_url


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """The URL of a database that exists for this test run only."""
    with per_run_database(server_url()) as url:
        yield url


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
