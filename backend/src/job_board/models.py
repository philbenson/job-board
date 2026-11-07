"""The database tables, as SQLAlchemy models.

The migrations are generated from and checked against these models, so a
table changes here first and then in a new migration.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, Text, func
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
