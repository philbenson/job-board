"""The checkpoint saver's tables, which the migrations make in place of its own setup.

The saver's ``setup()`` would create and alter its tables itself; the service
never calls it, so the tables are the migrations'. These tests fail when a
saver upgrade changes what its setup builds, before that version can run
against a database whose tables no longer match its queries.
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres.base import MIGRATIONS
from per_run_database import per_run_database, server_url
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy import create_engine, make_url, text

SAVER_TABLES = ("checkpoint_blobs", "checkpoint_migrations", "checkpoint_writes", "checkpoints")

# Each column with its type, nullability and default as the server renders them.
COLUMNS = """
SELECT t.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       pg_get_expr(d.adbin, d.adrelid)
FROM pg_attribute a
JOIN pg_class t ON t.oid = a.attrelid
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE t.relname = ANY(:tables) AND a.attnum > 0 AND NOT a.attisdropped
"""
# Each index by the columns it covers, in order, and whether it is the primary key.
INDEXES = """
SELECT t.relname, i.indisprimary,
       array_agg(a.attname ORDER BY k.position)
FROM pg_index i
JOIN pg_class t ON t.oid = i.indrelid
CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, position)
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
WHERE t.relname = ANY(:tables)
GROUP BY t.relname, i.indexrelid, i.indisprimary
"""

type Shape = set[tuple[object, ...]]


def shape(database_url: str) -> Shape:
    """The saver's tables by their columns and indexes, leaving out every key's and index's name."""
    found: Shape = set()
    engine = create_engine(database_url)
    with engine.connect() as connection:
        parameters = {"tables": list(SAVER_TABLES)}
        for row in connection.execute(text(COLUMNS), parameters):
            found.add(("column", *row))
        for table, primary, columns in connection.execute(text(INDEXES), parameters):
            found.add(("primary key" if primary else "index", table, tuple(columns)))
    engine.dispose()
    return found


def libpq(database_url: str) -> str:
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


async def test_the_migrations_build_the_tables_the_saver_setup_would(
    migrated_database_url: str,
) -> None:
    with per_run_database(server_url()) as saver_database_url:
        async with await AsyncConnection.connect(
            libpq(saver_database_url), autocommit=True, prepare_threshold=0, row_factory=dict_row
        ) as connection:
            await AsyncPostgresSaver(connection).setup()
        from_saver = shape(saver_database_url)
    from_migrations = shape(migrated_database_url)

    # A table neither side has would compare equal and pass unseen.
    assert {row[1] for row in from_saver if row[0] == "column"} == set(SAVER_TABLES)
    assert sorted(from_saver - from_migrations, key=str) == []
    assert sorted(from_migrations - from_saver, key=str) == []


def test_the_migrations_record_every_saver_migration(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    with engine.connect() as connection:
        recorded = list(connection.execute(text("SELECT v FROM checkpoint_migrations ORDER BY v")))
    engine.dispose()
    assert [version for (version,) in recorded] == list(range(len(MIGRATIONS))), (
        "the saver's setup has a migration the revisions do not record: a saver upgrade added "
        "one, and it needs a revision making the same change and recording its version"
    )
