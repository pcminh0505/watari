"""graded_price_points table

Adds a separate table for graded (PSA/BGS/CGC) card price data so the four
existing materialized views on ``price_points`` are not affected.

Revision ID: 008_graded_price_points
Revises: 007_mv_market_price
Create Date: 2026-05-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "008_graded_price_points"
down_revision: str | Sequence[str] | None = "007_mv_market_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_TABLE = """
CREATE TABLE graded_price_points (
    id            BIGSERIAL PRIMARY KEY,
    card_id       TEXT NOT NULL REFERENCES cards(card_id),
    source        TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    grade_company TEXT NOT NULL,
    grade_score   NUMERIC(3,1) NOT NULL,
    price_jpy     INTEGER NOT NULL,
    stock_qty     INTEGER,
    observed_at   TIMESTAMPTZ NOT NULL,
    external_url  TEXT,
    scrape_run_id BIGINT REFERENCES scrape_runs(id),
    created_at    TIMESTAMPTZ DEFAULT now()
)
"""

_CREATE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_graded_price_points_idem
ON graded_price_points (
    card_id, source, grade_company, grade_score, price_jpy, observed_at,
    COALESCE(external_url, '')
)
"""

_CREATE_LOOKUP_INDEX = """
CREATE INDEX idx_graded_price_points_card_grade_time
ON graded_price_points (card_id, grade_company, grade_score, observed_at DESC)
"""


def upgrade() -> None:
    op.execute(_CREATE_TABLE)
    op.execute(_CREATE_UNIQUE_INDEX)
    op.execute(_CREATE_LOOKUP_INDEX)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS graded_price_points")
