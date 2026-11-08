"""The database tables, as SQLAlchemy models.

The migrations are generated from and checked against these models, so a
table changes here first and then in a new migration.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Constraint names are derived, not left to the database, so a migration can
# name the constraint it drops and every database gets the same names. A
# constraint over several columns is named after all of them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Person(Base):
    """Someone who has signed in, once: Clerk's user id is unique."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelKey(Base):
    """A person's own key for a model provider, sealed so only the service can open it.

    One per person and provider. Only the last four characters are kept in the
    clear, to show which key is saved. ``failure`` says why scoring stopped
    using the key, if it did; saving a key again clears it.
    """

    __tablename__ = "model_keys"
    __table_args__ = (
        UniqueConstraint("person_id", "provider"),
        CheckConstraint("provider = 'anthropic'", name="provider_is_known"),
        CheckConstraint(
            "failure IN ('rejected', 'not-permitted', 'no-credit')", name="failure_is_known"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    person_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("people.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text)
    sealed_key: Mapped[bytes] = mapped_column(LargeBinary)
    last_four: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure: Mapped[str | None] = mapped_column(Text)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Posting(Base):
    """One job post on one board of one source, as the posting fetcher last read it.

    The fetcher writes this table: a posting is closed when a later fetch of
    its board no longer lists it, and reopened if it comes back.
    """

    __tablename__ = "postings"
    __table_args__ = (UniqueConstraint("source", "board", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    board: Mapped[str] = mapped_column(Text)
    external_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(Text)
    company_name: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    content_html: Mapped[str | None] = mapped_column(Text)  # the source's HTML, untrusted
    first_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Open postings, newest published first: undated ones after every dated one,
# then first sight and the id, so the order is total. Named by hand, because
# the naming convention's name for three columns runs past PostgreSQL's 63
# characters.
Index(
    "ix_postings_open_newest_published",
    Posting.first_published_at.desc().nulls_last(),
    Posting.first_seen_at.desc(),
    Posting.id.desc(),
    postgresql_where=Posting.closed_at.is_(None),
)


class FetchRun(Base):
    """One attempt to fetch one board, successful or not."""

    __tablename__ = "fetch_runs"
    __table_args__ = (CheckConstraint("outcome IN ('succeeded', 'failed')", name="outcome"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    board: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(Text)
    postings_seen: Mapped[int] = mapped_column(Integer, server_default="0")
    postings_new: Mapped[int] = mapped_column(Integer, server_default="0")
    postings_closed: Mapped[int] = mapped_column(Integer, server_default="0")
    failure: Mapped[str | None] = mapped_column(Text)  # a short code, never raw error text


class ProfileRow(Base):
    """A person's profile, one document per person, written a section at a time.

    The document's shape is ``job_board.profiles.Profile``; the database holds
    it whole so a new section needs no migration.
    """

    __tablename__ = "profiles"

    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResumeRow(Base):
    """What is known of a person's resume, whose file is in the resume store.

    One per person. The file's key in the store is the same for every upload
    by that person, so a new upload replaces the file and this row in place.

    The text read from the file at upload sits beside it: what the reading
    gave, the text when there is some, and when the person checked and saved
    it. Each upload reads its own file and clears the check. A row from before
    the text was read has none of the three.

    Removing a person removes this row but not the file in the store.
    TODO: removing a person's data must also delete their resume from the store.
    """

    __tablename__ = "resumes"
    __table_args__ = (
        CheckConstraint("size_bytes BETWEEN 1 AND 5242880", name="size_bytes"),  # at most 5 MiB
        CheckConstraint(
            "text_state IN ('found', 'cut', 'none_found', 'failed')", name="text_state"
        ),
        # The cap on a resume's text, in characters, as the text rules count them.
        CheckConstraint("char_length(text) BETWEEN 1 AND 15000", name="text_length"),
        CheckConstraint(
            "text_state NOT IN ('found', 'cut') OR text IS NOT NULL", name="text_when_found"
        ),
        CheckConstraint("text_checked_at IS NULL OR text IS NOT NULL", name="text_when_checked"),
    )

    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    object_key: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    text_state: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    text_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Score(Base):
    """One person's rating of one posting, or a note that the model's reply could not be read.

    Invariant: at most one row per person and posting; the per-person lock is
    what keeps a run from paying twice for one rating. An unreadable reply
    holds the place too, and is not retried.
    """

    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("person_id", "posting_id"),
        CheckConstraint("outcome IN ('scored', 'unreadable')", name="outcome"),
        CheckConstraint("score BETWEEN 1 AND 5", name="score_on_the_scale"),
        CheckConstraint(
            "(outcome = 'scored' AND score IS NOT NULL AND reason IS NOT NULL) "
            "OR (outcome <> 'scored' AND score IS NULL AND reason IS NULL)",
            name="rated_exactly_when_scored",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    person_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("people.id", ondelete="CASCADE"))
    posting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postings.id", ondelete="CASCADE")
    )
    outcome: Mapped[str] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)  # the model id that gave the rating
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# The checkpoint saver's tables, as its own setup would leave them after its
# migration 9: the same columns, keys and thread_id indexes, under the saver's
# names. The migrations make them and the service never runs that setup;
# tests/test_checkpoint_tables.py fails when a saver upgrade changes them.


class CheckpointMigration(Base):
    """Which of the saver's migrations the database holds, so its setup would add none."""

    __tablename__ = "checkpoint_migrations"
    __table_args__ = (PrimaryKeyConstraint("v", name="checkpoint_migrations_pkey"),)

    v: Mapped[int] = mapped_column(Integer, autoincrement=False)


class Checkpoint(Base):
    """One saved step of a thread: the state's channel versions, its blobs stored apart."""

    __tablename__ = "checkpoints"
    __table_args__ = (
        PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "checkpoint_id", name="checkpoints_pkey"
        ),
        Index("checkpoints_thread_id_idx", "thread_id"),
    )

    thread_id: Mapped[str] = mapped_column(Text)
    checkpoint_ns: Mapped[str] = mapped_column(Text, server_default=text("''"))
    checkpoint_id: Mapped[str] = mapped_column(Text)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The attribute cannot be called metadata, which the declarative base keeps for itself.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )


class CheckpointBlob(Base):
    """One channel's value at one version, shared by every step that did not change it."""

    __tablename__ = "checkpoint_blobs"
    __table_args__ = (
        PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "channel", "version", name="checkpoint_blobs_pkey"
        ),
        Index("checkpoint_blobs_thread_id_idx", "thread_id"),
    )

    thread_id: Mapped[str] = mapped_column(Text)
    checkpoint_ns: Mapped[str] = mapped_column(Text, server_default=text("''"))
    channel: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    blob: Mapped[bytes | None] = mapped_column(LargeBinary)


class CheckpointWrite(Base):
    """A write a task made toward the next step, kept so a resumed step need not repeat it."""

    __tablename__ = "checkpoint_writes"
    __table_args__ = (
        PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
            name="checkpoint_writes_pkey",
        ),
        Index("checkpoint_writes_thread_id_idx", "thread_id"),
    )

    thread_id: Mapped[str] = mapped_column(Text)
    checkpoint_ns: Mapped[str] = mapped_column(Text, server_default=text("''"))
    checkpoint_id: Mapped[str] = mapped_column(Text)
    task_id: Mapped[str] = mapped_column(Text)
    idx: Mapped[int] = mapped_column(Integer, autoincrement=False)
    channel: Mapped[str] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    task_path: Mapped[str] = mapped_column(Text, server_default=text("''"))
