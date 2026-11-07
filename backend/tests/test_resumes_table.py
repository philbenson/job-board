import secrets
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

LARGEST = 5 * 1024 * 1024


def run(database_url: str, sql: str, **values: Any) -> list[Any]:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            result = connection.execute(text(sql), values)
            return list(result) if result.returns_rows else []
    finally:
        engine.dispose()


def new_person(database_url: str) -> int:
    (row,) = run(
        database_url,
        "INSERT INTO people (clerk_user_id) VALUES (:user) RETURNING id",
        user=f"user_{secrets.token_hex(12)}",
    )
    person_id: int = row.id
    return person_id


def add_resume(database_url: str, person: int, size: int) -> None:
    run(
        database_url,
        "INSERT INTO resumes (person_id, object_key, size_bytes) VALUES (:person, :key, :size)",
        person=person,
        key=f"resumes/{person}.pdf",
        size=size,
    )


def test_a_new_row_is_stamped_with_when_it_was_uploaded(migrated_database_url: str) -> None:
    person = new_person(migrated_database_url)
    add_resume(migrated_database_url, person, LARGEST)

    (row,) = run(
        migrated_database_url,
        "SELECT object_key, size_bytes, uploaded_at FROM resumes WHERE person_id = :person",
        person=person,
    )
    run(migrated_database_url, "DELETE FROM people WHERE id = :person", person=person)

    assert row.object_key == f"resumes/{person}.pdf"
    assert row.size_bytes == LARGEST
    assert row.uploaded_at is not None


@pytest.mark.parametrize("size", [0, LARGEST + 1])
def test_refuses_a_size_no_upload_can_have(migrated_database_url: str, size: int) -> None:
    person = new_person(migrated_database_url)
    try:
        with pytest.raises(IntegrityError, match="ck_resumes_size_bytes"):
            add_resume(migrated_database_url, person, size)
    finally:
        run(migrated_database_url, "DELETE FROM people WHERE id = :person", person=person)


def test_removing_a_person_removes_their_resume_row(migrated_database_url: str) -> None:
    person = new_person(migrated_database_url)
    add_resume(migrated_database_url, person, 1)

    run(migrated_database_url, "DELETE FROM people WHERE id = :person", person=person)

    remaining = run(
        migrated_database_url, "SELECT 1 FROM resumes WHERE person_id = :person", person=person
    )
    assert remaining == []
