"""The models and the migrations at head build the same schema, read from the catalog.

Both databases are read from PostgreSQL's own catalog, so one server renders
each side's definitions in its canonical form and most spellings compare equal
('{}' and '{}'::jsonb, 'false' and false). A few stay as written, such as
CURRENT_TIMESTAMP against now(), and fail the comparison.

Compared: each table's columns (type, collation, nullability, default, identity
kind and its sequence's options, generated expression), constraints and
indexes, and each enum type's labels in order. Only the public schema is read,
so a model placed in another schema fails the test: its table goes unread.

Not compared:
- schemas other than public
- privileges
- comments
- triggers and functions
- sequences no identity column owns
"""

from per_run_database import per_run_database, server_url
from sqlalchemy import create_engine, text

from job_board.models import Base

# What one database holds, keyed by table (or enum type), kind ("column",
# "constraint", "index" or "enum") and name, each mapped to its definition as
# the server renders it.
type Catalog = dict[tuple[str, str, str], str]

# The migrations' own bookkeeping, which the models never describe.
MIGRATIONS_TABLE = "alembic_version"
IDENTITY_KINDS = {"a": "always", "d": "by default"}  # pg_attribute.attidentity
GENERATED_KINDS = {"s": "stored", "v": "virtual"}  # pg_attribute.attgenerated

# A collation is read only where it differs from its type's default; an
# identity column's sequence is read by its options, never its name.
COLUMNS = """
SELECT t.relname, a.attname, format_type(a.atttypid, a.atttypmod), co.collname,
       a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attidentity, a.attgenerated,
       CASE WHEN s.seqrelid IS NOT NULL THEN
         format('start %s increment %s minimum %s maximum %s cache %s %s',
                s.seqstart, s.seqincrement, s.seqmin, s.seqmax, s.seqcache,
                CASE WHEN s.seqcycle THEN 'cycle' ELSE 'no cycle' END)
       END
FROM pg_attribute a
JOIN pg_class t ON t.oid = a.attrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_type ty ON ty.oid = a.atttypid
LEFT JOIN pg_collation co ON co.oid = a.attcollation AND a.attcollation <> ty.typcollation
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
LEFT JOIN pg_sequence s ON a.attidentity <> '' AND s.seqrelid =
  pg_get_serial_sequence(format('%I.%I', n.nspname, t.relname), a.attname)::regclass
WHERE n.nspname = 'public' AND t.relkind IN ('r', 'p') AND t.relname <> :skipped
  AND a.attnum > 0 AND NOT a.attisdropped
"""
# PostgreSQL 18 lists each NOT NULL as a constraint too; those are left out,
# because nullability is already compared on the column and their names are
# chosen by the server, not by the models or the migrations.
CONSTRAINTS = """
SELECT t.relname, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public' AND t.relname <> :skipped AND c.contype <> 'n'
"""
INDEXES = """
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename <> :skipped
"""
ENUMS = """
SELECT t.typname, 'labels', string_agg(quote_literal(e.enumlabel), ', ' ORDER BY e.enumsortorder)
FROM pg_enum e
JOIN pg_type t ON t.oid = e.enumtypid
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
GROUP BY t.typname
"""


def column_definition(
    type_name: str,
    collation: str | None,
    not_null: bool,
    expression: str | None,
    identity: str,
    generated: str,
    sequence: str | None,
) -> str:
    parts = [type_name]
    if collation is not None:
        parts.append(f'collate "{collation}"')
    if not_null:
        parts.append("not null")
    if identity:
        parts.append(f"generated {IDENTITY_KINDS.get(identity, identity)} as identity")
        if sequence is not None:
            parts.append(f"({sequence})")
    if generated:  # a generated column keeps its expression where a default would be
        parts.append(
            f"generated always as ({expression}) {GENERATED_KINDS.get(generated, generated)}"
        )
    elif expression is not None:
        parts.append(f"default {expression}")
    return " ".join(parts)


def catalog(database_url: str) -> Catalog:
    """Every column, constraint and index of the public schema's tables, and its enum types."""
    found: Catalog = {}
    engine = create_engine(database_url)
    with engine.connect() as connection:
        parameters = {"skipped": MIGRATIONS_TABLE}
        for table, name, *details in connection.execute(text(COLUMNS), parameters):
            found[(table, "column", name)] = column_definition(*details)
        for kind, sql in (("constraint", CONSTRAINTS), ("index", INDEXES), ("enum", ENUMS)):
            for table, name, definition in connection.execute(text(sql), parameters):
                found[(table, kind, name)] = definition
    engine.dispose()
    return found


def differences(from_models: Catalog, from_migrations: Catalog) -> list[str]:
    """One entry per thing the two sides disagree on, with each side's definition."""
    found = []
    for key in sorted(from_models.keys() | from_migrations.keys()):
        models, migrations = from_models.get(key), from_migrations.get(key)
        if models != migrations:
            table, kind, name = key
            found.append(
                f"{table} {kind} {name}\n"
                f"  models:     {models or '(absent)'}\n"
                f"  migrations: {migrations or '(absent)'}"
            )
    return found


# Beside alembic check, which never compares a partial index's WHERE or a check
# constraint's expression, and skips server defaults, identity kinds and generated
# columns' expressions because migrations/env.py leaves compare_server_default off.
def test_the_models_and_the_migrations_build_the_same_catalog(migrated_database_url: str) -> None:
    with per_run_database(server_url()) as models_database_url:
        engine = create_engine(models_database_url)
        Base.metadata.create_all(engine)
        engine.dispose()
        from_models = catalog(models_database_url)
    from_migrations = catalog(migrated_database_url)

    # A table the read misses would be compared on neither side and pass unseen.
    read = {table for table, kind, _ in from_models if kind == "column"}
    assert read == set(Base.metadata.tables)
    found = differences(from_models, from_migrations)
    assert not found, "\n".join(found)
