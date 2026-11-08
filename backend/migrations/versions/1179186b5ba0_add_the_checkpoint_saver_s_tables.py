"""add the checkpoint saver's tables

The tables LangGraph's PostgreSQL checkpoint saver keeps an interview's steps
in, as its own setup leaves them after its migration 9, and the record that
the database holds its migrations 0 to 9, so its setup would add nothing.
The service never runs that setup: a saver upgrade that changes its tables
needs a revision of its own.

Revision ID: 1179186b5ba0
Revises: 9ac7735e49d8
Create Date: 2026-11-07 19:59:15.812971
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1179186b5ba0"
down_revision: str | Sequence[str] | None = "9ac7735e49d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The saver's migrations this revision stands in for, written out rather than
# read from the installed saver, so the revision means the same thing after an upgrade.
SAVER_MIGRATIONS = range(10)


def upgrade() -> None:
    migrations = op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("v", name="checkpoint_migrations_pkey"),
    )
    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "checkpoint_id", name="checkpoints_pkey"
        ),
    )
    op.create_index("checkpoints_thread_id_idx", "checkpoints", ["thread_id"])
    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=True),
        sa.PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "channel", "version", name="checkpoint_blobs_pkey"
        ),
    )
    op.create_index("checkpoint_blobs_thread_id_idx", "checkpoint_blobs", ["thread_id"])
    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
            name="checkpoint_writes_pkey",
        ),
    )
    op.create_index("checkpoint_writes_thread_id_idx", "checkpoint_writes", ["thread_id"])
    op.bulk_insert(migrations, [{"v": version} for version in SAVER_MIGRATIONS])


def downgrade() -> None:
    op.drop_index("checkpoint_writes_thread_id_idx", table_name="checkpoint_writes")
    op.drop_table("checkpoint_writes")
    op.drop_index("checkpoint_blobs_thread_id_idx", table_name="checkpoint_blobs")
    op.drop_table("checkpoint_blobs")
    op.drop_index("checkpoints_thread_id_idx", table_name="checkpoints")
    op.drop_table("checkpoints")
    op.drop_table("checkpoint_migrations")
