from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
# Every table the migrations create, in name order; base holds alembic_version alone.
HEAD_TABLES = ["alembic_version", "fetch_runs", "postings"]


def query(database_url: str, sql: str) -> list[str]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        result = list(connection.execute(text(sql)).scalars())
    engine.dispose()
    return result


def recorded_revisions(database_url: str) -> list[str]:
    return query(database_url, "SELECT version_num FROM alembic_version")


def public_tables(database_url: str) -> list[str]:
    return query(
        database_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
    )


def test_upgrades_to_head_back_to_base_and_to_head_again(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The migrations read their URL from the settings, as the service does.
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(ALEMBIC_INI)
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None

    command.upgrade(config, "head")
    assert recorded_revisions(database_url) == [head]
    assert public_tables(database_url) == HEAD_TABLES

    # Every downgrade undoes its upgrade: nothing is left behind at base, so a
    # second upgrade does not trip over a table the first one created.
    command.downgrade(config, "base")
    assert recorded_revisions(database_url) == []
    assert public_tables(database_url) == ["alembic_version"]

    command.upgrade(config, "head")
    assert recorded_revisions(database_url) == [head]
    assert public_tables(database_url) == HEAD_TABLES
