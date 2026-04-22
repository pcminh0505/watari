"""Card/artwork-level read endpoints.

Responses are denormalized via :class:`pokeprice_core.schemas.CardWithArtwork`
so clients don't have to join artwork metadata themselves.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pokeprice_core.models import Artwork, Card, Set
from pokeprice_core.schemas import CardWithArtwork
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pokeprice_api.deps import get_session
from pokeprice_api.ratelimit import rate_limit_dep

router = APIRouter(tags=["cards"], dependencies=[Depends(rate_limit_dep)])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _card_with_artwork_columns() -> tuple[Any, ...]:
    """Projection used by every endpoint that returns ``CardWithArtwork``."""
    return (
        Card.card_id,
        Card.artwork_id,
        Card.set_code,
        Card.local_id,
        Card.variant,
        Card.is_tracked,
        Card.source_refs,
        Card.created_at,
        Card.updated_at,
        Artwork.name_ja,
        Artwork.name_en,
        Artwork.rarity_code,
        Artwork.image_url,
        Artwork.illustrator,
        Artwork.category,
    )


def _row_to_card_with_artwork(row: Any) -> CardWithArtwork:
    return CardWithArtwork.model_validate(row._mapping)


@router.get("/sets/{set_code}/cards", response_model=list[CardWithArtwork])
async def list_cards_for_set(
    set_code: str,
    session: SessionDep,
    variant: str | None = Query(None, description="Filter by variant slug"),
    rarity: str | None = Query(None, description="Filter by rarity_code (e.g. 'SAR')"),
    tracked_only: bool = Query(True, description="Only return is_tracked=True prints"),
) -> list[CardWithArtwork]:
    """List every print in a set, denormalized with artwork metadata.

    Matches ``set_code`` case-insensitively. Returned ordered by ``local_id``
    then ``variant`` for a stable shape.
    """
    # Validate the set exists to give a clean 404 instead of an empty list.
    exists_stmt = select(Set.set_code).where(func.upper(Set.set_code) == set_code.upper())
    exists = (await session.execute(exists_stmt)).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")

    stmt = (
        select(*_card_with_artwork_columns())
        .join(Artwork, Card.artwork_id == Artwork.artwork_id)
        .where(func.upper(Card.set_code) == set_code.upper())
        .order_by(Card.local_id, Card.variant)
    )
    if variant is not None:
        stmt = stmt.where(Card.variant == variant)
    if rarity is not None:
        stmt = stmt.where(Artwork.rarity_code == rarity)
    if tracked_only:
        stmt = stmt.where(Card.is_tracked.is_(True))

    result = await session.execute(stmt)
    return [_row_to_card_with_artwork(row) for row in result.all()]


@router.get("/cards/{card_id}", response_model=CardWithArtwork)
async def get_card(
    card_id: str,
    session: SessionDep,
) -> CardWithArtwork:
    """Fetch a single print (card_id) with its artwork metadata inlined."""
    stmt = (
        select(*_card_with_artwork_columns())
        .join(Artwork, Card.artwork_id == Artwork.artwork_id)
        .where(Card.card_id == card_id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"card not found: {card_id!r}")
    return _row_to_card_with_artwork(row)
