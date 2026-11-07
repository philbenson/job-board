import secrets
from typing import Any

from sqlalchemy import create_engine, text


def run(database_url: str, sql: str, **values: Any) -> list[Any]:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        result = connection.execute(text(sql), values)
        rows = list(result) if result.returns_rows else []
    engine.dispose()
    return rows


def new_person(database_url: str) -> int:
    (row,) = run(
        database_url,
        "INSERT INTO people (clerk_user_id) VALUES (:user) RETURNING id",
        user=f"user_{secrets.token_hex(12)}",
    )
    person_id: int = row.id
    return person_id


def test_a_new_row_holds_an_empty_document_and_both_times(migrated_database_url: str) -> None:
    person = new_person(migrated_database_url)
    run(migrated_database_url, "INSERT INTO profiles (person_id) VALUES (:person)", person=person)

    (row,) = run(
        migrated_database_url,
        "SELECT document, created_at, updated_at FROM profiles WHERE person_id = :person",
        person=person,
    )
    run(migrated_database_url, "DELETE FROM people WHERE id = :person", person=person)

    assert row.document == {}
    assert row.created_at is not None
    assert row.created_at == row.updated_at


def test_removing_a_person_removes_their_profile(migrated_database_url: str) -> None:
    person = new_person(migrated_database_url)
    run(migrated_database_url, "INSERT INTO profiles (person_id) VALUES (:person)", person=person)

    run(migrated_database_url, "DELETE FROM people WHERE id = :person", person=person)

    remaining = run(
        migrated_database_url, "SELECT 1 FROM profiles WHERE person_id = :person", person=person
    )
    assert remaining == []
