"""artworks_split

Split the ``cards`` table into:

- ``artworks`` — one row per ``(set_code, local_id)``, owns image / name /
  rarity / illustrator.
- ``cards`` — one row per print ``(set_code, local_id, variant)`` with an
  ``artwork_id`` foreign key. Keeps ``card_id`` as primary key so
  ``price_points`` / ``card_scrape_state`` references don't change shape.

This is a destructive migration (catalog data is rebuilt from the committed
YML tree via ``seed-cards``).

Revision ID: 005_artworks_split
Revises: 004_condition_short_codes
Create Date: 2026-04-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_artworks_split"
down_revision: str | Sequence[str] | None = "004_condition_short_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    # 1. Drop the materialized views that read price_points (they'll be rebuilt).
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    # 2. Wipe downstream data so we can drop/replace cards cleanly.
    # CASCADE covers the price_points → scrape_runs FK that would otherwise
    # block truncating scrape_runs.
    op.execute(
        "TRUNCATE price_points, card_scrape_state, scrape_runs "
        "RESTART IDENTITY CASCADE"
    )

    # 3. Drop the FKs referencing cards, then drop cards itself.
    op.drop_constraint(
        "price_points_card_id_fkey", "price_points", type_="foreignkey"
    )
    op.drop_constraint(
        "card_scrape_state_card_id_fkey", "card_scrape_state", type_="foreignkey"
    )
    op.drop_table("cards")

    # 4. Create artworks.
    op.create_table(
        "artworks",
        sa.Column("artwork_id", sa.Text(), nullable=False),
        sa.Column("set_code", sa.Text(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column("name_ja", sa.Text(), nullable=True),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("rarity_code", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "category", sa.Text(), nullable=False, server_default=sa.text("'card'")
        ),
        sa.Column("illustrator", sa.Text(), nullable=True),
        sa.Column(
            "source_refs",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("artwork_id"),
        sa.ForeignKeyConstraint(["set_code"], ["sets.set_code"]),
    )
    op.create_index(
        "uq_artworks_set_local", "artworks", ["set_code", "local_id"], unique=True
    )
    op.create_index("idx_artworks_set_code", "artworks", ["set_code"])
    op.create_index("idx_artworks_rarity_code", "artworks", ["rarity_code"])

    # 5. Create the new cards (print level).
    op.create_table(
        "cards",
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("artwork_id", sa.Text(), nullable=False),
        sa.Column("set_code", sa.Text(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column(
            "variant", sa.Text(), nullable=False, server_default=sa.text("'normal'")
        ),
        sa.Column(
            "is_tracked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "source_refs",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("card_id"),
        sa.ForeignKeyConstraint(["artwork_id"], ["artworks.artwork_id"]),
        sa.ForeignKeyConstraint(["set_code"], ["sets.set_code"]),
    )
    op.create_index(
        "uq_cards_set_local_variant",
        "cards",
        ["set_code", "local_id", "variant"],
        unique=True,
    )
    op.create_index("idx_cards_artwork_id", "cards", ["artwork_id"])
    op.create_index("idx_cards_set_code", "cards", ["set_code"])
    op.create_index(
        "idx_cards_is_tracked",
        "cards",
        ["is_tracked"],
        postgresql_where=sa.text("is_tracked = true"),
    )

    # 6. Re-add FKs from price_points / card_scrape_state.
    op.create_foreign_key(
        "price_points_card_id_fkey",
        "price_points",
        "cards",
        ["card_id"],
        ["card_id"],
    )
    op.create_foreign_key(
        "card_scrape_state_card_id_fkey",
        "card_scrape_state",
        "cards",
        ["card_id"],
        ["card_id"],
    )

    # 7. Rebuild the materialized views.
    _rebuild_materialized_views()


def downgrade() -> None:
    """Best-effort restore of the v2 `cards` shape (no data preservation)."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    op.execute(
        "TRUNCATE price_points, card_scrape_state, scrape_runs "
        "RESTART IDENTITY CASCADE"
    )

    op.drop_constraint(
        "price_points_card_id_fkey", "price_points", type_="foreignkey"
    )
    op.drop_constraint(
        "card_scrape_state_card_id_fkey", "card_scrape_state", type_="foreignkey"
    )
    op.drop_table("cards")
    op.drop_table("artworks")

    op.create_table(
        "cards",
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("set_code", sa.Text(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column(
            "variant", sa.Text(), nullable=False, server_default=sa.text("'normal'")
        ),
        sa.Column("rarity_code", sa.Text(), nullable=True),
        sa.Column("name_ja", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "category", sa.Text(), nullable=False, server_default=sa.text("'card'")
        ),
        sa.Column(
            "is_tracked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "source_refs",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("card_id"),
        sa.ForeignKeyConstraint(["set_code"], ["sets.set_code"]),
    )
    op.create_index(
        "uq_cards_set_local_variant",
        "cards",
        ["set_code", "local_id", "variant"],
        unique=True,
    )
    op.create_index("idx_cards_set_code", "cards", ["set_code"])
    op.create_index("idx_cards_rarity_code", "cards", ["rarity_code"])
    op.create_index(
        "idx_cards_is_tracked",
        "cards",
        ["is_tracked"],
        postgresql_where=sa.text("is_tracked = true"),
    )

    op.create_foreign_key(
        "price_points_card_id_fkey",
        "price_points",
        "cards",
        ["card_id"],
        ["card_id"],
    )
    op.create_foreign_key(
        "card_scrape_state_card_id_fkey",
        "card_scrape_state",
        "cards",
        ["card_id"],
        ["card_id"],
    )

    _rebuild_materialized_views()
