import secrets
import socket
from collections.abc import Iterator
from pathlib import Path

import boto3
import botocore.config
import botocore.session
import pytest
from alembic import command
from alembic.config import Config
from local_s3 import LocalBucket, local_s3_server
from per_run_database import per_run_database, server_url

from job_board.resumes.store import SETTINGS_FROM_NOWHERE
from job_board.scoring.tracing import TRACING_VARIABLES

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(autouse=True)
def no_tracing_custom_headers_or_library_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs with LangSmith tracing, the SDK's custom headers and its log unset.

    So none can send a trace, none sends a header the environment added, and
    none is refused for the SDK's own logging.
    """
    for name in (*TRACING_VARIABLES, "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_LOG"):
        monkeypatch.delenv(name, raising=False)


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


@pytest.fixture(scope="session")
def local_s3() -> Iterator[str]:
    """The address of an S3 server on this machine, running for this test run only."""
    with local_s3_server() as address:
        yield address


@pytest.fixture
def s3_bucket(local_s3: str) -> Iterator[LocalBucket]:
    """A bucket of one test's own on the local S3 server, emptied and removed after."""
    # Built as the service builds its own, reading nothing from the shell's
    # AWS_ variables, ~/.aws or proxy variables, which a test may also set.
    session = botocore.session.Session(session_vars=SETTINGS_FROM_NOWHERE)
    client = boto3.session.Session(botocore_session=session).client(
        "s3",
        endpoint_url=local_s3,
        region_name="us-east-1",
        aws_access_key_id="local-s3-owner",
        aws_secret_access_key="local-s3-owner-secret",
        config=botocore.config.Config(proxies={}),
    )
    bucket = LocalBucket(f"resumes-{secrets.token_hex(6)}", client)
    client.create_bucket(Bucket=bucket.name)
    try:
        yield bucket
    finally:
        for key in bucket.stored_keys():
            client.delete_object(Bucket=bucket.name, Key=key)
        client.delete_bucket(Bucket=bucket.name)
        client.close()
