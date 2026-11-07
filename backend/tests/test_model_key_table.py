import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection]:
    """A connection whose writes are rolled back when the test ends."""
    engine = create_engine(migrated_database_url)
    with engine.connect() as connection:
        yield connection
        connection.rollback()
    engine.dispose()


def new_person(connection: Connection) -> int:
    person_id: int = connection.execute(
        text("INSERT INTO people (clerk_user_id) VALUES (:user) RETURNING id"),
        {"user": f"user_{secrets.token_hex(12)}"},
    ).scalar_one()
    return person_id


def add_key(connection: Connection, person_id: int, provider: str = "anthropic") -> Any:
    return connection.execute(
        text(
            "INSERT INTO model_keys (person_id, provider, sealed_key, last_four, checked_at) "
            "VALUES (:person, :provider, :sealed, 'abcd', now()) "
            "RETURNING created_at, updated_at"
        ),
        {"person": person_id, "provider": provider, "sealed": b"\x01sealed"},
    ).one()


def keys_of(connection: Connection, person_id: int) -> list[str]:
    return list(
        connection.execute(
            text("SELECT provider FROM model_keys WHERE person_id = :person"),
            {"person": person_id},
        ).scalars()
    )


def test_keeps_a_sealed_key_and_stamps_it(connection: Connection) -> None:
    person = new_person(connection)
    created_at, updated_at = add_key(connection, person)
    assert created_at is not None
    assert updated_at is not None
    assert keys_of(connection, person) == ["anthropic"]


def test_holds_one_key_per_person_and_provider(connection: Connection) -> None:
    person = new_person(connection)
    add_key(connection, person)
    add_key(connection, new_person(connection))  # another person's is their own
    with pytest.raises(IntegrityError, match="uq_model_keys_person_id_provider"):
        add_key(connection, person)


def test_takes_only_a_known_provider(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="ck_model_keys_provider_is_known"):
        add_key(connection, new_person(connection), provider="another")


def test_goes_when_its_person_goes(connection: Connection) -> None:
    person = new_person(connection)
    add_key(connection, person)
    connection.execute(text("DELETE FROM people WHERE id = :person"), {"person": person})
    assert keys_of(connection, person) == []


def test_belongs_to_a_person_who_exists(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="fk_model_keys_person_id_people"):
        add_key(connection, person_id=-1)


def failure_of(connection: Connection, person_id: int) -> tuple[str | None, object]:
    failure, failed_at = connection.execute(
        text("SELECT failure, failed_at FROM model_keys WHERE person_id = :person"),
        {"person": person_id},
    ).one()
    return failure, failed_at


def test_starts_with_no_failure(connection: Connection) -> None:
    person = new_person(connection)
    add_key(connection, person)
    assert failure_of(connection, person) == (None, None)


@pytest.mark.parametrize("failure", ["rejected", "not-permitted", "no-credit"])
def test_records_a_known_failure(connection: Connection, failure: str) -> None:
    person = new_person(connection)
    add_key(connection, person)
    connection.execute(
        text("UPDATE model_keys SET failure = :failure, failed_at = now() WHERE person_id = :p"),
        {"failure": failure, "p": person},
    )
    recorded, failed_at = failure_of(connection, person)
    assert recorded == failure
    assert failed_at is not None


def test_takes_only_a_known_failure(connection: Connection) -> None:
    person = new_person(connection)
    add_key(connection, person)
    with pytest.raises(IntegrityError, match="ck_model_keys_failure_is_known"):
        connection.execute(
            text("UPDATE model_keys SET failure = 'expired' WHERE person_id = :p"), {"p": person}
        )
