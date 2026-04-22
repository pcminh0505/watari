"""catalog_v2

Wipe-and-rebuild the catalog for the metadata layer.

- Drops the three materialized views.
- Truncates price_points, card_scrape_state, scrape_runs, cards.
- Drops and recreates ``cards`` with the new shape (set_code FK, variant, …).
- Creates new ``sets`` table.
- Re-creates the three materialized views with unchanged DDL.

Downgrade is best-effort: restores the prior ``cards`` shape, but not the data.

Revision ID: 003_catalog_v2
Revises: 41bdc53fd9e9
Create Date: 2026-04-21 20:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003_catalog_v2"
down_revision: str | Sequence[str] | None = "41bdc53fd9e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1) Drop materialized views (dependent on cards).
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    # 2) Wipe downstream data. CASCADE also clears price_points / card_scrape_state.
    op.execute(
        "TRUNCATE price_points, card_scrape_state, scrape_runs, cards "
        "RESTART IDENTITY CASCADE"
    )

    # 3) Drop dependent FKs from price_points / card_scrape_state, then drop
    #    the old cards table itself. Indexes go with it.
    op.drop_constraint(
        "price_points_card_id_fkey", "price_points", type_="foreignkey"
    )
    op.drop_constraint(
        "card_scrape_state_card_id_fkey", "card_scrape_state", type_="foreignkey"
    )
    op.drop_index(
        "idx_cards_tier_tracked",
        table_name="cards",
        postgresql_where=sa.text("is_tracked = true"),
    )
    op.drop_index("idx_cards_era", table_name="cards")
    op.drop_table("cards")

    # 4) Create new `sets` table.
    op.create_table(
        "sets",
        sa.Column("set_code", sa.Text(), nullable=False),
        sa.Column("era_block", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False, server_default="jp"),
        sa.Column("name_ja", sa.Text(), nullable=True),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("parent_set_code", sa.Text(), nullable=True),
        sa.Column("tcgdex_id", sa.Text(), nullable=True),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("set_code"),
        sa.ForeignKeyConstraint(
            ["parent_set_code"], ["sets.set_code"], name="fk_sets_parent_set_code"
        ),
    )
    op.create_index("idx_sets_era_block", "sets", ["era_block"], unique=False)
    op.create_index(
        "idx_sets_release_date",
        "sets",
        [sa.literal_column("release_date DESC")],
        unique=False,
    )

    # 5) Create new `cards` table.
    op.create_table(
        "cards",
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("set_code", sa.Text(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("rarity_code", sa.Text(), nullable=True),
        sa.Column("name_ja", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False, server_default="card"),
        sa.Column(
            "is_tracked", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("card_id"),
        sa.ForeignKeyConstraint(
            ["set_code"], ["sets.set_code"], name="fk_cards_set_code"
        ),
    )
    op.create_index(
        "uq_cards_set_local_variant",
        "cards",
        ["set_code", "local_id", "variant"],
        unique=True,
    )
    op.create_index("idx_cards_set_code", "cards", ["set_code"], unique=False)
    op.create_index(
        "idx_cards_rarity_code", "cards", ["rarity_code"], unique=False
    )
    op.create_index(
        "idx_cards_is_tracked",
        "cards",
        ["is_tracked"],
        unique=False,
        postgresql_where=sa.text("is_tracked = true"),
    )

    # 5b) Re-add FKs on dependent tables to new cards.card_id.
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

    # 6) Re-create materialized views (identical DDL to revision 41bdc53fd9e9).
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_latest_price AS
        SELECT DISTINCT ON (card_id, source, condition)
            card_id, source, condition, price_jpy, stock_qty, observed_at
        FROM price_points
        ORDER BY card_id, source, condition, observed_at DESC
        """
    )
    op.execute("CREATE UNIQUE INDEX ON mv_latest_price(card_id, source, condition)")

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_median_7d AS
        SELECT card_id, condition,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price_jpy) AS median_jpy,
               COUNT(*) AS sample_size
        FROM price_points
        WHERE source = 'snkrdunk' AND source_type = 'sold'
          AND observed_at > now() - interval '7 days'
        GROUP BY card_id, condition
        """
    )
    op.execute("CREATE UNIQUE INDEX ON mv_median_7d(card_id, condition)")

    op.execute(
        """
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
    )


def downgrade() -> None:
    """Downgrade schema (best-effort — data is not restored)."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cross_source_spread")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_median_7d")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_latest_price")

    op.execute(
        "TRUNCATE price_points, card_scrape_state, scrape_runs, cards "
        "RESTART IDENTITY CASCADE"
    )

    op.drop_index("idx_cards_is_tracked", table_name="cards")
    op.drop_index("idx_cards_rarity_code", table_name="cards")
    op.drop_index("idx_cards_set_code", table_name="cards")
    op.drop_index("uq_cards_set_local_variant", table_name="cards")
    op.drop_table("cards")

    op.drop_index("idx_sets_release_date", table_name="sets")
    op.drop_index("idx_sets_era_block", table_name="sets")
    op.drop_table("sets")

    op.create_table(
        "cards",
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("era", sa.Text(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column("total", sa.Text(), nullable=True),
        sa.Column("name_ja", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("rarity", sa.Text(), nullable=True),
        sa.Column("set_name_ja", sa.Text(), nullable=True),
        sa.Column("set_name_en", sa.Text(), nullable=True),
        sa.Column("set_release_date", sa.Date(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("tier", sa.Text(), server_default="mid", nullable=False),
        sa.Column(
            "is_tracked", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("card_id"),
    )
    op.create_index("idx_cards_era", "cards", ["era"], unique=False)
    op.create_index(
        "idx_cards_tier_tracked",
        "cards",
        ["tier", "is_tracked"],
        unique=False,
        postgresql_where=sa.text("is_tracked = true"),
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_latest_price AS
        SELECT DISTINCT ON (card_id, source, condition)
            card_id, source, condition, price_jpy, stock_qty, observed_at
        FROM price_points
        ORDER BY card_id, source, condition, observed_at DESC
        """
    )
    op.execute("CREATE UNIQUE INDEX ON mv_latest_price(card_id, source, condition)")

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_median_7d AS
        SELECT card_id, condition,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price_jpy) AS median_jpy,
               COUNT(*) AS sample_size
        FROM price_points
        WHERE source = 'snkrdunk' AND source_type = 'sold'
          AND observed_at > now() - interval '7 days'
        GROUP BY card_id, condition
        """
    )
    op.execute("CREATE UNIQUE INDEX ON mv_median_7d(card_id, condition)")

    op.execute(
        """
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
    )
