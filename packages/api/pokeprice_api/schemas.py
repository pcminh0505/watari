"""Pydantic response models specific to the read API.

Re-exports catalog/price DTOs from ``pokeprice_core.schemas`` where they're
already fit for purpose; adds thin wrappers for the materialized-view shapes
(``mv_latest_price``, ``mv_cross_source_spread``) which have no ORM model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LatestPrice(BaseModel):
    """One row of ``mv_latest_price``: most recent observation per (source, condition)."""

    card_id: str
    source: str
    condition: str
    price_jpy: int
    stock_qty: int | None = None
    observed_at: datetime


class SpreadRow(BaseModel):
    """One row of ``mv_cross_source_spread`` joined for a card_id."""

    card_id: str
    condition: str
    cardrush_floor: int
    snkrdunk_median_7d: float
    spread_jpy: float
    spread_pct: float | None = None
