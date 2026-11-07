"""add the postings and fetch runs tables

The posting fetcher writes both tables and never creates or alters one: their
shape is owned here. A posting is one job post on one board of one source; it
is closed when a later fetch of its board no longer lists it, and reopened if
it comes back. Each attempt to fetch a board, successful or not, is one row of
fetch_runs.

Revision ID: 9fe5638962f4
Revises: cfa93d75ce9f
Create Date: 2026-11-07 11:48:05.097612
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9fe5638962f4"
down_revision: str | Sequence[str] | None = "cfa93d75ce9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "postings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("board", sa.Text(), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),  # the source's HTML, untrusted
        sa.Column("first_published_at", TIMESTAMP, nullable=True),
        sa.Column("source_updated_at", TIMESTAMP, nullable=False),
        sa.Column("first_seen_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.UniqueConstraint(
            "source", "board", "external_id", name="postings_source_board_external_id_key"
        ),
    )
    # Serves open postings newest first, without reading closed ones. Newest
    # means when the company published the posting, not when this system first
    # saw it: a board's first fetch gives all its postings one first_seen_at,
    # while their publish times tell them apart. Postings without a publish time
    # sort after every dated one; first sight and then the id break ties, so the
    # order is total and the same on every read.
    op.create_index(
        "postings_open_newest_published_idx",
        "postings",
        [
            sa.text("first_published_at DESC NULLS LAST"),
            sa.text("first_seen_at DESC"),
            sa.text("id DESC"),
        ],
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("board", sa.Text(), nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("finished_at", TIMESTAMP, nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("postings_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("postings_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("postings_closed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure", sa.Text(), nullable=True),  # a short code, never raw error text
        sa.CheckConstraint("outcome IN ('succeeded', 'failed')", name="fetch_runs_outcome_check"),
    )


def downgrade() -> None:
    op.drop_table("fetch_runs")
    op.drop_index("postings_open_newest_published_idx", table_name="postings")
    op.drop_table("postings")
