"""Price endpoints — hybrid mode.

Cardrush prices are read from the DB materialized views (fast, ~50 ms).
Snkrdunk prices are fetched on demand from :class:`~watari_api.price_proxy.PriceProxy`
(first call ~3 s; cached 30 min thereafter).

``/prices``       — CR rows from ``mv_latest_price`` + SD rows on-demand (parallel)
``/spread``       — CR floor from ``mv_cross_source_spread`` + SD 7d median on-demand
``/market-price`` — SD 7d median preferred; CR floor from ``mv_market_price`` as fallback
``/graded-prices``  — CR latest per grade from ``graded_price_points`` + SD on-demand (merged)
``/graded-history`` — CR history from ``graded_price_points`` + SD on-demand (merged, sorted)
``/history``      — always empty (no ``price_points`` query; historical data not served)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.catalog import pad_local_id
from watari_core.schemas import PricePointOut

from watari_api.catalog_mem import MemCatalog
from watari_api.deps import get_catalog, get_price_proxy, get_session
from watari_api.price_proxy import PriceProxy
from watari_api.schemas import (
    GradedPricePointOut,
    LatestGradedPrice,
    LatestPrice,
    MarketPriceOut,
    SpreadRow,
)

router = APIRouter(
    prefix="/cards/{set_code}/{local_id}",
    tags=["prices"],
)

CatalogDep = Annotated[MemCatalog, Depends(get_catalog)]
PriceProxyDep = Annotated[PriceProxy, Depends(get_price_proxy)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Cache hint for clients — matches the server-side TTL
_PRICE_CACHE = "public, max-age=1800, stale-while-revalidate=60"


def _resolve_card_id(
    catalog: MemCatalog,
    *,
    lang: str,
    set_code: str,
    local_id: str,
    variant: str,
) -> str:
    """Resolve (lang, set_code, local_id, variant) → card_id or raise HTTP 400/404."""
    artwork = catalog.get_artwork(set_code, local_id)
    if artwork is None or artwork.language != lang:
        raise HTTPException(
            status_code=404,
            detail=f"card not found: {set_code}/{pad_local_id(local_id)}",
        )
    match = next((v for v in artwork.variants if v.variant == variant), None)
    if match is None:
        available = sorted(v.variant for v in artwork.variants)
        raise HTTPException(
            status_code=400,
            detail=f"unknown variant {variant!r}; available variants: {available}",
        )
    return match.card_id


@router.get("/prices", response_model=list[LatestPrice])
async def latest_prices(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    session: SessionDep,
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """CR rows from mv_latest_price + most-recent SD sale per condition, in parallel."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)

    cr_coro = session.execute(
        text(
            "SELECT source, condition, price_jpy, stock_qty, observed_at "
            "FROM mv_latest_price WHERE card_id = :cid AND source = 'cardrush'"
        ),
        {"cid": card_id},
    )
    sd_coro = proxy.snkrdunk_latest_prices(set_code, local_id, variant, card_id)
    cr_result, sd_rows = await asyncio.gather(cr_coro, sd_coro)

    rows: list[dict[str, Any]] = [
        {**dict(r), "card_id": card_id} for r in cr_result.mappings()
    ]
    rows.extend(sd_rows)
    response.headers["Cache-Control"] = _PRICE_CACHE
    return [LatestPrice.model_validate(r) for r in rows]


