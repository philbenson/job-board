import secrets
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from job_board.interview.failures import INTERVIEW_FAILURES

SAVER_ROWS = {
    "checkpoints": (
        "INSERT INTO checkpoints (thread_id, checkpoint_id, checkpoint) "
        "VALUES (:thread, :step, '{}')"
    ),
    "checkpoint_blobs": (
        "INSERT INTO checkpoint_blobs (thread_id, channel, version, type) "
        "VALUES (:thread, 'messages', :step, 'empty')"
    ),
    "checkpoint_writes": (
        "INSERT INTO checkpoint_writes (thread_id, checkpoint_id, task_id, idx, channel, blob) "
        "VALUES (:thread, :step, 'task', 0, 'messages', '\\x00')"
    ),
}


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


def new_interview(connection: Connection, person_id: int) -> str:
    thread = str(uuid.uuid4())
    connection.execute(
        text("INSERT INTO interviews (person_id, thread_id) VALUES (:person, :thread)"),
        {"person": person_id, "thread": thread},
    )
    for sql in SAVER_ROWS.values():
        connection.execute(text(sql), {"thread": thread, "step": "1"})
    return thread


def saver_rows(connection: Connection, thread: str) -> dict[str, int]:
    return {
        table: connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE thread_id = :thread"), {"thread": thread}
        ).scalar_one()
        for table in SAVER_ROWS
    }


def test_deleting_the_person_deletes_their_interview_and_every_saved_step(
    connection: Connection,
) -> None:
    person = new_person(connection)
    thread = new_interview(connection, person)
    kept = new_interview(connection, new_person(connection))
    assert saver_rows(connection, thread) == dict.fromkeys(SAVER_ROWS, 1)

    connection.execute(text("DELETE FROM people WHERE id = :person"), {"person": person})
    assert (
        connection.execute(
            text("SELECT count(*) FROM interviews WHERE person_id = :person"), {"person": person}
        ).scalar_one()
        == 0
    )
    assert saver_rows(connection, thread) == dict.fromkeys(SAVER_ROWS, 0)
    assert saver_rows(connection, kept) == dict.fromkeys(SAVER_ROWS, 1)


def test_deleting_the_interview_deletes_every_saved_step(connection: Connection) -> None:
    person = new_person(connection)
    thread = new_interview(connection, person)
    connection.execute(text("DELETE FROM interviews WHERE person_id = :person"), {"person": person})
    assert saver_rows(connection, thread) == dict.fromkeys(SAVER_ROWS, 0)


@pytest.mark.parametrize("table", SAVER_ROWS)
def test_refuses_a_saved_step_of_no_interview(connection: Connection, table: str) -> None:
    with pytest.raises(IntegrityError, match="interviews"):
        connection.execute(text(SAVER_ROWS[table]), {"thread": str(uuid.uuid4()), "step": "1"})


def test_an_interview_starts_unclaimed_and_stamped(connection: Connection) -> None:
    person = new_person(connection)
    new_interview(connection, person)
    row = connection.execute(
        text(
            "SELECT run_id, running_since, failure, started_at IS NOT NULL "
            "FROM interviews WHERE person_id = :person"
        ),
        {"person": person},
    ).one()
    assert tuple(row) == (None, None, None, True)


@pytest.mark.parametrize(("run_id", "running_since"), [("a-run", None), (None, "now()")])
def test_refuses_half_a_claim(
    connection: Connection, run_id: str | None, running_since: str | None
) -> None:
    person = new_person(connection)
    new_interview(connection, person)
    with pytest.raises(IntegrityError, match="ck_interviews_claim_whole"):
        connection.execute(
            text(
                f"UPDATE interviews SET run_id = :run, running_since = {running_since or 'NULL'} "
                "WHERE person_id = :person"
            ),
            {"run": run_id, "person": person},
        )


def test_keeps_every_known_failure(connection: Connection) -> None:
    person = new_person(connection)
    new_interview(connection, person)
    for code in INTERVIEW_FAILURES:
        connection.execute(
            text("UPDATE interviews SET failure = :code WHERE person_id = :person"),
            {"code": code, "person": person},
        )


def test_refuses_an_unknown_failure(connection: Connection) -> None:
    person = new_person(connection)
    new_interview(connection, person)
    with pytest.raises(IntegrityError, match="ck_interviews_failure_is_known"):
        connection.execute(
            text("UPDATE interviews SET failure = 'refused-418' WHERE person_id = :person"),
            {"person": person},
        )


def test_refuses_a_second_interview_for_one_person_or_one_thread(connection: Connection) -> None:
    person = new_person(connection)
    thread = new_interview(connection, person)
    with pytest.raises(IntegrityError, match="pk_interviews"), connection.begin_nested():
        connection.execute(
            text("INSERT INTO interviews (person_id, thread_id) VALUES (:person, :thread)"),
            {"person": person, "thread": str(uuid.uuid4())},
        )
    with pytest.raises(IntegrityError, match="uq_interviews_thread_id"):
        connection.execute(
            text("INSERT INTO interviews (person_id, thread_id) VALUES (:person, :thread)"),
            {"person": new_person(connection), "thread": thread},
        )
