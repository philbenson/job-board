"""add the scores table and key failures

Each person's rating of each posting, at most one per posting, and on each
model key the reason scoring stopped using it, if it did.

Revision ID: 0379d9403735
Revises: 50648919cc44
Create Date: 2026-11-07 15:16:03.869422
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0379d9403735"
down_revision: str | Sequence[str] | None = "50648919cc44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("posting_id", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(outcome = 'scored' AND score IS NOT NULL AND reason IS NOT NULL) "
            "OR (outcome <> 'scored' AND score IS NULL AND reason IS NULL)",
            name=op.f("ck_scores_rated_exactly_when_scored"),
        ),
        sa.CheckConstraint("outcome IN ('scored', 'unreadable')", name=op.f("ck_scores_outcome")),
        sa.CheckConstraint("score BETWEEN 1 AND 5", name=op.f("ck_scores_score_on_the_scale")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_scores_person_id_people"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["postings.id"],
            name=op.f("fk_scores_posting_id_postings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scores")),
        sa.UniqueConstraint("person_id", "posting_id", name=op.f("uq_scores_person_id_posting_id")),
    )
    op.add_column("model_keys", sa.Column("failure", sa.Text(), nullable=True))
    op.add_column("model_keys", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    # Autogenerate does not compare check constraints, so this one is written by hand.
    op.create_check_constraint(
        op.f("ck_model_keys_failure_is_known"),
        "model_keys",
        "failure IN ('rejected', 'not-permitted', 'no-credit')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_model_keys_failure_is_known"), "model_keys", type_="check")
    op.drop_column("model_keys", "failed_at")
    op.drop_column("model_keys", "failure")
    op.drop_table("scores")
