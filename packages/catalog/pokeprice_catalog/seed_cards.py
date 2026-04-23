"""Load ``data/cards/*/*.yml`` into the ``artworks`` and ``cards`` tables.

This is the **runtime build**: it is network-free and only reads committed
YMLs. It is idempotent — re-running with the same tree is a no-op (aside
from bumping ``updated_at``).
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import yaml
from pokeprice_core.catalog import make_artwork_id, make_card_id, pad_local_id
from pokeprice_core.db import async_session_factory
from pokeprice_core.models import Artwork, Card, Set
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pokeprice_catalog.paths import cards_dir, cards_set_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YML discovery
# ---------------------------------------------------------------------------


def _iter_set_dirs(sets: list[str] | None) -> list[pathlib.Path]:
    if sets:
        return [cards_set_dir(s) for s in sets]
    if not cards_dir().exists():
        return []
    return sorted(
        d for d in cards_dir().iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def _iter_card_files(set_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(set_dir.glob("*.yml"))


def _load(path: pathlib.Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected top-level mapping")
    return raw


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _artwork_row(set_code: str, card: dict[str, Any]) -> dict[str, Any]:
    local_id_raw = str(card["local_id"])
    padded = pad_local_id(local_id_raw)
    return {
        "artwork_id": make_artwork_id(set_code, padded),
        "set_code": set_code,
        "local_id": padded,
        "name_ja": card.get("name_ja"),
        "name_en": card.get("name_en"),
        "rarity_code": card.get("rarity_code"),
        "image_url": card.get("image"),
        "category": (card.get("category") or "card").lower(),
        "illustrator": card.get("illustrator"),
        "source_refs": card.get("sources") or {},
    }


def _card_rows(set_code: str, card: dict[str, Any]) -> list[dict[str, Any]]:
    local_id_raw = str(card["local_id"])
    padded = pad_local_id(local_id_raw)
    artwork_id = make_artwork_id(set_code, padded)
    prints = card.get("prints") or ["normal"]
    rows: list[dict[str, Any]] = []
    for variant in prints:
        rows.append(
            {
                "card_id": make_card_id(set_code, padded, variant),
                "artwork_id": artwork_id,
                "set_code": set_code,
                "local_id": padded,
                "variant": variant,
                "is_tracked": True,
                "source_refs": {},
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


async def _upsert_artworks(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    stmt = pg_insert(Artwork).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["artwork_id"],
        set_={
            "set_code": stmt.excluded.set_code,
            "local_id": stmt.excluded.local_id,
            "name_ja": stmt.excluded.name_ja,
            "name_en": stmt.excluded.name_en,
            "rarity_code": stmt.excluded.rarity_code,
            "image_url": stmt.excluded.image_url,
            "category": stmt.excluded.category,
            "illustrator": stmt.excluded.illustrator,
            "source_refs": stmt.excluded.source_refs,
        },
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def _upsert_cards(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    stmt = pg_insert(Card).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["card_id"],
        set_={
            "artwork_id": stmt.excluded.artwork_id,
            "set_code": stmt.excluded.set_code,
            "local_id": stmt.excluded.local_id,
            "variant": stmt.excluded.variant,
            "is_tracked": stmt.excluded.is_tracked,
        },
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def _known_set_codes(session: AsyncSession) -> set[str]:
    result = await session.execute(select(Set.set_code))
    return {row[0] for row in result.all()}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run(sets: list[str] | None = None) -> dict[str, Any]:
    """Load YMLs for the requested sets (or every set under ``data/cards/``)."""
    totals = {"sets_loaded": 0, "artworks_upserted": 0, "cards_upserted": 0}
    per_set: list[dict[str, Any]] = []

    async with async_session_factory() as session:
        known = await _known_set_codes(session)

        for set_dir in _iter_set_dirs(sets):
            set_code = set_dir.name.upper()
            if set_code not in known:
                logger.warning(
                    "skip %s: set_code not found in `sets` (run seed-sets first)",
                    set_code,
                )
                continue

            artwork_rows: list[dict[str, Any]] = []
            card_rows: list[dict[str, Any]] = []
            for card_path in _iter_card_files(set_dir):
                try:
                    card = _load(card_path)
                except Exception as exc:
                    logger.error("failed to read %s: %s", card_path, exc)
                    continue
                artwork_rows.append(_artwork_row(set_code, card))
                card_rows.extend(_card_rows(set_code, card))

            upserted_artworks = await _upsert_artworks(session, artwork_rows)
            upserted_cards = await _upsert_cards(session, card_rows)

            totals["sets_loaded"] += 1
            totals["artworks_upserted"] += upserted_artworks
            totals["cards_upserted"] += upserted_cards
            per_set.append(
                {
                    "set_code": set_code,
                    "yml_files": len(artwork_rows),
                    "artworks_upserted": upserted_artworks,
                    "cards_upserted": upserted_cards,
                }
            )
            logger.info(
                "seed-cards %s: files=%d artworks_upserted=%d cards_upserted=%d",
                set_code,
                len(artwork_rows),
                upserted_artworks,
                upserted_cards,
            )

    return {"totals": totals, "per_set": per_set}
