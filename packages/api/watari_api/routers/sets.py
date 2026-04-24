"""Set-level read endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from watari_core.models import Set
from watari_core.schemas import SetOut
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watari_api.deps import get_session

router = APIRouter(prefix="/sets", tags=["sets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Catalog data changes only on explicit operator reseed.
_CATALOG_CACHE = "public, max-age=3600, stale-while-revalidate=300"


@router.get("", response_model=list[SetOut])
async def list_sets(
    lang: str,
    session: SessionDep,
    response: Response,
    era: str | None = Query(None, description="Filter by era_block (e.g. 'sv', 'me')"),
    limit: int = Query(100, ge=1, le=500, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[Set]:
    """List sets, optionally filtered by ``era_block``.

    Ordered by ``release_date`` desc, NULL-last, then ``set_code`` for
    stability.  ``X-Total-Count`` carries the unfiltered-page total.
    """
    base = select(Set).where(Set.language == lang)
    if era is not None:
        base = base.where(Set.era_block == era)

    total: int = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = _CATALOG_CACHE

    stmt = base.order_by(Set.release_date.desc().nulls_last(), Set.set_code)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{set_code}", response_model=SetOut)
async def get_set(
    lang: str,
    set_code: str,
    session: SessionDep,
    response: Response,
) -> Set:
    """Fetch a single set by ``set_code`` (case-insensitive)."""
    stmt = select(Set).where(
        Set.language == lang,
        func.upper(Set.set_code) == set_code.upper(),
    )
    result = await session.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return obj
