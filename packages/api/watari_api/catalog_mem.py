"""In-memory catalog loaded from YAML files at startup.

Replaces the DB-backed catalog for online mode (no PostgreSQL required).
Sets and cards are loaded once at process start from the YAML tree in
``packages/catalog/data/``, then served from memory for the life of the
process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import yaml
from watari_catalog.paths import cards_dir, sets_dir
from watari_catalog.seed_sets import load_sets_yaml
from watari_core.catalog import make_artwork_id, make_card_id, pad_local_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemVariant:
    variant: str
    card_id: str
    is_tracked: bool = True


@dataclass
class MemArtwork:
    artwork_id: str
    set_code: str
    local_id: str
    name_ja: str | None
    name_en: str | None
    rarity_code: str | None
    image_url: str | None
    illustrator: str | None
    category: str
    language: str
    variants: list[MemVariant]
    set_name_ja: str | None = None
    set_name_en: str | None = None
    set_release_date: date | None = None


@dataclass
class MemSet:
    set_code: str
    era_block: str
    language: str
    name_ja: str | None
    name_en: str | None
    release_date: date | None
    total: int | None
    parent_set_code: str | None
    tcgdex_id: str | None
    source_refs: dict[str, Any]
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MemCatalog:
    """In-memory catalog indexed by set_code and (set_code, local_id)."""

    def __init__(self, sets: list[MemSet], artworks: list[MemArtwork]) -> None:
        self._sets: dict[str, MemSet] = {s.set_code.upper(): s for s in sets}
        self._artworks: dict[tuple[str, str], MemArtwork] = {}
        self._artworks_by_set: dict[str, list[MemArtwork]] = {}

        for a in artworks:
            key = (a.set_code.upper(), a.local_id)
            self._artworks[key] = a
            self._artworks_by_set.setdefault(a.set_code.upper(), []).append(a)

        for sc in self._artworks_by_set:
            self._artworks_by_set[sc].sort(key=lambda a: a.local_id)

    @classmethod
    def load(cls) -> MemCatalog:
        """Load all YAMLs from the catalog data directory."""
        logger.info("catalog_mem: loading sets from YAML...")
        raw_sets = load_sets_yaml()
        loaded_at = datetime.now(UTC)

        sets: list[MemSet] = []
        for s in raw_sets:
            sets.append(
                MemSet(
                    set_code=s["set_code"],
                    era_block=s["era_block"],
                    language=s["language"],
                    name_ja=s.get("name_ja"),
                    name_en=s.get("name_en"),
                    release_date=s.get("release_date"),
                    total=s.get("total"),
                    parent_set_code=s.get("parent_set_code"),
                    tcgdex_id=s.get("tcgdex_id"),
                    source_refs=s.get("source_refs", {}),
                    loaded_at=loaded_at,
                )
            )

        set_map = {s.set_code: s for s in sets}

        logger.info("catalog_mem: loading card YAMLs...")
        artworks: list[MemArtwork] = []
        cards_base = cards_dir()

        for set_dir in sorted(cards_base.iterdir()):
            if not set_dir.is_dir():
                continue
            sc = set_dir.name.upper()
            mem_set = set_map.get(sc)

            for card_yaml_path in sorted(set_dir.glob("*.yml")):
                try:
                    raw: Any = yaml.safe_load(card_yaml_path.read_text(encoding="utf-8"))
                except Exception:
                    logger.warning("catalog_mem: failed to load %s", card_yaml_path)
                    continue
                if not isinstance(raw, dict):
                    continue

                local_id = pad_local_id(str(raw.get("local_id", card_yaml_path.stem)))
                artwork_id = make_artwork_id(sc, local_id)
                prints: list[str] = raw.get("prints") or ["normal"]
                variants = [
                    MemVariant(
                        variant=v,
                        card_id=make_card_id(artwork_id, v),
                        is_tracked=True,
                    )
                    for v in prints
                ]
                artworks.append(
                    MemArtwork(
                        artwork_id=artwork_id,
                        set_code=sc,
                        local_id=local_id,
                        name_ja=raw.get("name_ja") or None,
                        name_en=raw.get("name_en") or None,
                        rarity_code=raw.get("rarity_code") or None,
                        image_url=raw.get("image") or None,
                        illustrator=raw.get("illustrator") or None,
                        category=str(raw.get("category") or "card"),
                        language=mem_set.language if mem_set else "jp",
                        variants=variants,
                        set_name_ja=mem_set.name_ja if mem_set else None,
                        set_name_en=mem_set.name_en if mem_set else None,
                        set_release_date=mem_set.release_date if mem_set else None,
                    )
                )

        logger.info(
            "catalog_mem: loaded %d sets, %d artworks", len(sets), len(artworks)
        )
        return cls(sets, artworks)

    # --- sets ----------------------------------------------------------------

    def get_sets(self, *, language: str = "jp", era: str | None = None) -> list[MemSet]:
        sets = [s for s in self._sets.values() if s.language == language]
        if era is not None:
            sets = [s for s in sets if s.era_block == era.lower()]
        return sets

    def get_set(self, set_code: str, *, language: str = "jp") -> MemSet | None:
        s = self._sets.get(set_code.upper())
        if s is None or s.language != language:
            return None
        return s

    # --- artworks ------------------------------------------------------------

    def get_artworks(self, set_code: str) -> list[MemArtwork]:
        return list(self._artworks_by_set.get(set_code.upper(), []))

    def get_artwork(self, set_code: str, local_id: str) -> MemArtwork | None:
        return self._artworks.get((set_code.upper(), pad_local_id(local_id)))

    def search_artworks(
        self,
        *,
        language: str = "jp",
        q: str | None = None,
        set_code: str | None = None,
        rarity: str | None = None,
        illustrator: str | None = None,
    ) -> list[MemArtwork]:
        results = [a for a in self._artworks.values() if a.language == language]
        if set_code is not None:
            sc_upper = set_code.upper()
            results = [a for a in results if a.set_code == sc_upper]
        if rarity is not None:
            results = [a for a in results if a.rarity_code == rarity]
        if illustrator is not None:
            results = [a for a in results if a.illustrator == illustrator]
        if q is not None:
            q_lower = q.lower()
            q_padded = pad_local_id(q) if q.isdigit() else q
            results = [
                a
                for a in results
                if (a.name_ja and q_lower in a.name_ja.lower())
                or (a.name_en and q_lower in a.name_en.lower())
                or a.local_id == q_padded
                or a.set_code.upper() == q.upper()
            ]
        _DATE_MIN = date.min
        results.sort(
            key=lambda a: (a.set_release_date or _DATE_MIN, a.set_code, a.local_id),
            reverse=True,
        )
        return results

    def get_rarities(self, *, language: str = "jp", set_code: str | None = None) -> list[str]:
        if set_code is not None:
            artworks: list[MemArtwork] = self.get_artworks(set_code)
        else:
            artworks = [a for a in self._artworks.values() if a.language == language]
        return sorted({a.rarity_code for a in artworks if a.rarity_code})
