"""Price + spread endpoints.

Uses materialized views for latency:

- ``mv_latest_price``: most recent observation per (card_id, source, condition).
- ``mv_cross_source_spread``: per-condition cardrush-floor vs snkrdunk-median-7d.

The raw ``price_points`` table is only hit for the optional ``history``
endpoint, which is bounded by ``days`` and ``limit``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from watari_core.catalog import pad_local_id
from watari_core.models import Card, PricePoint, Set
from watari_core.schemas import PricePointOut
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from watari_api.deps import get_session
from watari_api.schemas import LatestPrice, MarketPriceOut, SpreadRow

router = APIRouter(
    prefix="/cards/{set_code}/{local_id}",
    tags=["prices"],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# MV data refreshes only after a scrape run (a few times per day).
_PRICE_CACHE = "public, max-age=300, stale-while-revalidate=60"


def _compute_etag(data: list[Any]) -> str:
    """Deterministic ETag from a list of Pydantic models."""
    payload = json.dumps(
        [row.model_dump(mode="json") for row in data],
        sort_keys=True,
        default=str,
    )
    return f'"{hashlib.sha256(payload.encode()).hexdigest()[:24]}"'


async def _resolve_card(
    session: AsyncSession,
    *,
    lang: str,
    set_code: str,
    local_id: str,
    variant: str,
) -> Card:
    """Resolve (lang, set_code, local_id, variant) → Card in a single query.

    Fetches all prints for the artwork in one round-trip, then selects the
    requested variant in Python.  If the variant is absent but siblings exist
    the caller gets a 400 with an available-variants hint; if the artwork has
    no prints at all the caller gets a 404.
    """
    normalized = pad_local_id(local_id)
    stmt = (
        select(Card)
        .join(Set, Set.set_code == Card.set_code)
        .where(
            Set.language == lang,
            func.upper(Card.set_code) == set_code.upper(),
            Card.local_id == normalized,
        )
    )
    cards = (await session.execute(stmt)).scalars().all()

    match = next((c for c in cards if c.variant == variant), None)
    if match is not None:
        return match

    if cards:
        available = sorted(c.variant for c in cards)
        raise HTTPException(
            status_code=400,
            detail=f"unknown variant {variant!r}; available variants: {available}",
        )
    raise HTTPException(
        status_code=404,
        detail=f"card not found: {set_code}/{normalized}",
    )


@router.get("/prices", response_model=list[LatestPrice])
async def latest_prices(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    request: Request,
    response: Response,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
) -> Any:
    """Latest observation per (source, condition) for a card, from ``mv_latest_price``.

    Supports conditional GET via ``If-None-Match`` / ``ETag``.
    """
    card = await _resolve_card(
        session,
        lang=lang,
        set_code=set_code,
        local_id=local_id,
        variant=variant,
    )
    stmt = text(
        "SELECT card_id, source, condition, price_jpy, stock_qty, observed_at "
        "FROM mv_latest_price WHERE card_id = :card_id "
        "ORDER BY source, condition"
    ).bindparams(bindparam("card_id", type_=None))
    rows = (await session.execute(stmt, {"card_id": card.card_id})).mappings().all()
    data = [LatestPrice.model_validate(dict(r)) for r in rows]

    etag = _compute_etag(data)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["Cache-Control"] = _PRICE_CACHE
    response.headers["ETag"] = etag
    return data


@router.get("/history", response_model=list[PricePointOut])
async def price_history(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    response: Response,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
    days: int = Query(30, ge=1, le=365, description="Look back this many days"),
    source: str | None = Query(None, description="Filter by source (cardrush|snkrdunk)"),
    condition: str | None = Query(None, description="Filter by condition short-code"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[PricePoint]:
    """Raw price_points for a card over the last ``days`` days, newest first."""
    card = await _resolve_card(
        session,
        lang=lang,
        set_code=set_code,
        local_id=local_id,
        variant=variant,
    )
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(PricePoint)
        .where(
            PricePoint.card_id == card.card_id,
            PricePoint.observed_at >= since,
        )
        .order_by(PricePoint.observed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if source is not None:
        stmt = stmt.where(PricePoint.source == source)
    if condition is not None:
        stmt = stmt.where(PricePoint.condition == condition)
    result = await session.execute(stmt)
    # Raw time-windowed data: never cache.
    response.headers["Cache-Control"] = "no-store"
    return list(result.scalars().all())


@router.get("/market-price", response_model=MarketPriceOut)
async def market_price(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    request: Request,
    response: Response,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
) -> Any:
    """Unified best-price for a card from ``mv_market_price`` (condition='A').

    Prefers the SNKRDUNK 7-day median; falls back to Cardrush floor.
    Returns 404 when neither source has data for the card.

    Supports conditional GET via ``If-None-Match`` / ``ETag``.
    """
    card = await _resolve_card(
        session,
        lang=lang,
        set_code=set_code,
        local_id=local_id,
        variant=variant,
    )
    stmt = text(
        "SELECT card_id, market_price_jpy, source_used "
        "FROM mv_market_price WHERE card_id = :card_id"
    ).bindparams(bindparam("card_id", type_=None))
    row = (await session.execute(stmt, {"card_id": card.card_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="no market price data for this card")
    data = MarketPriceOut.model_validate(dict(row))

    etag = _compute_etag([data])
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["Cache-Control"] = _PRICE_CACHE
    response.headers["ETag"] = etag
    return data


@router.get("/spread", response_model=list[SpreadRow])
async def cross_source_spread(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    request: Request,
    response: Response,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
) -> Any:
    """Cardrush-floor vs SNKRDUNK-median-7d spread per condition, from MV.

    Supports conditional GET via ``If-None-Match`` / ``ETag``.
    """
    card = await _resolve_card(
        session,
        lang=lang,
        set_code=set_code,
        local_id=local_id,
        variant=variant,
    )
    stmt = text(
        "SELECT card_id, condition, cardrush_floor, snkrdunk_median_7d, "
        "       spread_jpy, spread_pct "
        "FROM mv_cross_source_spread WHERE card_id = :card_id "
        "ORDER BY condition"
    )
    rows = (await session.execute(stmt, {"card_id": card.card_id})).mappings().all()
    data = [SpreadRow.model_validate(dict(r)) for r in rows]

    etag = _compute_etag(data)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["Cache-Control"] = _PRICE_CACHE
    response.headers["ETag"] = etag
    return data
