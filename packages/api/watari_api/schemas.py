"""Pydantic response models specific to the read API.

Re-exports catalog/price DTOs from ``watari_core.schemas`` where they're
already fit for purpose; adds thin wrappers for the materialized-view shapes
(``mv_latest_price``, ``mv_cross_source_spread``) which have no ORM model.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class VariantRef(BaseModel):
    """One tracked print variant for an artwork."""

    variant: str
    card_id: str
    is_tracked: bool


class ArtworkDetail(BaseModel):
    """Artwork-level response with nested print variants."""

    artwork_id: str
    set_code: str
    local_id: str
    language: str
    name_ja: str | None = None
    name_en: str | None = None
    rarity_code: str | None = None
    image_url: str | None = None
    illustrator: str | None = None
    category: str = "card"
    variants: list[VariantRef]


class ArtworkSearchResult(ArtworkDetail):
    """Artwork search result with set + floor price enrichment."""

    set_name_ja: str | None = None
    set_name_en: str | None = None
    set_release_date: date | None = None
    cardrush_a_floor_jpy: int | None = None


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
