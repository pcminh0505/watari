"""condition_short_codes

Shorten the ``condition_enum`` values from ``RAW_A``/``RAW_A_MINUS``/``RAW_B``/
``RAW_C`` to the Cardrush-style ``A``/``A-``/``B``/``C``.

Because Postgres enum types don't support renaming *values* cleanly (and the
materialized views depend on this column), the migration:

1. Drops the three materialized views.
2. Creates ``condition_enum_new`` with the short codes.
3. Alters ``price_points.condition`` to the new type with a CASE expression.
4. Drops the old type and renames the new one back to ``condition_enum``.
5. Recreates the materialized views (identical DDL to revision 003).

Revision ID: 004_condition_short_codes
Revises: 003_catalog_v2
Create Date: 2026-04-21 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "004_condition_short_codes"
down_revision: str | Sequence[str] | None = "003_catalog_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_TO_NEW_SQL = """
    CASE condition::text
        WHEN 'RAW_A'       THEN 'A'
        WHEN 'RAW_A_MINUS' THEN 'A-'
        WHEN 'RAW_B'       THEN 'B'
        WHEN 'RAW_C'       THEN 'C'
    END
"""

NEW_TO_OLD_SQL = """
    CASE condition::text
        WHEN 'A'  THEN 'RAW_A'
        WHEN 'A-' THEN 'RAW_A_MINUS'
        WHEN 'B'  THEN 'RAW_B'
        WHEN 'C'  THEN 'RAW_C'
    END
"""

MV_LATEST_PRICE = """
    CREATE MATERIALIZED VIEW mv_latest_price AS
    SELECT DISTINCT ON (card_id, source, condition)
        card_id, source, condition, price_jpy, stock_qty, observed_at
    FROM price_points
    ORDER BY card_id, source, condition, observed_at DESC
"""

MV_MEDIAN_7D = """
    CREATE MATERIALIZED VIEW mv_median_7d AS
    SELECT card_id, condition,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY price_jpy) AS median_jpy,
           COUNT(*) AS sample_size
    FROM price_points
    WHERE source = 'snkrdunk' AND source_type = 'sold'
      AND observed_at > now() - interval '7 days'
    GROUP BY card_id, condition
"""

MV_CROSS_SOURCE_SPREAD = """
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
"""


def _rebuild_materialized_views() -> None:
    op.execute(MV_LATEST_PRICE)
    op.execute("CREATE UNIQUE INDEX ON mv_latest_price(card_id, source, condition)")
    op.execute(MV_MEDIAN_7D)
    op.execute("CREATE UNIQUE INDEX ON mv_median_7d(card_id, condition)")
    op.execute(MV_CROSS_SOURCE_SPREAD)


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    op.execute("CREATE TYPE condition_enum_new AS ENUM ('A', 'A-', 'B', 'C')")
    op.execute(
        "ALTER TABLE price_points "
        "ALTER COLUMN condition TYPE condition_enum_new "
        f"USING ({OLD_TO_NEW_SQL})::condition_enum_new"
    )
    op.execute("DROP TYPE condition_enum")
    op.execute("ALTER TYPE condition_enum_new RENAME TO condition_enum")

    _rebuild_materialized_views()


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    op.execute(
        "CREATE TYPE condition_enum_old AS ENUM "
        "('RAW_A', 'RAW_A_MINUS', 'RAW_B', 'RAW_C')"
    )
    op.execute(
        "ALTER TABLE price_points "
        "ALTER COLUMN condition TYPE condition_enum_old "
        f"USING ({NEW_TO_OLD_SQL})::condition_enum_old"
    )
    op.execute("DROP TYPE condition_enum")
    op.execute("ALTER TYPE condition_enum_old RENAME TO condition_enum")

    _rebuild_materialized_views()
