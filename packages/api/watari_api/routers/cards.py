"""Artwork-oriented card endpoints — served from in-memory catalog (hybrid mode).

``market_price_jpy`` in batch results is populated from ``mv_market_price``
(Cardrush DB, instant). Search/list results still return ``null`` — use the
``/prices`` and ``/market-price`` endpoints for per-card price details.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.catalog import pad_local_id

from watari_api.catalog_mem import MemArtwork, MemCatalog, MemVariant
from watari_api.deps import get_catalog, get_session
from watari_api.schemas import (
    ArtworkDetail,
    ArtworkSearchResult,
    CardBatchItem,
    CardBatchRequest,
    SetsBatchRequest,
    VariantRef,
)

router = APIRouter(tags=["cards"])

CatalogDep = Annotated[MemCatalog, Depends(get_catalog)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_CATALOG_CACHE = "public, max-age=3600, stale-while-revalidate=300"


def _variant_sort_key(variant: str) -> tuple[int, str]:
    return (0, variant) if variant == "normal" else (1, variant)


def _mem_variant_to_ref(v: MemVariant) -> VariantRef:
    return VariantRef(variant=v.variant, card_id=v.card_id, is_tracked=v.is_tracked)


def _mem_artwork_to_detail(a: MemArtwork) -> ArtworkDetail:
    variants = sorted(
        [_mem_variant_to_ref(v) for v in a.variants],
        key=lambda v: _variant_sort_key(v.variant),
    )
    return ArtworkDetail(
        artwork_id=a.artwork_id,
        set_code=a.set_code,
        local_id=a.local_id,
        language=a.language,
        name_ja=a.name_ja,
        name_en=a.name_en,
        rarity_code=a.rarity_code,
        image_url=a.image_url,
        illustrator=a.illustrator,
        category=a.category,
        variants=variants,
    )


def _mem_artwork_to_search_result(a: MemArtwork) -> ArtworkSearchResult:
    variants = sorted(
        [_mem_variant_to_ref(v) for v in a.variants],
        key=lambda v: _variant_sort_key(v.variant),
    )
    return ArtworkSearchResult(
        artwork_id=a.artwork_id,
        set_code=a.set_code,
        local_id=a.local_id,
        language=a.language,
        name_ja=a.name_ja,
        name_en=a.name_en,
        rarity_code=a.rarity_code,
        image_url=a.image_url,
        illustrator=a.illustrator,
        category=a.category,
        variants=variants,
        set_name_ja=a.set_name_ja,
        set_name_en=a.set_name_en,
        set_release_date=a.set_release_date,
        cardrush_a_floor_jpy=None,
        market_price_jpy=None,
        market_price_source_used=None,
    )


# --- price enrichment --------------------------------------------------------


async def _enrich_search_results_from_db(
    results: list[ArtworkSearchResult], session: AsyncSession
) -> None:
    """Populate market_price_jpy on search results via a single mv_market_price query."""
    cid_to_result: dict[str, ArtworkSearchResult] = {}
    for r in results:
        variant = "normal"
        if r.variants and not any(v.variant == "normal" for v in r.variants):
            variant = r.variants[0].variant
        card_id = next((v.card_id for v in r.variants if v.variant == variant), None)
        if card_id:
            cid_to_result[card_id] = r

    if not cid_to_result:
        return

    db_result = await session.execute(
        text(
            "SELECT card_id, market_price_jpy, source_used "
            "FROM mv_market_price WHERE card_id = ANY(:ids)"
        ),
        {"ids": list(cid_to_result.keys())},
    )
    for row in db_result.mappings():
        r = cid_to_result.get(row["card_id"])
        if r:
            r.market_price_jpy = row["market_price_jpy"]
            r.market_price_source_used = row["source_used"]


async def _enrich_batch_from_db(items: list[CardBatchItem], session: AsyncSession) -> None:
    """Fetch market_price_jpy for all found items via a single mv_market_price query."""
    cid_to_item: dict[str, CardBatchItem] = {}
    for item in items:
        if item.card is None:
            continue
        # Prefer "normal" variant; fall back to the first tracked variant.
        variant = "normal"
        if item.card.variants and not any(v.variant == "normal" for v in item.card.variants):
            variant = item.card.variants[0].variant
        card_id = next(
            (v.card_id for v in item.card.variants if v.variant == variant),
            None,
        )
        if card_id:
            cid_to_item[card_id] = item
            item.market_price_variant = variant

    if not cid_to_item:
        return

    result = await session.execute(
        text(
            "SELECT card_id, market_price_jpy, source_used "
            "FROM mv_market_price WHERE card_id = ANY(:ids)"
        ),
        {"ids": list(cid_to_item.keys())},
    )
    for row in result.mappings():
        item = cid_to_item.get(row["card_id"])
        if item:
            item.market_price_jpy = row["market_price_jpy"]
            item.market_price_source_used = row["source_used"]


# --- batch endpoint ----------------------------------------------------------

# Official promo denomination suffixes → internal set_code.
# Handles inputs like "P 020/M-P" (M-era promo) and "P 297/SM-P" (SM-era promo).
_PROMO_DENOM: dict[str, str] = {
    "M-P": "MP",
    "SM-P": "SMPR",
    "S-P": "SP",
    "SV-P": "SVP",
}


def _parse_code_token(raw: str) -> tuple[str | None, str] | None:
    token = raw.strip()
    if not token:
        return None
    parts = token.split(None, 1)
    if len(parts) == 2:
        set_code: str | None = parts[0].upper()
        raw_id = parts[1]
    else:
        set_code = None
        raw_id = parts[0]

    # Resolve promo denomination: "P 020/M-P" → set_code=MP, local_id=020
    if set_code == "P" and "/" in raw_id:
        denom = raw_id.split("/", 1)[1].strip().upper()
        if denom in _PROMO_DENOM:
            set_code = _PROMO_DENOM[denom]

    raw_id = raw_id.split("/")[0].strip()
    if not raw_id:
        return None
    return set_code, pad_local_id(raw_id)


def _split_code_tokens(values: list[str]) -> list[str]:
    tokens: list[str] = []
    for value in values:
        tokens.extend(part.strip() for part in value.split(",") if part.strip())
    return tokens


def _resolve_batch(tokens: list[str], lang: str, catalog: MemCatalog) -> list[CardBatchItem]:
    if not tokens:
        return []
    results: list[CardBatchItem] = []
    for token in tokens:
        parsed = _parse_code_token(token)
        item = CardBatchItem(input=token)
        if parsed is None:
            item.error = "parse_error"
        elif parsed[0] is None:
            item.error = "missing_set_code"
        else:
            sc, lid = parsed
            artwork = catalog.get_artwork(sc, lid)
            if artwork is None or artwork.language != lang:
                item.error = "not_found"
            else:
                item.card = _mem_artwork_to_detail(artwork)
        results.append(item)
    return results


@router.get("/cards/batch", response_model=list[CardBatchItem])
async def get_cards_batch(
    lang: str,
    catalog: CatalogDep,
    session: SessionDep,
    response: Response,
    codes: str = Query(..., description="Comma-separated card codes in ``set_code local_id`` form"),
) -> list[CardBatchItem]:
    """Resolve a comma-separated list of card codes and fetch market prices from mv_market_price."""
    tokens = _split_code_tokens([codes])
    results = _resolve_batch(tokens, lang, catalog)
    await _enrich_batch_from_db(results, session)
    if results:
        response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


@router.post("/cards/batch", response_model=list[CardBatchItem])
async def post_cards_batch(
    lang: str,
    catalog: CatalogDep,
    session: SessionDep,
    response: Response,
    body: CardBatchRequest = Body(...),
) -> list[CardBatchItem]:
    """Resolve a list of card codes and fetch market prices from mv_market_price.

    ``body.codes`` accepts a JSON array **or** a single comma-separated string,
    e.g. ``{"codes": "sv2a 204, m2a 195"}`` or ``{"codes": ["sv2a 204", "m2a 195"]}``.
    """
    tokens = _split_code_tokens(body.codes)
    results = _resolve_batch(tokens, lang, catalog)
    await _enrich_batch_from_db(results, session)
    if results:
        response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


# --- by-sets endpoint --------------------------------------------------------


def _cards_by_sets(
    set_codes: list[str],
    lang: str,
    catalog: MemCatalog,
    limit: int,
    offset: int,
) -> tuple[int, list[ArtworkSearchResult]]:
    all_artworks: list[MemArtwork] = []
    for sc in set_codes:
        for a in catalog.get_artworks(sc):
            if a.language == lang and a.variants:
                all_artworks.append(a)

    # Stable sort: newest set first, then set_code, then local_id
    from datetime import date as _date
    all_artworks.sort(
        key=lambda a: (a.set_release_date or _date.min, a.set_code, a.local_id),
        reverse=True,
    )
    total = len(all_artworks)
    page = all_artworks[offset : offset + limit]
    return total, [_mem_artwork_to_search_result(a) for a in page]


@router.get("/cards/by-sets", response_model=list[ArtworkSearchResult])
async def get_cards_by_sets(
    lang: str,
    catalog: CatalogDep,
    response: Response,
    codes: str = Query(..., description="Comma-separated set codes (e.g. ``SV2A,M1L``)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkSearchResult]:
    set_codes = [c.strip().upper() for c in codes.split(",") if c.strip()]
    total, results = _cards_by_sets(set_codes, lang, catalog, limit, offset)
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


@router.post("/cards/by-sets", response_model=list[ArtworkSearchResult])
async def post_cards_by_sets(
    lang: str,
    catalog: CatalogDep,
    response: Response,
    body: SetsBatchRequest = Body(...),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkSearchResult]:
    set_codes = [c.strip().upper() for c in body.codes if c.strip()]
    total, results = _cards_by_sets(set_codes, lang, catalog, limit, offset)
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


# --- search ------------------------------------------------------------------


@router.get("/cards/search", response_model=list[ArtworkSearchResult])
async def search_cards(
    lang: str,
    catalog: CatalogDep,
    session: SessionDep,
    response: Response,
    q: str | None = Query(None, min_length=1, max_length=80),
    set_code: str | None = Query(None),
    rarity: str | None = Query(None),
    illustrator: str | None = Query(None),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkSearchResult]:
    q_clean = q.strip() if q is not None else None
    if q is not None and not q_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="q must include at least one non-space character",
        )

    all_artworks = catalog.search_artworks(
        language=lang,
        q=q_clean,
        set_code=set_code,
        rarity=rarity,
        illustrator=illustrator,
    )
    total = len(all_artworks)
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    page = all_artworks[offset : offset + limit]
    results = [_mem_artwork_to_search_result(a) for a in page]
    await _enrich_search_results_from_db(results, session)
    return results


@router.get("/cards/rarities", response_model=list[str])
async def list_rarity_codes(
    lang: str,
    catalog: CatalogDep,
    response: Response,
    set_code: str | None = Query(None),
) -> list[str]:
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return catalog.get_rarities(language=lang, set_code=set_code)


# --- per-set cards list ------------------------------------------------------


@router.get("/sets/{set_code}/cards", response_model=list[ArtworkDetail])
async def list_cards_for_set(
    lang: str,
    set_code: str,
    catalog: CatalogDep,
    response: Response,
    variant: str | None = Query(None),
    rarity: str | None = Query(None),
    tracked_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkDetail]:
    """List artworks in a set with nested variant refs."""
    if catalog.get_set(set_code, language=lang) is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")

    artworks = catalog.get_artworks(set_code)
    artworks = [a for a in artworks if a.language == lang]

    if rarity is not None:
        artworks = [a for a in artworks if a.rarity_code == rarity]

    # Apply variant and tracked_only filters at the variant level
    details: list[ArtworkDetail] = []
    for a in artworks:
        variants = [v for v in a.variants if v.is_tracked or not tracked_only]
        if variant is not None:
            variants = [v for v in variants if v.variant == variant]
        if not variants:
            continue
        variants_sorted = sorted(
            [_mem_variant_to_ref(v) for v in variants],
            key=lambda v: _variant_sort_key(v.variant),
        )
        details.append(
            ArtworkDetail(
                artwork_id=a.artwork_id,
                set_code=a.set_code,
                local_id=a.local_id,
                language=a.language,
                name_ja=a.name_ja,
                name_en=a.name_en,
                rarity_code=a.rarity_code,
                image_url=a.image_url,
                illustrator=a.illustrator,
                category=a.category,
                variants=variants_sorted,
            )
        )

    total = len(details)
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return details[offset : offset + limit]


# --- single card -------------------------------------------------------------


@router.get("/cards/{set_code}/{local_id}", response_model=ArtworkDetail)
async def get_card(
    lang: str,
    set_code: str,
    local_id: str,
    catalog: CatalogDep,
    response: Response,
) -> Any:
    """Fetch an artwork by set/local ID with all variants."""
    artwork = catalog.get_artwork(set_code, local_id)
    if artwork is None or artwork.language != lang:
        raise HTTPException(
            status_code=404, detail=f"card not found: {set_code}/{pad_local_id(local_id)}"
        )
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return _mem_artwork_to_detail(artwork)
