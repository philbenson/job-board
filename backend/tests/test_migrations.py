from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def recorded_revisions(database_url: str) -> list[str]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        result = list(revisions)
    engine.dispose()
    return result


def test_upgrades_to_head_and_back_to_base(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The migrations read their URL from the settings, as the service does.
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(ALEMBIC_INI)
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None

    command.upgrade(config, "head")
    assert recorded_revisions(database_url) == [head]

    command.downgrade(config, "base")
    assert recorded_revisions(database_url) == []
