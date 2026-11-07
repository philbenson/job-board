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
    clear, to show which key is saved.
    """

    __tablename__ = "model_keys"
    __table_args__ = (
        UniqueConstraint("person_id", "provider"),
        CheckConstraint("provider = 'anthropic'", name="provider_is_known"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    person_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("people.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text)
    sealed_key: Mapped[bytes] = mapped_column(LargeBinary)
    last_four: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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
