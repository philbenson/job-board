"""add the model keys table

Each person's own key for a model provider, sealed so only the service can
open it, with its last four characters in the clear. One per person and
provider; a person's keys go when the person does.

Revision ID: 95bda4472598
Revises: cfa93d75ce9f
Create Date: 2026-11-07 12:45:05.917837
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "95bda4472598"
down_revision: str | Sequence[str] | None = "cfa93d75ce9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("sealed_key", sa.LargeBinary(), nullable=False),
        sa.Column("last_four", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("provider = 'anthropic'", name=op.f("ck_model_keys_provider_is_known")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_model_keys_person_id_people"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_keys")),
        sa.UniqueConstraint("person_id", "provider", name=op.f("uq_model_keys_person_id_provider")),
    )


def downgrade() -> None:
    op.drop_table("model_keys")
