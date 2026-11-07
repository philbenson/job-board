"""add the people table

One row per person who has signed in, keyed by Clerk's user id, which is
unique so two first requests at once still make one row.

Revision ID: cfa93d75ce9f
Revises: d6537361a180
Create Date: 2026-11-07 11:54:06.303455
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cfa93d75ce9f"
down_revision: str | Sequence[str] | None = "d6537361a180"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("clerk_user_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people")),
        sa.UniqueConstraint("clerk_user_id", name=op.f("uq_people_clerk_user_id")),
    )


def downgrade() -> None:
    op.drop_table("people")
