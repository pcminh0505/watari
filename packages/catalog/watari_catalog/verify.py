"""Smoke/sanity checks over the catalog tables (sets + artworks + cards)."""

from __future__ import annotations

import logging
from typing import Any

from watari_core.db import async_session_factory
from watari_core.models import Artwork, Card, Set
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _set_summary(session: AsyncSession) -> list[dict[str, Any]]:
    """Aggregate per-set stats.

    Columns:
        - ``artworks_present``: one row per (set, local_id).
        - ``artworks_with_rarity``: artworks that have a rarity_code.
        - ``artworks_with_image``: artworks that have an image_url.
        - ``cards_present``: distinct prints (artwork × variant).
        - ``variants_present``: distinct variant slugs seen.
    """
    stmt = (
        select(
            Set.set_code,
            Set.era_block,
            Set.name_ja,
            Set.total,
            func.count(func.distinct(Artwork.artwork_id)).label("artworks_present"),
            func.count(func.distinct(
                case((Artwork.rarity_code.is_not(None), Artwork.artwork_id))
            )).label("artworks_with_rarity"),
            func.count(func.distinct(
                case((Artwork.image_url.is_not(None), Artwork.artwork_id))
            )).label("artworks_with_image"),
            func.count(func.distinct(
                case((Artwork.name_ja.is_not(None), Artwork.artwork_id))
            )).label("artworks_with_name_ja"),
            func.count(func.distinct(Card.card_id)).label("cards_present"),
            func.count(func.distinct(Card.variant)).label("variants_present"),
        )
        .join(Artwork, Artwork.set_code == Set.set_code, isouter=True)
        .join(Card, Card.artwork_id == Artwork.artwork_id, isouter=True)
        .group_by(Set.set_code, Set.era_block, Set.name_ja, Set.total)
        .order_by(Set.era_block, Set.set_code)
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.all()]


async def _orphan_counts(session: AsyncSession) -> dict[str, int]:
    orphan_artworks = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Artwork)
                .where(~Artwork.set_code.in_(select(Set.set_code)))
            )
        ).scalar_one()
    )
    orphan_cards = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Card)
                .where(~Card.artwork_id.in_(select(Artwork.artwork_id)))
            )
        ).scalar_one()
    )
    return {"orphan_artworks": orphan_artworks, "orphan_cards": orphan_cards}


async def _run_totals(session: AsyncSession) -> dict[str, int]:
    sets = int((await session.execute(select(func.count()).select_from(Set))).scalar_one())
    artworks = int(
        (await session.execute(select(func.count()).select_from(Artwork))).scalar_one()
    )
    cards = int(
        (await session.execute(select(func.count()).select_from(Card))).scalar_one()
    )
    artworks_no_rarity = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Artwork)
                .where(Artwork.rarity_code.is_(None))
            )
        ).scalar_one()
    )
    artworks_no_image = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Artwork)
                .where(Artwork.image_url.is_(None))
            )
        ).scalar_one()
    )
    artworks_no_name_ja = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Artwork)
                .where(Artwork.name_ja.is_(None))
            )
        ).scalar_one()
    )
    variants = int(
        (
            await session.execute(
                select(func.count(func.distinct(Card.variant))).select_from(Card)
            )
        ).scalar_one()
    )
    return {
        "sets": sets,
        "artworks": artworks,
        "cards": cards,
        "artworks_no_rarity": artworks_no_rarity,
        "artworks_no_image": artworks_no_image,
        "artworks_no_name_ja": artworks_no_name_ja,
        "variants": variants,
    }


async def run() -> dict[str, Any]:
    """CLI entrypoint: print + return a catalog health snapshot."""
    async with async_session_factory() as session:
        totals = await _run_totals(session)
        orphans = await _orphan_counts(session)
        per_set = await _set_summary(session)

    print("=== catalog verify ===")
    print(f"sets:               {totals['sets']}")
    print(f"artworks:           {totals['artworks']}")
    print(f"cards (prints):     {totals['cards']}")
    print(f"variants:           {totals['variants']}")
    print(f"artworks w/o rar:   {totals['artworks_no_rarity']}")
    print(f"artworks w/o img:   {totals['artworks_no_image']}")
    print(f"artworks w/o ja:    {totals['artworks_no_name_ja']}")
    print(f"orphan artworks:    {orphans['orphan_artworks']}")
    print(f"orphan cards:       {orphans['orphan_cards']}")
    print()
    print(
        f"{'set_code':<10} {'era':<6} {'tot':>4} "
        f"{'art':>5} {'ja':>5} {'rar':>5} {'img':>5} {'prn':>5} {'var':>4}  set_name_ja"
    )
    print("-" * 95)
    for row in per_set:
        print(
            f"{row['set_code']:<10} "
            f"{row['era_block']:<6} "
            f"{str(row['total'] or '-'):>4} "
            f"{row['artworks_present']:>5} "
            f"{row['artworks_with_name_ja']:>5} "
            f"{row['artworks_with_rarity']:>5} "
            f"{row['artworks_with_image']:>5} "
            f"{row['cards_present']:>5} "
            f"{row['variants_present']:>4}  "
            f"{row['name_ja'] or ''}"
        )

    return {"totals": totals, **orphans, "per_set": per_set}
