"""Set-level read endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pokeprice_core.models import Set
from pokeprice_core.schemas import SetOut
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pokeprice_api.deps import get_session

router = APIRouter(prefix="/sets", tags=["sets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[SetOut])
async def list_sets(
    lang: str,
    session: SessionDep,
    era: str | None = Query(None, description="Filter by era_block (e.g. 'sv', 'me')"),
) -> list[Set]:
    """List all sets, optionally filtered by ``era_block``.

    Ordered by ``release_date`` desc, NULL-last, then ``set_code`` for stability.
    """
    stmt = select(Set).where(Set.language == lang)
    if era is not None:
        stmt = stmt.where(Set.era_block == era)
    stmt = stmt.order_by(Set.release_date.desc().nulls_last(), Set.set_code)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{set_code}", response_model=SetOut)
async def get_set(
    lang: str,
    set_code: str,
    session: SessionDep,
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
    return obj
