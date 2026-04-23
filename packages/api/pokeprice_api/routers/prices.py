"""Price + spread endpoints.

Uses materialized views for latency:

- ``mv_latest_price``: most recent observation per (card_id, source, condition).
- ``mv_cross_source_spread``: per-condition cardrush-floor vs snkrdunk-median-7d.

The raw ``price_points`` table is only hit for the optional ``history``
endpoint, which is bounded by ``days`` and ``limit``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pokeprice_core.catalog import pad_local_id
from pokeprice_core.models import Card, PricePoint, Set
from pokeprice_core.schemas import PricePointOut
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pokeprice_api.deps import get_session
from pokeprice_api.schemas import LatestPrice, SpreadRow

router = APIRouter(
    prefix="/cards/{set_code}/{local_id}",
    tags=["prices"],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _available_variants(
    session: AsyncSession,
    *,
    lang: str,
    set_code: str,
    local_id: str,
) -> list[str]:
    stmt = (
        select(Card.variant)
        .join(Set, Set.set_code == Card.set_code)
        .where(
            Set.language == lang,
            func.upper(Card.set_code) == set_code.upper(),
            Card.local_id == local_id,
        )
        .order_by(Card.variant)
    )
    rows = (await session.execute(stmt)).all()
    return [row.variant for row in rows]


async def _resolve_card(
    session: AsyncSession,
    *,
    lang: str,
    set_code: str,
    local_id: str,
    variant: str,
) -> Card:
    normalized_local_id = pad_local_id(local_id)
    stmt = (
        select(Card)
        .join(Set, Set.set_code == Card.set_code)
        .where(
            Set.language == lang,
            func.upper(Card.set_code) == set_code.upper(),
            Card.local_id == normalized_local_id,
            Card.variant == variant,
        )
    )
    card = (await session.execute(stmt)).scalar_one_or_none()
    if card is not None:
        return card

    available = await _available_variants(
        session,
        lang=lang,
        set_code=set_code,
        local_id=normalized_local_id,
    )
    if available:
        raise HTTPException(
            status_code=400,
            detail=f"unknown variant {variant!r}; available variants: {available}",
        )
    raise HTTPException(
        status_code=404,
        detail=f"card not found: {set_code}/{normalized_local_id}",
    )


@router.get("/prices", response_model=list[LatestPrice])
async def latest_prices(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
) -> list[LatestPrice]:
    """Latest observation per (source, condition) for a card, from ``mv_latest_price``."""
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
    return [LatestPrice.model_validate(dict(r)) for r in rows]


@router.get("/history", response_model=list[PricePointOut])
async def price_history(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
    days: int = Query(30, ge=1, le=365, description="Look back this many days"),
    source: str | None = Query(None, description="Filter by source (cardrush|snkrdunk)"),
    condition: str | None = Query(None, description="Filter by condition short-code"),
    limit: int = Query(500, ge=1, le=5000),
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
    )
    if source is not None:
        stmt = stmt.where(PricePoint.source == source)
    if condition is not None:
        stmt = stmt.where(PricePoint.condition == condition)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/spread", response_model=list[SpreadRow])
async def cross_source_spread(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    variant: str = Query("normal", description="Variant slug (default: normal)"),
) -> list[SpreadRow]:
    """Cardrush-floor vs SNKRDUNK-median-7d spread per condition, from MV."""
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
    return [SpreadRow.model_validate(dict(r)) for r in rows]
