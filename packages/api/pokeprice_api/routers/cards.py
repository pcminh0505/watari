"""Artwork-oriented card endpoints keyed by set + local_id."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pokeprice_core.catalog import pad_local_id
from pokeprice_core.models import Artwork, Card, Set
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pokeprice_api.deps import get_session
from pokeprice_api.schemas import ArtworkDetail, VariantRef

router = APIRouter(tags=["cards"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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


@router.get("/sets/{set_code}/cards", response_model=list[ArtworkDetail])
async def list_cards_for_set(
    lang: str,
    set_code: str,
    session: SessionDep,
    variant: str | None = Query(None, description="Filter by variant slug"),
    rarity: str | None = Query(None, description="Filter by rarity_code (e.g. 'SAR')"),
    tracked_only: bool = Query(True, description="Only return is_tracked=True prints"),
) -> list[ArtworkDetail]:
    """List artworks in a set with nested variant refs.

    Matches ``set_code`` case-insensitively. Returned ordered by ``local_id``
    for a stable shape.
    """
    # Validate the set exists to give a clean 404 instead of an empty list.
    exists_stmt = select(Set.set_code).where(
        Set.language == lang,
        func.upper(Set.set_code) == set_code.upper(),
    )
    exists = (await session.execute(exists_stmt)).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")

    stmt = (
        select(*_artwork_columns())
        .join(Card, Card.artwork_id == Artwork.artwork_id)
        .join(Set, Set.set_code == Artwork.set_code)
        .where(
            Set.language == lang,
            func.upper(Artwork.set_code) == set_code.upper(),
        )
        .order_by(Artwork.local_id)
    )
    if variant is not None:
        stmt = stmt.where(Card.variant == variant)
    if rarity is not None:
        stmt = stmt.where(Artwork.rarity_code == rarity)
    if tracked_only:
        stmt = stmt.where(Card.is_tracked.is_(True))

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
    return _row_to_artwork_detail(row, variants)
