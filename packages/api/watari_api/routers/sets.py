"""Set-level read endpoints — served from in-memory catalog (online mode)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.schemas import SetOut

from watari_api.catalog_mem import MemCatalog, MemSet
from watari_api.deps import SessionDep, get_catalog

router = APIRouter(prefix="/sets", tags=["sets"])

CatalogDep = Annotated[MemCatalog, Depends(get_catalog)]


async def _fetch_set_totals(session: AsyncSession) -> dict[str, int]:
    """Return {SET_CODE_UPPER: total_value_jpy} from mv_market_price (normal variants)."""
    result = await session.execute(
        text(
            "SELECT UPPER(split_part(card_id, '-', 2)) AS set_code, "
            "SUM(market_price_jpy)::bigint AS total_value "
            "FROM mv_market_price "
            "WHERE card_id LIKE '%-normal' "
            "GROUP BY 1"
        )
    )
    return {row["set_code"]: int(row["total_value"]) for row in result.mappings()}

# Catalog data changes only on explicit operator reseed / process restart.
_CATALOG_CACHE = "public, max-age=3600, stale-while-revalidate=300"


def _mem_set_to_out(s: MemSet, *, total_value_jpy: int | None = None) -> SetOut:
    return SetOut.model_validate(
        {
            "set_code": s.set_code,
            "era_block": s.era_block,
            "language": s.language,
            "name_ja": s.name_ja,
            "name_en": s.name_en,
            "release_date": s.release_date,
            "total": s.total,
            "total_value_jpy": total_value_jpy,
            "parent_set_code": s.parent_set_code,
            "tcgdex_id": s.tcgdex_id,
            "source_refs": s.source_refs,
            "created_at": s.loaded_at,
            "updated_at": s.loaded_at,
        }
    )


def _sort_sets(
    rows: list[SetOut],
    sort: Literal["release_date", "value", "set_code"],
    order: Literal["asc", "desc"],
) -> list[SetOut]:
    if sort == "set_code":
        return sorted(rows, key=lambda r: r.set_code, reverse=(order == "desc"))
    if sort == "value":
        # total_value_jpy is always None in online mode — all sets sort equal.
        return sorted(rows, key=lambda r: (r.total_value_jpy or 0, r.set_code), reverse=(order == "desc"))
    # release_date (default)
    with_date = [r for r in rows if r.release_date is not None]
    without_date = [r for r in rows if r.release_date is None]
    with_date.sort(
        key=lambda r: (r.release_date or date.min, r.set_code), reverse=(order == "desc")
    )
    return with_date + without_date


@router.get("", response_model=list[SetOut])
async def list_sets(
    lang: str,
    catalog: CatalogDep,
    session: SessionDep,
    response: Response,
    era: str | None = Query(None, description="Filter by era_block (e.g. 'sv', 'me', 'sm', 'sw')"),
    sort: Literal["release_date", "value", "set_code"] = Query("release_date"),
    order: Literal["asc", "desc"] = Query("desc"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[SetOut]:
    """List sets, optionally filtered by ``era_block``."""
    mem_sets = catalog.get_sets(language=lang, era=era)
    set_totals = await _fetch_set_totals(session)
    rows = [_mem_set_to_out(s, total_value_jpy=set_totals.get(s.set_code.upper())) for s in mem_sets]
    sorted_rows = _sort_sets(rows, sort, order)
    response.headers["X-Total-Count"] = str(len(sorted_rows))
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return sorted_rows[offset : offset + limit]


@router.get("/{set_code}", response_model=SetOut)
async def get_set(
    lang: str,
    set_code: str,
    catalog: CatalogDep,
    response: Response,
) -> Any:
    """Fetch a single set by ``set_code`` (case-insensitive)."""
    s = catalog.get_set(set_code, language=lang)
    if s is None:
        raise HTTPException(status_code=404, detail=f"set not found: {set_code!r}")
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return _mem_set_to_out(s)
