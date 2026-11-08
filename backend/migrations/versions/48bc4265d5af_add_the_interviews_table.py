"""add the interviews table

Each person's onboarding interview, at most one, with the claim of the run
holding it and why its last run failed. Deleting an interview, or its person,
deletes the steps the checkpoint saver kept of it.

Revision ID: 48bc4265d5af
Revises: 1179186b5ba0
Create Date: 2026-11-07 20:01:12.070726
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "48bc4265d5af"
down_revision: str | Sequence[str] | None = "1179186b5ba0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The checkpoint saver's tables keyed by thread, each step of which belongs to an interview.
SAVER_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
# The interview's failure codes as this revision knows them, frozen here so a
# later change to the list needs a revision of its own.
FAILURE_IS_KNOWN = (
    "failure IN ('timed-out', 'connection-error', 'rejected', 'not-permitted', "
    "'model-not-found', 'no-credit', 'rate-limited', 'server-error', 'refused', 'cut-off', "
    "'declined', 'empty-reply', 'not-sealed-here', 'unopenable', 'interrupted', 'unexpected')"
)


def upgrade() -> None:
    op.create_table(
        "interviews",
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("running_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(run_id IS NULL) = (running_since IS NULL)", name=op.f("ck_interviews_claim_whole")
        ),
        sa.CheckConstraint(FAILURE_IS_KNOWN, name=op.f("ck_interviews_failure_is_known")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_interviews_person_id_people"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("person_id", name=op.f("pk_interviews")),
        sa.UniqueConstraint("thread_id", name=op.f("uq_interviews_thread_id")),
    )
    for table in SAVER_TABLES:
        op.create_foreign_key(
            op.f(f"fk_{table}_thread_id_interviews"),
            table,
            "interviews",
            ["thread_id"],
            ["thread_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table in SAVER_TABLES:
        op.drop_constraint(op.f(f"fk_{table}_thread_id_interviews"), table, type_="foreignkey")
    op.drop_table("interviews")
