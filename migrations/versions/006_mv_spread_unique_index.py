"""mv_spread_unique_index

Adds a unique index on ``mv_cross_source_spread(card_id, condition)`` so
``REFRESH MATERIALIZED VIEW CONCURRENTLY`` works for all three price MVs.

``mv_latest_price`` and ``mv_median_7d`` already had unique indexes from
the 005_artworks_split migration; only this one was missing. The join
shape guarantees uniqueness on ``(card_id, condition)`` (it's the GROUP BY
key of the cardrush CTE joined to ``mv_median_7d`` which itself is unique
on those columns), so adding the index can't fail on current data.

Revision ID: 006_mv_spread_unique_index
Revises: 005_artworks_split
Create Date: 2026-04-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "006_mv_spread_unique_index"
down_revision: str | Sequence[str] | None = "005_artworks_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "mv_cross_source_spread_pk_ux"


def upgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
        f"ON mv_cross_source_spread (card_id, condition)",
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
