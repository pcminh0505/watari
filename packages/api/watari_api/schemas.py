"""Pydantic response models specific to the read API.

Re-exports catalog/price DTOs from ``watari_core.schemas`` where they're
already fit for purpose; adds thin wrappers for the materialized-view shapes
(``mv_latest_price``, ``mv_cross_source_spread``, ``mv_market_price``) and
the admin scrape-health endpoint, which have no ORM model.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, model_validator


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


class CardBatchRequest(BaseModel):
    """Request body for ``POST /cards/batch``.

    ``codes`` accepts either a JSON array or a comma-separated string so
    spreadsheet clients can use whichever is easier to construct.
    """

    codes: list[str]

    @model_validator(mode="before")
    @classmethod
    def _coerce_codes(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("codes"), str):
            data = dict(data)
            data["codes"] = [data["codes"]]
        return data


class SetsBatchRequest(BaseModel):
    """Request body for ``POST /cards/by-sets``."""

    codes: list[str]


class CardBatchItem(BaseModel):
    """One result entry from ``GET /cards/batch``.

    ``error`` is ``None`` when the card was found unambiguously.
    ``"not_found"`` means no artwork matched the input in this language.
    ``"missing_set_code"`` means the token had no set code prefix; each token
    must be in ``set_code local_id`` form (e.g. ``sv3a 066/062``).
    ``"parse_error"`` means the token could not be parsed at all (e.g. empty
    local_id after stripping the denominator).

    ``candidates`` is reserved for future disambiguation support (see
    ``plans/batch-card-set-disambiguation.md``) and is always empty today.

    ``market_price_jpy`` / ``market_price_source_used`` / ``market_price_variant``
    are populated only for found cards that have price data in ``mv_market_price``.
    ``market_price_variant`` is the print variant that was priced (``"normal"``
    when available, otherwise the first tracked variant alphabetically).
    """

    input: str
    card: ArtworkDetail | None = None
    candidates: list[ArtworkDetail] = []
    error: str | None = None
    market_price_jpy: int | None = None
    market_price_source_used: str | None = None
    market_price_variant: str | None = None


class ArtworkSearchResult(ArtworkDetail):
    """Artwork search result with set + floor price enrichment."""

    set_name_ja: str | None = None
    set_name_en: str | None = None
    set_release_date: date | None = None
    cardrush_a_floor_jpy: int | None = None
    market_price_jpy: int | None = None
    market_price_source_used: str | None = None


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


class MarketPriceOut(BaseModel):
    """One row of ``mv_market_price``: unified best-price per card (condition='A').

    Prefers the SNKRDUNK 7-day median; falls back to the Cardrush floor.
    ``source_used`` is ``'snkrdunk'`` or ``'cardrush'`` so callers know
    which signal was used.
    """

    card_id: str
    market_price_jpy: int
    source_used: str


# --- Graded (slab) price shapes ------------------------------------------


class GradedPricePointOut(BaseModel):
    """One row from ``graded_price_points``, as returned by ``/graded-history``."""

    id: int
    card_id: str
    source: str
    source_type: str
    grade_company: str
    grade_score: float
    price_jpy: int
    observed_at: datetime
    external_url: str | None = None

    model_config = {"from_attributes": True}


class LatestGradedPrice(BaseModel):
    """Most recent listing per (grade_company, grade_score, source), as returned by
    ``/graded-prices``."""

    grade_company: str
    grade_score: float
    source: str
    price_jpy: int
    observed_at: datetime


# --- International / western market prices --------------------------------


class InternationalPrice(BaseModel):
    """One western-market price row from TCGPlayer, Cardmarket, or PriceCharting."""

    card_id: str
    market: str           # "tcgplayer" | "cardmarket" | "pricecharting"
    condition_label: str  # "Market" | "Mid" | "Low" | "Avg Sell" | "Trend" | "Ungraded" | "PSA 10" …
    price_jpy: int        # converted at fetch time using Frankfurter rates
    price_raw: float      # original value in source currency
    currency: str         # "USD" | "EUR"
    observed_at: datetime
    external_url: str | None = None


# --- Admin / scrape-health shapes ----------------------------------------


class ScrapeRunSummary(BaseModel):
    """Summary of the latest scrape run for one (set, source) pair."""

    started_at: datetime | None = None
    status: str | None = None
    rows_written: int = 0
    cards_failed: int = 0


class ScrapeHealthRow(BaseModel):
    """Per-set scrape health row returned by ``GET /admin/scrape-health``."""

    set_code: str
    era_block: str
    cardrush: ScrapeRunSummary
    snkrdunk: ScrapeRunSummary
    warning: str | None = None  # 'zero_rows' | 'consecutive_failures' | 'stale_7d'
