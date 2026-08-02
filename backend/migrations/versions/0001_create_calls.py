"""Create the calls table.

One row per call. `record` is the whole `CallRecord` as JSONB and is the source of truth;
the columns beside it are call-level facts lifted out of it so a query need not open the
blob. See `core/db/tables.py`.

No secondary index. Every lookup this app makes is `WHERE id = ?`, and `id` is the
primary key — in CockroachDB that *is* the physical storage order, so it is a point read.
An index on anything else would be dead weight until there is a query that wants it.

Revision ID: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("caller_number", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        # Null while the call is still open; duration is the difference, not a column.
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("record", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("calls")
