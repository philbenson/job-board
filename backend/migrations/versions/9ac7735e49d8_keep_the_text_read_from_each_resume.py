"""keep the text read from each resume

What reading the file's text at upload gave: its state, one of found, cut,
none_found and failed; the text, from 1 to 15,000 characters, when there is
some; and when the person last checked and saved it. Found and cut always
have text, and a checked text is always there. A row from before this
revision has none of the three.

Revision ID: 9ac7735e49d8
Revises: 9cb6d99ce07f
Create Date: 2026-11-07 17:54:51.115537
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9ac7735e49d8"
down_revision: str | Sequence[str] | None = "9cb6d99ce07f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = {
    "text_state": "text_state IN ('found', 'cut', 'none_found', 'failed')",
    "text_length": "char_length(text) BETWEEN 1 AND 15000",
    "text_when_found": "text_state NOT IN ('found', 'cut') OR text IS NOT NULL",
    "text_when_checked": "text_checked_at IS NULL OR text IS NOT NULL",
}


def upgrade() -> None:
    op.add_column("resumes", sa.Column("text_state", sa.Text(), nullable=True))
    op.add_column("resumes", sa.Column("text", sa.Text(), nullable=True))
    op.add_column(
        "resumes", sa.Column("text_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Autogenerate does not compare check constraints, so these are written by hand.
    for name, condition in CHECKS.items():
        op.create_check_constraint(op.f(f"ck_resumes_{name}"), "resumes", condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(op.f(f"ck_resumes_{name}"), "resumes", type_="check")
    op.drop_column("resumes", "text_checked_at")
    op.drop_column("resumes", "text")
    op.drop_column("resumes", "text_state")
