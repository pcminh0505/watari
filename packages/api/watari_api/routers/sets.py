"""Set-level read endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from watari_core.models import Card, Set
from watari_core.schemas import SetOut
from sqlalchemy import Integer, String, column, desc, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from watari_api.deps import get_session

router = APIRouter(prefix="/sets", tags=["sets"])

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


async def _set_values_map(
    session: AsyncSession,
    *,
    lang: str,
    era: str | None = None,
    set_code: str | None = None,
) -> dict[str, int]:
    stmt = (
        select(Card.set_code, func.sum(mv_latest_price.c.price_jpy))
        .select_from(Card)
        .join(Set, Set.set_code == Card.set_code)
        .join(mv_latest_price, mv_latest_price.c.card_id == Card.card_id)
        .where(
            Set.language == lang,
            Card.variant == "normal",
            Card.is_tracked.is_(True),
            mv_latest_price.c.source.cast(String) == "cardrush",
            mv_latest_price.c.condition.cast(String) == "A",
            mv_latest_price.c.stock_qty > 0,
        )
        .group_by(Card.set_code)
    )
    if era is not None:
        stmt = stmt.where(Set.era_block == era)
    if set_code is not None:
        stmt = stmt.where(func.upper(Card.set_code) == set_code.upper())

    rows = (await session.execute(stmt)).all()
    out: dict[str, int] = {}
    for row in rows:
        mapping = getattr(row, "_mapping", None)
        if mapping is not None:
            out[str(mapping["set_code"])] = int(mapping["sum"] or 0)
        else:
            out[str(row[0])] = int(row[1] or 0)
    return out


def _sort_sets(
    rows: list[SetOut],
    sort: Literal["release_date", "value", "set_code"],
    order: Literal["asc", "desc"],
) -> list[SetOut]:
    if sort == "set_code":
        reverse = order == "desc"
        return sorted(rows, key=lambda r: r.set_code, reverse=reverse)
    if sort == "value":
        with_value = [r for r in rows if r.total_value_jpy is not None]
        without_value = [r for r in rows if r.total_value_jpy is None]
        with_value.sort(
            key=lambda r: (r.total_value_jpy or 0, r.set_code), reverse=(order == "desc")
        )
        return with_value + without_value

    with_date = [r for r in rows if r.release_date is not None]
    without_date = [r for r in rows if r.release_date is None]
    with_date.sort(
        key=lambda r: (r.release_date or date.min, r.set_code), reverse=(order == "desc")
    )
    return with_date + without_date


@router.get("", response_model=list[SetOut])
async def list_sets(
    lang: str,
    session: SessionDep,
    response: Response,
    era: str | None = Query(None, description="Filter by era_block (e.g. 'sv', 'me', 'sm', 'sw')"),
    sort: Literal["release_date", "value", "set_code"] = Query(
        "release_date", description="Sort key: release_date, value, set_code"
    ),
    order: Literal["asc", "desc"] = Query("desc", description="Sort order"),
    limit: int = Query(100, ge=1, le=500, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> list[SetOut]:
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

    stmt = base.order_by(desc(Set.release_date).nulls_last(), Set.set_code)
    result = await session.execute(stmt)
    sets = list(result.scalars().all())
    values = await _set_values_map(session, lang=lang, era=era)
    enriched = [
        SetOut.model_validate(
            {
                **obj.__dict__,
                "total_value_jpy": values.get(obj.set_code),
            }
        )
        for obj in sets
    ]
    sorted_rows = _sort_sets(enriched, sort=sort, order=order)
    return sorted_rows[offset : offset + limit]


@router.get("/{set_code}", response_model=SetOut)
async def get_set(
    lang: str,
    set_code: str,
    session: SessionDep,
    response: Response,
) -> SetOut:
    """Fetch a single set by ``set_code`` (case-insensitive)."""
    stmt = select(Set).where(
        Set.language == lang,
        func.upper(Set.set_code) == set_code.upper(),
    )
    result = await session.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")
    value_map = await _set_values_map(session, lang=lang, set_code=obj.set_code)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return SetOut.model_validate(
        {
            **obj.__dict__,
            "total_value_jpy": value_map.get(obj.set_code),
        }
    )
