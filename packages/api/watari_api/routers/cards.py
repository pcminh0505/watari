"""Artwork-oriented card endpoints keyed by set + local_id."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import Integer, String, and_, column, func, or_, select, table
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.catalog import pad_local_id
from watari_core.models import Artwork, Card, Set

from watari_api.deps import get_session
from watari_api.schemas import (
    ArtworkDetail,
    ArtworkSearchResult,
    CardBatchItem,
    CardBatchRequest,
    SetsBatchRequest,
    VariantRef,
)

router = APIRouter(tags=["cards"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Catalog data changes only on explicit operator reseed.
_CATALOG_CACHE = "public, max-age=3600, stale-while-revalidate=300"
mv_latest_price = table(
    "mv_latest_price",
    column("card_id"),
    column("source"),
    column("condition"),
    column("price_jpy", Integer),
    column("stock_qty", Integer),
)
mv_market_price = table(
    "mv_market_price",
    column("card_id"),
    column("market_price_jpy", Integer),
    column("source_used", String),
)


def _artwork_columns() -> tuple[Any, ...]:
    """Projection for artwork-oriented responses."""
    return (
        Artwork.artwork_id,
        Artwork.set_code,
        Artwork.local_id,
        Artwork.name_ja,
        Artwork.name_en,
        Artwork.rarity_code,
        Artwork.image_url,
        Artwork.illustrator,
        Artwork.category,
        Set.language,
    )


def _variant_sort_key(variant: str) -> tuple[int, str]:
    return (0, variant) if variant == "normal" else (1, variant)


def _row_to_artwork_detail(row: Any, variants: list[VariantRef]) -> ArtworkDetail:
    return ArtworkDetail.model_validate({**dict(row._mapping), "variants": variants})


def _parse_code_token(raw: str) -> tuple[str | None, str] | None:
    """Parse one comma-split token into ``(set_code_upper_or_None, padded_local_id)``.

    Accepts:
    - ``"sv3a 066/062"``  → ``("SV3A", "066")``
    - ``"sv2a 170"``      → ``("SV2A", "170")``
    - ``"223/193"``        → ``(None, "223")``
    - ``"089"``            → ``(None, "089")``

    The denominator in fraction notation (``066/062``) is stripped — only the
    numerator (card number) is used.  Returns ``None`` when the token is empty
    or produces an empty local_id after stripping.
    """
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
    raw_id = raw_id.split("/")[0].strip()
    if not raw_id:
        return None
    return set_code, pad_local_id(raw_id)


def _split_code_tokens(values: list[str]) -> list[str]:
    """Normalize user-provided code values into individual non-empty tokens.

    Accept both styles:
    - ``["sv2a 089/210", "m1l 066/063"]``
    - ``["sv2a 089/210,m1l 066/063"]``
    """
    tokens: list[str] = []
    for value in values:
        tokens.extend(part.strip() for part in value.split(",") if part.strip())
    return tokens


async def _resolve_batch(
    tokens: list[str],
    lang: str,
    session: AsyncSession,
) -> list[CardBatchItem]:
    """Core batch resolution logic shared by GET and POST handlers.

    Every token must be in ``set_code local_id`` form (e.g. ``sv3a 066/062``).
    Tokens without a set code return ``error='missing_set_code'`` immediately
    with no DB query.  See ``plans/batch-card-set-disambiguation.md`` for the
    planned approach to support set-code-free lookups in the future.
    """
    if not tokens:
        return []

    parsed: list[tuple[str | None, str] | None] = [_parse_code_token(t) for t in tokens]
    results: list[CardBatchItem] = [CardBatchItem(input=t) for t in tokens]

    paired_items: list[tuple[int, str, str]] = []  # (result_idx, set_code, local_id)
    for i, p in enumerate(parsed):
        if p is None:
            results[i].error = "parse_error"
        elif p[0] is None:
            results[i].error = "missing_set_code"
        else:
            paired_items.append((i, p[0], p[1]))

    # artwork_id → raw DB row; populated by query 1 below.
    artwork_rows: dict[str, Any] = {}
    result_single: dict[int, str] = {}  # result_idx → artwork_id

    # --- Query 1: precise (set_code + local_id) lookups ---
    if paired_items:
        conditions = [
            and_(func.upper(Artwork.set_code) == sc, Artwork.local_id == lid)
            for _, sc, lid in paired_items
        ]
        stmt = (
            select(*_artwork_columns())
            .join(Set, Set.set_code == Artwork.set_code)
            .where(Set.language == lang, or_(*conditions))
        )
        rows = (await session.execute(stmt)).all()
        found_map = {(r.set_code.upper(), r.local_id): r for r in rows}
        for idx, sc, lid in paired_items:
            row = found_map.get((sc, lid))
            if row is None:
                results[idx].error = "not_found"
            else:
                artwork_rows[row.artwork_id] = row
                result_single[idx] = row.artwork_id

    if not artwork_rows:
        return results

    # --- Query 2: variants for all resolved artwork_ids ---
    variant_stmt = (
        select(Card.artwork_id, Card.variant, Card.card_id, Card.is_tracked)
        .where(Card.artwork_id.in_(list(artwork_rows)))
        .order_by(Card.artwork_id, Card.variant)
    )
    variant_rows = (await session.execute(variant_stmt)).all()
    variants_by_artwork: dict[str, list[VariantRef]] = defaultdict(list)
    for vrow in variant_rows:
        variants_by_artwork[vrow.artwork_id].append(
            VariantRef.model_validate(
                {"variant": vrow.variant, "card_id": vrow.card_id, "is_tracked": vrow.is_tracked}
            )
        )

    def _build(artwork_id: str) -> ArtworkDetail:
        row = artwork_rows[artwork_id]
        variants = sorted(
            variants_by_artwork[artwork_id], key=lambda v: _variant_sort_key(v.variant)
        )
        return _row_to_artwork_detail(row, variants)

    # --- Query 3: market price for each resolved artwork (single IN query) ---
    default_card_id_for_artwork: dict[str, tuple[str, str]] = {}
    for artwork_id in result_single.values():
        tracked = [v for v in variants_by_artwork[artwork_id] if v.is_tracked]
        if tracked:
            best = min(tracked, key=lambda v: _variant_sort_key(v.variant))
            default_card_id_for_artwork[artwork_id] = (best.card_id, best.variant)

    # Prefer Cardrush condition-A floor when present; fallback to mv_market_price.
    cardrush_floor_by_card_id: dict[str, int] = {}
    market_prices: dict[str, tuple[int, str]] = {}
    if default_card_id_for_artwork:
        card_ids = [cid for cid, _ in default_card_id_for_artwork.values()]
        floor_stmt = select(
            mv_latest_price.c.card_id,
            mv_latest_price.c.price_jpy,
        ).where(
            mv_latest_price.c.card_id.in_(card_ids),
            mv_latest_price.c.source.cast(String) == "cardrush",
            mv_latest_price.c.condition.cast(String) == "A",
            mv_latest_price.c.stock_qty > 0,
        )
        floor_rows = (await session.execute(floor_stmt)).all()
        cardrush_floor_by_card_id = {
            str(r.card_id): int(r.price_jpy) for r in floor_rows if r.price_jpy is not None
        }

        mp_stmt = select(
            mv_market_price.c.card_id,
            mv_market_price.c.market_price_jpy,
            mv_market_price.c.source_used,
        ).where(mv_market_price.c.card_id.in_(card_ids))
        mp_rows = (await session.execute(mp_stmt)).all()
        market_prices = {
            str(r.card_id): (int(r.market_price_jpy), str(r.source_used))
            for r in mp_rows
            if r.market_price_jpy is not None
        }

    for idx, artwork_id in result_single.items():
        results[idx].card = _build(artwork_id)
        if artwork_id in default_card_id_for_artwork:
            card_id, variant = default_card_id_for_artwork[artwork_id]
            results[idx].market_price_variant = variant
            floor = cardrush_floor_by_card_id.get(card_id)
            if floor is not None:
                results[idx].market_price_jpy = floor
                results[idx].market_price_source_used = "cardrush"
                continue
            price = market_prices.get(card_id)
            if price:
                results[idx].market_price_jpy = price[0]
                results[idx].market_price_source_used = price[1]

    return results


@router.get("/cards/batch", response_model=list[CardBatchItem])
async def get_cards_batch(
    lang: str,
    session: SessionDep,
    response: Response,
    codes: str = Query(
        ...,
        description=(
            "Comma-separated card codes in ``set_code local_id`` form "
            "(e.g. ``sv3a 066/062,m1l 066/063``).  Use the POST variant "
            "for large batches to avoid URL length limits."
        ),
    ),
) -> list[CardBatchItem]:
    """Resolve a comma-separated list of card codes (GET variant for small batches)."""
    tokens = _split_code_tokens([codes])
    results = await _resolve_batch(tokens, lang, session)
    if results:
        response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


@router.post("/cards/batch", response_model=list[CardBatchItem])
async def post_cards_batch(
    lang: str,
    session: SessionDep,
    response: Response,
    body: CardBatchRequest = Body(...),
) -> list[CardBatchItem]:
    """Resolve a list of card codes (POST variant — no URL length limit).

    Request body::

        {"codes": ["sv3a 066/062", "m1l 066/063", "sv2a 170/165"]}

    Each element is a single token in ``set_code local_id`` form.
    The denominator in fraction notation is stripped automatically.
    Response shape is identical to ``GET /cards/batch``.
    """
    tokens = _split_code_tokens(body.codes)
    results = await _resolve_batch(tokens, lang, session)
    if results:
        response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


async def _resolve_cards_by_sets(
    set_codes: list[str],
    lang: str,
    session: AsyncSession,
    limit: int,
    offset: int,
) -> tuple[int, list[ArtworkSearchResult]]:
    """Fetch artworks with prices for the given set codes (already uppercased)."""
    if not set_codes:
        return 0, []

    # --- Count ---
    count_stmt = (
        select(func.count(func.distinct(Artwork.artwork_id)))
        .join(Card, Card.artwork_id == Artwork.artwork_id)
        .join(Set, Set.set_code == Artwork.set_code)
        .where(
            Set.language == lang,
            func.upper(Artwork.set_code).in_(set_codes),
            Card.is_tracked.is_(True),
        )
    )
    total: int = (await session.execute(count_stmt)).scalar_one()
    if total == 0:
        return 0, []

    # --- Artworks ---
    stmt = (
        select(
            *_artwork_columns(),
            Set.name_ja.label("set_name_ja"),
            Set.name_en.label("set_name_en"),
            Set.release_date.label("set_release_date"),
        )
        .join(Card, Card.artwork_id == Artwork.artwork_id)
        .join(Set, Set.set_code == Artwork.set_code)
        .where(
            Set.language == lang,
            func.upper(Artwork.set_code).in_(set_codes),
            Card.is_tracked.is_(True),
        )
        .order_by(Set.release_date.desc().nulls_last(), Artwork.set_code, Artwork.local_id)
        .distinct()
        .limit(limit)
        .offset(offset)
    )
    artwork_rows = (await session.execute(stmt)).all()
    if not artwork_rows:
        return total, []

    artwork_ids = [row.artwork_id for row in artwork_rows]

    # --- Variants ---
    variant_stmt = (
        select(Card.artwork_id, Card.variant, Card.card_id, Card.is_tracked)
        .where(Card.artwork_id.in_(artwork_ids), Card.is_tracked.is_(True))
        .order_by(Card.artwork_id, Card.variant)
    )
    variant_rows = (await session.execute(variant_stmt)).all()
    variants_by_artwork: dict[str, list[VariantRef]] = defaultdict(list)
    for row in variant_rows:
        variants_by_artwork[row.artwork_id].append(
            VariantRef.model_validate(
                {"variant": row.variant, "card_id": row.card_id, "is_tracked": row.is_tracked}
            )
        )

    default_card_id_by_artwork: dict[str, str] = {}
    for artwork_id, variants in variants_by_artwork.items():
        if not variants:
            continue
        first_variant = min(variants, key=lambda v: _variant_sort_key(v.variant))
        default_card_id_by_artwork[artwork_id] = first_variant.card_id

    # --- Cardrush condition-A floor ---
    floor_stmt = (
        select(Card.artwork_id, mv_latest_price.c.price_jpy)
        .join(mv_latest_price, mv_latest_price.c.card_id == Card.card_id)
        .where(
            Card.artwork_id.in_(artwork_ids),
            Card.variant == "normal",
            Card.is_tracked.is_(True),
            mv_latest_price.c.source.cast(String) == "cardrush",
            mv_latest_price.c.condition.cast(String) == "A",
            mv_latest_price.c.stock_qty > 0,
        )
    )
    floor_rows = (await session.execute(floor_stmt)).all()
    floor_by_artwork = {row.artwork_id: int(row.price_jpy) for row in floor_rows}

    # --- Market prices ---
    market_by_card_id: dict[str, tuple[int, str]] = {}
    default_card_ids = list(default_card_id_by_artwork.values())
    if default_card_ids:
        market_stmt = select(
            mv_market_price.c.card_id,
            mv_market_price.c.market_price_jpy,
            mv_market_price.c.source_used,
        ).where(mv_market_price.c.card_id.in_(default_card_ids))
        market_rows = (await session.execute(market_stmt)).all()
        market_by_card_id = {
            str(row.card_id): (int(row.market_price_jpy), str(row.source_used))
            for row in market_rows
            if row.market_price_jpy is not None and row.source_used is not None
        }

    results: list[ArtworkSearchResult] = []
    for row in artwork_rows:
        variants = sorted(
            variants_by_artwork[row.artwork_id], key=lambda v: _variant_sort_key(v.variant)
        )
        default_card_id = default_card_id_by_artwork.get(row.artwork_id)
        market = market_by_card_id.get(default_card_id) if default_card_id else None
        results.append(
            ArtworkSearchResult.model_validate(
                {
                    **dict(row._mapping),
                    "variants": variants,
                    "cardrush_a_floor_jpy": floor_by_artwork.get(row.artwork_id),
                    "market_price_jpy": market[0] if market else None,
                    "market_price_source_used": market[1] if market else None,
                }
            )
        )
    return total, results


@router.get("/cards/by-sets", response_model=list[ArtworkSearchResult])
async def get_cards_by_sets(
    lang: str,
    session: SessionDep,
    response: Response,
    codes: str = Query(..., description="Comma-separated set codes (e.g. ``SV2A,M1L``)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkSearchResult]:
    """List all tracked cards with prices across one or more sets.

    ``X-Total-Count`` carries the total distinct artwork count for pagination.
    Use the POST variant for large set lists to avoid URL length limits.
    """
    set_codes = [c.strip().upper() for c in codes.split(",") if c.strip()]
    total, results = await _resolve_cards_by_sets(set_codes, lang, session, limit, offset)
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


@router.post("/cards/by-sets", response_model=list[ArtworkSearchResult])
async def post_cards_by_sets(
    lang: str,
    session: SessionDep,
    response: Response,
    body: SetsBatchRequest = Body(...),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkSearchResult]:
    """List all tracked cards with prices across one or more sets (POST variant).

    Request body::

        {"codes": ["SV2A", "M1L", "M2A"]}

    Response shape is identical to ``GET /cards/by-sets``.
    """
    set_codes = [c.strip().upper() for c in body.codes if c.strip()]
    total, results = await _resolve_cards_by_sets(set_codes, lang, session, limit, offset)
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return results


@router.get("/cards/search", response_model=list[ArtworkSearchResult])
async def search_cards(
    lang: str,
    session: SessionDep,
    response: Response,
    q: str | None = Query(None, min_length=1, max_length=80),
    set_code: str | None = Query(None, description="Filter by set code"),
    rarity: str | None = Query(None, description="Filter by rarity code"),
    illustrator: str | None = Query(None, description="Filter by illustrator name"),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArtworkSearchResult]:
    q_clean = q.strip() if q is not None else None
    if q is not None and not q_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="q must include at least one non-space character",
        )
    q_padded = pad_local_id(q_clean) if q_clean and q_clean.isdigit() else q_clean

    def _apply_filters(stmt: Any) -> Any:
        stmt = stmt.where(Set.language == lang)
        if set_code is not None:
            stmt = stmt.where(func.upper(Artwork.set_code) == set_code.upper())
        if rarity is not None:
            stmt = stmt.where(Artwork.rarity_code == rarity)
        if illustrator is not None:
            stmt = stmt.where(Artwork.illustrator == illustrator)
        if q_clean:
            stmt = stmt.where(
                or_(
                    Artwork.name_ja.ilike(f"%{q_clean}%"),
                    Artwork.name_en.ilike(f"%{q_clean}%"),
                    Artwork.local_id == q_padded,
                    func.upper(Artwork.set_code) == q_clean.upper(),
                )
            )
        return stmt

    count_stmt = _apply_filters(
        select(func.count(func.distinct(Artwork.artwork_id))).join(
            Set, Set.set_code == Artwork.set_code
        )
    )
    total: int = (await session.execute(count_stmt)).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE

    stmt = _apply_filters(
        select(
            *_artwork_columns(),
            Set.name_ja.label("set_name_ja"),
            Set.name_en.label("set_name_en"),
            Set.release_date.label("set_release_date"),
        )
        .join(Set, Set.set_code == Artwork.set_code)
        .order_by(Set.release_date.desc().nulls_last(), Artwork.set_code, Artwork.local_id)
    )
    stmt = stmt.limit(limit).offset(offset)
    artwork_rows = (await session.execute(stmt)).all()
    if not artwork_rows:
        return []

    artwork_ids = [row.artwork_id for row in artwork_rows]
    variant_stmt = (
        select(Card.artwork_id, Card.variant, Card.card_id, Card.is_tracked)
        .where(Card.artwork_id.in_(artwork_ids), Card.is_tracked.is_(True))
        .order_by(Card.artwork_id, Card.variant)
    )
    variant_rows = (await session.execute(variant_stmt)).all()
    variants_by_artwork: dict[str, list[VariantRef]] = defaultdict(list)
    for row in variant_rows:
        variants_by_artwork[row.artwork_id].append(
            VariantRef.model_validate(
                {
                    "variant": row.variant,
                    "card_id": row.card_id,
                    "is_tracked": row.is_tracked,
                }
            )
        )

    # Match the detail page default variant selection:
    # "normal" first, otherwise lexicographic variant.
    default_card_id_by_artwork: dict[str, str] = {}
    for artwork_id, variants in variants_by_artwork.items():
        if not variants:
            continue
        first_variant = min(variants, key=lambda v: _variant_sort_key(v.variant))
        default_card_id_by_artwork[artwork_id] = first_variant.card_id

    floor_stmt = (
        select(Card.artwork_id, mv_latest_price.c.price_jpy)
        .join(mv_latest_price, mv_latest_price.c.card_id == Card.card_id)
        .where(
            Card.artwork_id.in_(artwork_ids),
            Card.variant == "normal",
            Card.is_tracked.is_(True),
            mv_latest_price.c.source.cast(String) == "cardrush",
            mv_latest_price.c.condition.cast(String) == "A",
            mv_latest_price.c.stock_qty > 0,
        )
    )
    floor_rows = (await session.execute(floor_stmt)).all()
    floor_by_artwork = {row.artwork_id: int(row.price_jpy) for row in floor_rows}

    market_by_card_id: dict[str, tuple[int, str]] = {}
    default_card_ids = list(default_card_id_by_artwork.values())
    if default_card_ids:
        market_stmt = select(
            mv_market_price.c.card_id,
            mv_market_price.c.market_price_jpy,
            mv_market_price.c.source_used,
        ).where(mv_market_price.c.card_id.in_(default_card_ids))
        market_rows = (await session.execute(market_stmt)).all()
        market_by_card_id = {
            str(row.card_id): (int(row.market_price_jpy), str(row.source_used))
            for row in market_rows
            if row.market_price_jpy is not None and row.source_used is not None
        }

    results: list[ArtworkSearchResult] = []
    for row in artwork_rows:
        variants = sorted(
            variants_by_artwork[row.artwork_id], key=lambda v: _variant_sort_key(v.variant)
        )
        default_card_id = default_card_id_by_artwork.get(row.artwork_id)
        market = market_by_card_id.get(default_card_id) if default_card_id else None
        results.append(
            ArtworkSearchResult.model_validate(
                {
                    **dict(row._mapping),
                    "variants": variants,
                    "cardrush_a_floor_jpy": floor_by_artwork.get(row.artwork_id),
                    "market_price_jpy": market[0] if market else None,
                    "market_price_source_used": market[1] if market else None,
                }
            )
        )
    return results


@router.get("/cards/rarities", response_model=list[str])
async def list_rarity_codes(
    lang: str,
    session: SessionDep,
    response: Response,
    set_code: str | None = Query(None, description="Filter rarity list to one set"),
) -> list[str]:
    stmt = (
        select(Artwork.rarity_code)
        .join(Set, Set.set_code == Artwork.set_code)
        .where(Set.language == lang, Artwork.rarity_code.is_not(None))
    )
    if set_code is not None:
        stmt = stmt.where(func.upper(Artwork.set_code) == set_code.upper())
    stmt = stmt.distinct().order_by(Artwork.rarity_code)
    rows = (await session.execute(stmt)).scalars().all()
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return [code for code in rows if code is not None]


@router.get("/sets/{set_code}/cards", response_model=list[ArtworkDetail])
async def list_cards_for_set(
    lang: str,
    set_code: str,
    session: SessionDep,
    response: Response,
    variant: str | None = Query(None, description="Filter by variant slug"),
    rarity: str | None = Query(None, description="Filter by rarity_code (e.g. 'SAR')"),
    tracked_only: bool = Query(True, description="Only return is_tracked=True prints"),
    limit: int = Query(100, ge=1, le=500, description="Max artworks per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[ArtworkDetail]:
    """List artworks in a set with nested variant refs.

    Matches ``set_code`` case-insensitively.  Results are ordered by
    ``local_id``.  ``X-Total-Count`` carries the total artwork count for the
    given filters so clients can paginate.
    """
    # Validate the set exists to give a clean 404 instead of an empty list.
    exists_stmt = select(Set.set_code).where(
        Set.language == lang,
        func.upper(Set.set_code) == set_code.upper(),
    )
    exists = (await session.execute(exists_stmt)).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")

    # Base filter shared by the count query and the data query.
    def _apply_filters(stmt: Any) -> Any:
        stmt = stmt.where(
            Set.language == lang,
            func.upper(Artwork.set_code) == set_code.upper(),
        )
        if variant is not None:
            stmt = stmt.where(Card.variant == variant)
        if rarity is not None:
            stmt = stmt.where(Artwork.rarity_code == rarity)
        if tracked_only:
            stmt = stmt.where(Card.is_tracked.is_(True))
        return stmt

    count_stmt = _apply_filters(
        select(func.count(func.distinct(Artwork.artwork_id)))
        .join(Card, Card.artwork_id == Artwork.artwork_id)
        .join(Set, Set.set_code == Artwork.set_code)
    )
    total: int = (await session.execute(count_stmt)).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE

    stmt = _apply_filters(
        select(*_artwork_columns())
        .join(Card, Card.artwork_id == Artwork.artwork_id)
        .join(Set, Set.set_code == Artwork.set_code)
        .order_by(Artwork.local_id)
        .distinct()
    )
    stmt = stmt.limit(limit).offset(offset)
    artwork_rows = (await session.execute(stmt)).all()
    if not artwork_rows:
        return []

    artwork_by_id: dict[str, Any] = {}
    for row in artwork_rows:
        artwork_by_id.setdefault(row.artwork_id, row)

    variant_stmt = (
        select(Card.artwork_id, Card.variant, Card.card_id, Card.is_tracked)
        .where(Card.artwork_id.in_(artwork_by_id.keys()))
        .order_by(Card.artwork_id, Card.variant)
    )
    if variant is not None:
        variant_stmt = variant_stmt.where(Card.variant == variant)
    if tracked_only:
        variant_stmt = variant_stmt.where(Card.is_tracked.is_(True))

    variant_rows = (await session.execute(variant_stmt)).all()
    variants_by_artwork: dict[str, list[VariantRef]] = defaultdict(list)
    for row in variant_rows:
        variants_by_artwork[row.artwork_id].append(
            VariantRef.model_validate(
                {
                    "variant": row.variant,
                    "card_id": row.card_id,
                    "is_tracked": row.is_tracked,
                }
            )
        )

    details: list[ArtworkDetail] = []
    for artwork_id, row in artwork_by_id.items():
        variants = sorted(
            variants_by_artwork[artwork_id], key=lambda v: _variant_sort_key(v.variant)
        )
        details.append(_row_to_artwork_detail(row, variants))
    details.sort(key=lambda d: d.local_id)
    return details


@router.get("/cards/{set_code}/{local_id}", response_model=ArtworkDetail)
async def get_card(
    lang: str,
    set_code: str,
    local_id: str,
    session: SessionDep,
    response: Response,
) -> ArtworkDetail:
    """Fetch an artwork by set/local ID with all variants."""
    local_id = pad_local_id(local_id)
    stmt = (
        select(*_artwork_columns())
        .join(Set, Set.set_code == Artwork.set_code)
        .where(
            Set.language == lang,
            func.upper(Artwork.set_code) == set_code.upper(),
            Artwork.local_id == local_id,
        )
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"card not found: {set_code}/{local_id}")

    variant_rows = (
        await session.execute(
            select(Card.variant, Card.card_id, Card.is_tracked)
            .where(Card.artwork_id == row.artwork_id)
            .order_by(Card.variant)
        )
    ).all()
    variants = sorted(
        [
            VariantRef.model_validate(
                {
                    "variant": v.variant,
                    "card_id": v.card_id,
                    "is_tracked": v.is_tracked,
                }
            )
            for v in variant_rows
        ],
        key=lambda v: _variant_sort_key(v.variant),
    )
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return _row_to_artwork_detail(row, variants)