@router.get("/history", response_model=list[PricePointOut])
async def price_history(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    response: Response,
    variant: str = Query("normal"),
    days: int = Query(30, ge=1, le=365),
    source: str | None = Query(None),
    condition: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> list[PricePointOut]:
    """Historical price points — always empty (price_points not served via API)."""
    # Validate the card exists so callers still get 404 on bad IDs.
    _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    response.headers["Cache-Control"] = "no-store"
    return []


@router.get("/market-price", response_model=MarketPriceOut)
async def market_price(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    session: SessionDep,
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """SD 7d median preferred; falls back to CR floor from mv_market_price."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)

    sd_median = await proxy.snkrdunk_market_price(set_code, local_id, variant, card_id)
    if sd_median is not None:
        response.headers["Cache-Control"] = _PRICE_CACHE
        return MarketPriceOut(card_id=card_id, market_price_jpy=sd_median, source_used="snkrdunk")

    result = await session.execute(
        text("SELECT market_price_jpy FROM mv_market_price WHERE card_id = :cid"),
        {"cid": card_id},
    )
    r = result.mappings().first()
    if r is not None:
        response.headers["Cache-Control"] = _PRICE_CACHE
        return MarketPriceOut(
            card_id=card_id,
            market_price_jpy=r["market_price_jpy"],
            source_used="cardrush",
        )

    raise HTTPException(status_code=404, detail="no market price data for this card")


@router.get("/graded-prices", response_model=list[LatestGradedPrice])
async def latest_graded_prices(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    session: SessionDep,
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """Latest graded price per (grade_company, grade_score) — CR from DB + SD on-demand; SD preferred."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)

    cr_coro = session.execute(
        text(
            "SELECT DISTINCT ON (grade_company, grade_score) "
            "grade_company, grade_score, price_jpy, observed_at "
            "FROM graded_price_points "
            "WHERE card_id = :cid AND source = 'cardrush' "
            "ORDER BY grade_company, grade_score, observed_at DESC"
        ),
        {"cid": card_id},
    )
    sd_coro = proxy.graded_prices(set_code, local_id, card_id)
    cr_result, sd_rows = await asyncio.gather(cr_coro, sd_coro)

    # SD overrides CR for the same (grade_company, grade_score)
    grade_map: dict[tuple[str, float], dict[str, Any]] = {}
    for r in cr_result.mappings():
        key = (r["grade_company"], float(r["grade_score"]))
        grade_map[key] = {
            "grade_company": r["grade_company"],
            "grade_score": float(r["grade_score"]),
            "source": "cardrush",
            "price_jpy": r["price_jpy"],
            "observed_at": r["observed_at"],
        }
    for row in sd_rows:
        key = (row.get("grade_company", ""), float(row.get("grade_score", 0)))
        grade_map[key] = row

    response.headers["Cache-Control"] = "no-store"
    return [LatestGradedPrice.model_validate(r) for r in grade_map.values()]


@router.get("/graded-history", response_model=list[GradedPricePointOut])
async def graded_history(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    session: SessionDep,
    response: Response,
    variant: str = Query("normal"),
    days: int = Query(365, ge=1, le=365),
    company: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=2000),
) -> Any:
    """CR graded history from DB + SD on-demand, merged newest-first."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    if company:
        cr_sql = text(
            "SELECT id, card_id, source, source_type, grade_company, grade_score, "
            "price_jpy, observed_at, external_url "
            "FROM graded_price_points "
            "WHERE card_id = :cid AND source = 'cardrush' "
            "AND observed_at >= :cutoff AND grade_company = :company "
            "ORDER BY observed_at DESC"
        )
        cr_params: dict[str, Any] = {"cid": card_id, "cutoff": cutoff, "company": company.upper()}
    else:
        cr_sql = text(
            "SELECT id, card_id, source, source_type, grade_company, grade_score, "
            "price_jpy, observed_at, external_url "
            "FROM graded_price_points "
            "WHERE card_id = :cid AND source = 'cardrush' "
            "AND observed_at >= :cutoff "
            "ORDER BY observed_at DESC"
        )
        cr_params = {"cid": card_id, "cutoff": cutoff}

    cr_coro = session.execute(cr_sql, cr_params)
    sd_coro = proxy.graded_history(set_code, local_id, card_id, days=days, company=company)
    cr_result, sd_rows = await asyncio.gather(cr_coro, sd_coro)

    all_rows: list[dict[str, Any]] = [dict(r) for r in cr_result.mappings()]
    all_rows.extend(sd_rows)
    all_rows.sort(key=lambda r: r["observed_at"], reverse=True)
    all_rows = all_rows[:limit]
    for i, r in enumerate(all_rows):
        r["id"] = i + 1

    response.headers["Cache-Control"] = "no-store"
    return [GradedPricePointOut.model_validate(r) for r in all_rows]


@router.get("/spread", response_model=list[SpreadRow])
async def cross_source_spread(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    session: SessionDep,
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """CR floor from mv_cross_source_spread + SD 7d median on-demand."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)

    cr_coro = session.execute(
        text(
            "SELECT cardrush_floor FROM mv_cross_source_spread "
            "WHERE card_id = :cid AND condition = 'A'"
        ),
        {"cid": card_id},
    )
    sd_coro = proxy.snkrdunk_market_price(set_code, local_id, variant, card_id)
    cr_result, sd_median = await asyncio.gather(cr_coro, sd_coro)

    cr_row = cr_result.mappings().first()
    cr_floor = cr_row["cardrush_floor"] if cr_row else None

    response.headers["Cache-Control"] = _PRICE_CACHE
    if cr_floor is None or sd_median is None:
        return []

    spread_jpy = float(sd_median - cr_floor)
    spread_pct = (spread_jpy / cr_floor * 100) if cr_floor else None
    return [
        SpreadRow(
            card_id=card_id,
            condition="A",
            cardrush_floor=cr_floor,
            snkrdunk_median_7d=float(sd_median),
            spread_jpy=spread_jpy,
            spread_pct=spread_pct,
        )
    ]
