"""mv_market_price

Adds a unified per-card market price materialized view:

- ``mv_market_price``: one row per card_id (condition='A'), preferring the
  SNKRDUNK 7-day median when available, falling back to the Cardrush
  condition-A floor.  Carries a ``source_used`` column so callers know
  which signal was used.

The UNIQUE index on ``card_id`` is created in the same migration so
``REFRESH MATERIALIZED VIEW CONCURRENTLY`` works immediately (see
migration 005 + 006 for the same pattern on the other three MVs).

Revision ID: 007_mv_market_price
Revises: 006_mv_spread_unique_index
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "007_mv_market_price"
down_revision: str | Sequence[str] | None = "006_mv_spread_unique_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MV_NAME = "mv_market_price"
_INDEX_NAME = "uq_mv_market_price_card_id"

_CREATE_MV = f"""
CREATE MATERIALIZED VIEW {_MV_NAME} AS
SELECT
    COALESCE(sd.card_id, cr.card_id)   AS card_id,
    COALESCE(sd.median_7d, cr.price)   AS market_price_jpy,
    CASE
        WHEN sd.card_id IS NOT NULL THEN 'snkrdunk'
        ELSE 'cardrush'
    END                                AS source_used
FROM (
    SELECT card_id, price_jpy AS median_7d
    FROM mv_median_7d
    WHERE source = 'snkrdunk' AND condition = 'A'
) sd
FULL OUTER JOIN (
    SELECT card_id, price_jpy AS price
    FROM mv_latest_price
    WHERE source = 'cardrush' AND condition = 'A'
) cr ON sd.card_id = cr.card_id
"""


def upgrade() -> None:
    op.execute(_CREATE_MV)
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX_NAME} ON {_MV_NAME} (card_id)"
    )


def downgrade() -> None:
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {_MV_NAME}")
