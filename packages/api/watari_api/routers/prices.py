"""Price endpoints — fetch live from Cardrush and Snkrdunk (online mode).

Results are cached in :class:`~watari_api.price_proxy.PriceProxy` for
:data:`~watari_api.price_proxy.CACHE_TTL` (default 30 min) so repeated
requests for the same card are fast.

**What changes vs the DB-backed version:**

- ``/prices`` and ``/market-price``: fetched on demand; first call may take
  2–5 s (Cardrush HTML scrape + Snkrdunk JSON API).
- ``/history``: always returns an empty list — no historical DB rows.
- ``/spread``: computed from the live fetch, only condition 'A' available.
- ``/graded-prices`` / ``/graded-history``: from Snkrdunk sales history.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from watari_core.catalog import pad_local_id
from watari_core.schemas import PricePointOut

from watari_api.catalog_mem import MemCatalog
from watari_api.deps import get_catalog, get_price_proxy
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
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """Current listings per (source, condition) — fetched live, cached 30 min."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    rows = await proxy.latest_prices(set_code, local_id, variant, card_id)
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
    """Historical price points — always empty in online mode (no database)."""
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
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """Unified best-price — Snkrdunk 7d median preferred, Cardrush floor fallback."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    result = await proxy.market_price(set_code, local_id, variant, card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="no market price data for this card")
    response.headers["Cache-Control"] = _PRICE_CACHE
    return MarketPriceOut.model_validate(result)


@router.get("/graded-prices", response_model=list[LatestGradedPrice])
async def latest_graded_prices(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """Most recent graded listing per (grade_company, grade_score, source)."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    rows = await proxy.graded_prices(set_code, local_id, card_id)
    response.headers["Cache-Control"] = "no-store"
    return [LatestGradedPrice.model_validate(r) for r in rows]


@router.get("/graded-history", response_model=list[GradedPricePointOut])
async def graded_history(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    response: Response,
    variant: str = Query("normal"),
    days: int = Query(365, ge=1, le=365),
    company: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=2000),
) -> Any:
    """Raw graded price history from Snkrdunk, newest first."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    rows = await proxy.graded_history(
        set_code, local_id, card_id, days=days, company=company
    )
    response.headers["Cache-Control"] = "no-store"
    return [GradedPricePointOut.model_validate(r) for r in rows[:limit]]


@router.get("/spread", response_model=list[SpreadRow])
async def cross_source_spread(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    proxy: PriceProxyDep,
    response: Response,
    variant: str = Query("normal"),
) -> Any:
    """Cardrush floor vs Snkrdunk 7d median spread for condition 'A'."""
    card_id = _resolve_card_id(catalog, lang=lang, set_code=set_code, local_id=local_id, variant=variant)
    rows = await proxy.spread(set_code, local_id, variant, card_id)
    response.headers["Cache-Control"] = _PRICE_CACHE
    return [SpreadRow.model_validate(r) for r in rows]
