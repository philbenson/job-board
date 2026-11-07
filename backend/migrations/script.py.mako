"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
% if imports:
${imports}
% endif

<%
    def quoted(value):
        # repr() with the double quotes ruff format writes
        return repr(value).replace("'", '"')
%>\
revision: str = ${quoted(up_revision)}
down_revision: str | Sequence[str] | None = ${quoted(down_revision)}
branch_labels: str | Sequence[str] | None = ${quoted(branch_labels)}
depends_on: str | Sequence[str] | None = ${quoted(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
