import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import per_run_database as module
import pytest
from per_run_database import STALE_AFTER, START_COMMAND, per_run_database, server_url
from sqlalchemy import URL, create_engine, make_url, text

NAME = re.compile(r"job_board_test_\d{14}_[0-9a-f]+")


def existing(server: URL, names: list[str]) -> set[str]:
    admin = create_engine(server)
    with admin.connect() as connection:
        found = connection.execute(
            text("SELECT datname FROM pg_database WHERE datname = ANY(:names)"), {"names": names}
        ).scalars()
        result = set(found)
    admin.dispose()
    return result


@contextmanager
def databases(server: URL, names: list[str]) -> Iterator[None]:
    """Create databases by name for a test, and drop whatever is left of them after."""
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            for name in names:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield
    finally:
        with admin.connect() as connection:
            for name in names:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_creates_a_fresh_database_and_drops_it() -> None:
    server = server_url()
    with per_run_database(server) as url:
        name = make_url(url).database
        assert name is not None
        assert NAME.fullmatch(name)
        assert name != server.database
        engine = create_engine(url)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar_one() == name
        engine.dispose()
    assert existing(server, [name]) == set()


def test_two_runs_at_once_get_different_databases() -> None:
    server = server_url()
    with per_run_database(server) as first, per_run_database(server) as second:
        assert make_url(first).database != make_url(second).database


def test_drops_test_databases_older_than_a_day_and_nothing_else() -> None:
    server = server_url()
    now = datetime.now(UTC)
    stamp = "%Y%m%d%H%M%S"
    stale = f"job_board_test_{(now - STALE_AFTER - timedelta(hours=1)):{stamp}}_0123456789ab"
    recent = f"job_board_test_{(now - timedelta(hours=1)):{stamp}}_0123456789ab"
    unparsable = "job_board_test_0123456789ab"
    with databases(server, [stale, recent, unparsable]), per_run_database(server):
        assert existing(server, [stale, recent, unparsable]) == {recent, unparsable}


def test_reads_the_example_file_when_no_url_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    example = tmp_path / ".env.example"
    example.write_text(
        "# a comment\nDATABASE_URL=postgres://someone:pw@db.example.com:6543/other\n"
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(module, "EXAMPLE_FILE", example)
    url = server_url()
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database) == ("db.example.com", 6543, "other")


def test_prefers_the_database_url_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://someone:pw@db.example.com:6543/other")
    url = server_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "db.example.com"


def test_an_unreachable_server_fails_the_run_with_the_start_command(closed_port: int) -> None:
    server = make_url(f"postgresql+psycopg://job_board:s3cret@127.0.0.1:{closed_port}/job_board")
    with pytest.raises(pytest.fail.Exception) as raised, per_run_database(server):
        pass
    message = str(raised.value)
    assert "could not connect to PostgreSQL" in message
    assert START_COMMAND in message
    for leak in ("s3cret", str(closed_port), "127.0.0.1"):
        assert leak not in message
