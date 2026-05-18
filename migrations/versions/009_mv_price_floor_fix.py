"""mv_price_floor_fix

Fix mv_latest_price to always pick the floor (cheapest) price within a
scrape, and mv_market_price to exclude out-of-stock Cardrush listings.

Root cause: Cardrush scrapes multiple price tiers per condition in a single
run (e.g. condition A at ¥2 080 with 19 in stock AND ¥19 800 with 0 stock).
Because both rows share the same ``observed_at``, the previous DISTINCT ON
with no price tiebreaker picked arbitrarily — often the inflated out-of-stock
price.  ``mv_market_price`` then used that value with no ``stock_qty`` guard,
so the API returned prices far above the true market floor.

Changes
-------
* ``mv_latest_price``: add ``price_jpy ASC`` as secondary sort so DISTINCT ON
  always resolves to the cheapest row when timestamps tie.
* ``mv_market_price``: add ``AND stock_qty > 0`` to the Cardrush sub-select so
  zero-stock aspirational prices are never used as the market price.

Revision ID: 009_mv_price_floor_fix
Revises: 008_graded_price_points
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "009_mv_price_floor_fix"
down_revision: str | Sequence[str] | None = "008_graded_price_points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop dependents first (reverse dependency order).
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_market_price")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    # Recreate mv_latest_price — price_jpy ASC breaks ties within a scrape.
    op.execute("""
        CREATE MATERIALIZED VIEW mv_latest_price AS
        SELECT DISTINCT ON (card_id, source, condition)
            card_id, source, condition, price_jpy, stock_qty, observed_at
        FROM price_points
        ORDER BY card_id, source, condition, observed_at DESC, price_jpy ASC
    """)
    op.execute(
        "CREATE UNIQUE INDEX mv_latest_price_card_id_source_condition_idx "
        "ON mv_latest_price (card_id, source, condition)"
    )

    # Recreate mv_cross_source_spread (definition unchanged; depends on mv_latest_price).
    op.execute("""
        CREATE MATERIALIZED VIEW mv_cross_source_spread AS
        SELECT
            cr.card_id,
            cr.condition,
            cr.min_listing_jpy AS cardrush_floor,
            sd.median_jpy AS snkrdunk_median_7d,
            (cr.min_listing_jpy::double precision - sd.median_jpy) AS spread_jpy,
            CASE
                WHEN sd.median_jpy > 0
                THEN (cr.min_listing_jpy::double precision - sd.median_jpy) / sd.median_jpy
                ELSE NULL::double precision
            END AS spread_pct
        FROM (
            SELECT card_id, condition, MIN(price_jpy) AS min_listing_jpy
            FROM mv_latest_price
            WHERE source = 'cardrush' AND stock_qty > 0
            GROUP BY card_id, condition
        ) cr
        JOIN mv_median_7d sd USING (card_id, condition)
    """)
    op.execute(
        "CREATE UNIQUE INDEX mv_cross_source_spread_pk_ux "
        "ON mv_cross_source_spread (card_id, condition)"
    )

    # Recreate mv_market_price — stock_qty > 0 guard on the Cardrush branch.
    op.execute("""
        CREATE MATERIALIZED VIEW mv_market_price AS
        SELECT
            COALESCE(sd.card_id, cr.card_id) AS card_id,
            COALESCE(sd.median_jpy, cr.price::double precision) AS market_price_jpy,
            CASE
                WHEN sd.card_id IS NOT NULL THEN 'snkrdunk'::text
                ELSE 'cardrush'::text
            END AS source_used
        FROM (
            SELECT card_id, median_jpy
            FROM mv_median_7d
            WHERE condition = 'A'
        ) sd
        FULL OUTER JOIN (
            SELECT card_id, price_jpy AS price
            FROM mv_latest_price
            WHERE source = 'cardrush'
              AND condition = 'A'
              AND stock_qty > 0
        ) cr ON sd.card_id = cr.card_id
    """)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_market_price_card_id "
        "ON mv_market_price (card_id)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_market_price")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    # Restore old mv_latest_price (no price tiebreaker).
    op.execute("""
        CREATE MATERIALIZED VIEW mv_latest_price AS
        SELECT DISTINCT ON (card_id, source, condition)
            card_id, source, condition, price_jpy, stock_qty, observed_at
        FROM price_points
        ORDER BY card_id, source, condition, observed_at DESC
    """)
    op.execute(
        "CREATE UNIQUE INDEX mv_latest_price_card_id_source_condition_idx "
        "ON mv_latest_price (card_id, source, condition)"
    )

    op.execute("""
        CREATE MATERIALIZED VIEW mv_cross_source_spread AS
        SELECT
            cr.card_id,
            cr.condition,
            cr.min_listing_jpy AS cardrush_floor,
            sd.median_jpy AS snkrdunk_median_7d,
            (cr.min_listing_jpy::double precision - sd.median_jpy) AS spread_jpy,
            CASE
                WHEN sd.median_jpy > 0
                THEN (cr.min_listing_jpy::double precision - sd.median_jpy) / sd.median_jpy
                ELSE NULL::double precision
            END AS spread_pct
        FROM (
            SELECT card_id, condition, MIN(price_jpy) AS min_listing_jpy
            FROM mv_latest_price
            WHERE source = 'cardrush' AND stock_qty > 0
            GROUP BY card_id, condition
        ) cr
        JOIN mv_median_7d sd USING (card_id, condition)
    """)
    op.execute(
        "CREATE UNIQUE INDEX mv_cross_source_spread_pk_ux "
        "ON mv_cross_source_spread (card_id, condition)"
    )

    # Restore old mv_market_price (no stock_qty guard).
    op.execute("""
        CREATE MATERIALIZED VIEW mv_market_price AS
        SELECT
            COALESCE(sd.card_id, cr.card_id) AS card_id,
            COALESCE(sd.median_jpy, cr.price::double precision) AS market_price_jpy,
            CASE
                WHEN sd.card_id IS NOT NULL THEN 'snkrdunk'::text
                ELSE 'cardrush'::text
            END AS source_used
        FROM (
            SELECT card_id, median_jpy
            FROM mv_median_7d
            WHERE condition = 'A'
        ) sd
        FULL OUTER JOIN (
            SELECT card_id, price_jpy AS price
            FROM mv_latest_price
            WHERE source = 'cardrush' AND condition = 'A'
        ) cr ON sd.card_id = cr.card_id
    """)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_market_price_card_id "
        "ON mv_market_price (card_id)"
    )
