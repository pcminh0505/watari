"""add_materialized_views

Revision ID: 41bdc53fd9e9
Revises: 29ab4e8079f1
Create Date: 2026-04-21 17:08:13.414097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41bdc53fd9e9'
down_revision: Union[str, Sequence[str], None] = '29ab4e8079f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE MATERIALIZED VIEW mv_latest_price AS
        SELECT DISTINCT ON (card_id, source, condition)
            card_id, source, condition, price_jpy, stock_qty, observed_at
        FROM price_points
        ORDER BY card_id, source, condition, observed_at DESC
    """)
    op.execute(
        "CREATE UNIQUE INDEX ON mv_latest_price(card_id, source, condition)"
    )

    op.execute("""
        CREATE MATERIALIZED VIEW mv_median_7d AS
        SELECT card_id, condition,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price_jpy) AS median_jpy,
               COUNT(*) AS sample_size
        FROM price_points
        WHERE source = 'snkrdunk' AND source_type = 'sold'
          AND observed_at > now() - interval '7 days'
        GROUP BY card_id, condition
    """)
    op.execute(
        "CREATE UNIQUE INDEX ON mv_median_7d(card_id, condition)"
    )

    op.execute("""
        CREATE MATERIALIZED VIEW mv_cross_source_spread AS
        SELECT cr.card_id, cr.condition,
               cr.min_listing_jpy AS cardrush_floor,
               sd.median_jpy AS snkrdunk_median_7d,
               cr.min_listing_jpy - sd.median_jpy AS spread_jpy,
               CASE WHEN sd.median_jpy > 0
                    THEN (cr.min_listing_jpy - sd.median_jpy)::float / sd.median_jpy
                    ELSE NULL END AS spread_pct
        FROM (SELECT card_id, condition, MIN(price_jpy) AS min_listing_jpy
              FROM mv_latest_price
              WHERE source = 'cardrush' AND stock_qty > 0
              GROUP BY card_id, condition) cr
        JOIN mv_median_7d sd USING (card_id, condition)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")
