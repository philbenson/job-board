from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
# Every table the migrations create, in name order; base holds alembic_version alone.
HEAD_TABLES = [
    "alembic_version",
    "fetch_runs",
    "model_keys",
    "people",
    "postings",
    "profiles",
    "resumes",
]
# The key, unique and check constraints of the fetcher's tables, in name order,
# each named by the models' naming convention.
FETCHER_CONSTRAINTS = [
    "ck_fetch_runs_outcome",
    "pk_fetch_runs",
    "pk_postings",
    "uq_postings_source_board_external_id",
]
# Open postings, newest published first; undated ones after every dated one;
# first sight and then the id break ties, so the order is total and stable.
OPEN_POSTINGS_INDEX = (
    "CREATE INDEX ix_postings_open_newest_published ON public.postings USING btree "
    "(first_published_at DESC NULLS LAST, first_seen_at DESC, id DESC) WHERE (closed_at IS NULL)"
)


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


def postings_indexes(database_url: str) -> list[str]:
    return query(
        database_url,
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'postings' "
        "AND indexname NOT IN ('pk_postings', 'uq_postings_source_board_external_id')",
    )


def fetcher_constraints(database_url: str) -> list[str]:
    # PostgreSQL also lists each NOT NULL as a constraint; those are left out.
    return query(
        database_url,
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid IN ('postings'::regclass, 'fetch_runs'::regclass) "
        "AND contype IN ('p', 'u', 'c') ORDER BY 1",
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
    assert postings_indexes(database_url) == [OPEN_POSTINGS_INDEX]
    assert fetcher_constraints(database_url) == FETCHER_CONSTRAINTS


def test_the_models_match_the_migrations_at_head(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    # Raises when autogenerate would write anything: a model changed without
    # its migration, or a migration without its model.
    command.check(config)
