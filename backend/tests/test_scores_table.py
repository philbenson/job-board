import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from job_board.model_key.check import CHECK_MODEL


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


def new_posting(connection: Connection) -> int:
    posting_id: int = connection.execute(
        text(
            "INSERT INTO postings (source, board, external_id, title, url, source_updated_at, "
            "first_seen_at, last_seen_at) VALUES ('greenhouse', 'example', :external, "
            "'Engineer', 'https://boards.example.com/1', now(), now(), now()) RETURNING id"
        ),
        {"external": secrets.randbelow(10**12)},
    ).scalar_one()
    return posting_id


def add_score(
    connection: Connection,
    person_id: int,
    posting_id: int,
    outcome: str = "scored",
    score: int | None = 4,
    reason: str | None = "A close match.",
) -> None:
    connection.execute(
        text(
            "INSERT INTO scores (person_id, posting_id, outcome, score, reason, model) "
            "VALUES (:person, :posting, :outcome, :score, :reason, :model)"
        ),
        {
            "person": person_id,
            "posting": posting_id,
            "outcome": outcome,
            "score": score,
            "reason": reason,
            "model": CHECK_MODEL,
        },
    )


def scores_of(connection: Connection, person_id: int) -> list[tuple[str, int | None]]:
    rows = connection.execute(
        text("SELECT outcome, score FROM scores WHERE person_id = :person ORDER BY id"),
        {"person": person_id},
    )
    return [(outcome, score) for outcome, score in rows]


def test_keeps_a_score_and_an_unreadable_reply_stamped(connection: Connection) -> None:
    person = new_person(connection)
    add_score(connection, person, new_posting(connection))
    add_score(connection, person, new_posting(connection), "unreadable", None, None)
    assert scores_of(connection, person) == [("scored", 4), ("unreadable", None)]
    stamped = connection.execute(
        text("SELECT bool_and(scored_at IS NOT NULL) FROM scores WHERE person_id = :person"),
        {"person": person},
    ).scalar_one()
    assert stamped is True


def test_rates_a_posting_at_most_once_per_person(connection: Connection) -> None:
    person, posting = new_person(connection), new_posting(connection)
    add_score(connection, person, posting)
    add_score(connection, new_person(connection), posting)  # another person's is their own
    with pytest.raises(IntegrityError, match="uq_scores_person_id_posting_id"):
        add_score(connection, person, posting, "unreadable", None, None)


@pytest.mark.parametrize("score", [0, 6])
def test_takes_a_score_only_from_one_to_five(connection: Connection, score: int) -> None:
    with pytest.raises(IntegrityError, match="ck_scores_score_on_the_scale"):
        add_score(connection, new_person(connection), new_posting(connection), score=score)


def test_takes_only_a_known_outcome(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="ck_scores_outcome"):
        add_score(connection, new_person(connection), new_posting(connection), "skipped")


@pytest.mark.parametrize(
    ("outcome", "score", "reason"),
    [
        ("scored", None, "A close match."),
        ("scored", 4, None),
        ("unreadable", 4, None),
        ("unreadable", None, "A close match."),
    ],
)
def test_holds_a_score_and_reason_exactly_when_the_posting_was_scored(
    connection: Connection, outcome: str, score: int | None, reason: str | None
) -> None:
    with pytest.raises(IntegrityError, match="ck_scores_rated_exactly_when_scored"):
        add_score(
            connection, new_person(connection), new_posting(connection), outcome, score, reason
        )


@pytest.mark.parametrize("table", ["people", "postings"])
def test_goes_when_its_person_or_posting_goes(connection: Connection, table: str) -> None:
    person, posting = new_person(connection), new_posting(connection)
    add_score(connection, person, posting)
    gone = person if table == "people" else posting
    connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": gone})
    assert scores_of(connection, person) == []


def test_belongs_to_a_person_and_a_posting_that_exist(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="fk_scores_person_id_people"):
        add_score(connection, -1, new_posting(connection))
    connection.rollback()
    with pytest.raises(IntegrityError, match="fk_scores_posting_id_postings"):
        add_score(connection, new_person(connection), -1)
