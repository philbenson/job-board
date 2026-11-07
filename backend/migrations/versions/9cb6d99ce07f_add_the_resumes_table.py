"""add the resumes table

One row per person describing their resume, whose file is kept in the resume
store: its key there, its size, from 1 byte to 5 MiB, and when it was
uploaded. The row goes when the person does; the file in the store does not.

Revision ID: 9cb6d99ce07f
Revises: 0379d9403735
Create Date: 2026-11-07 15:23:30.053607
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9cb6d99ce07f"
down_revision: str | Sequence[str] | None = "0379d9403735"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 5242880", name=op.f("ck_resumes_size_bytes")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_resumes_person_id_people"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("person_id", name=op.f("pk_resumes")),
    )


def downgrade() -> None:
    op.drop_table("resumes")
