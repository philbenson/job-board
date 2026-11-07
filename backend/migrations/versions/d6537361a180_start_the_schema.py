"""start the schema

The first revision is empty: it gives every later one a common base.

Revision ID: d6537361a180
Revises: none
Create Date: 2026-11-07 10:57:41.620037
"""

from collections.abc import Sequence

revision: str = "d6537361a180"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
