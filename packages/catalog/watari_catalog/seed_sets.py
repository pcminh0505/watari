"""Idempotently upsert curated Set rows from ``data/sets/*.yml`` into the DB.

Each set lives in its own YML file (``packages/catalog/data/sets/{SET_CODE}.yml``)
so that a PR touching one set is easy to review and merge conflicts stay local
to one file. The seeder loads every ``*.yml`` under ``data/sets`` and upserts.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import yaml
from watari_core.db import async_session_factory
from watari_core.models import Set
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from watari_catalog.paths import sets_dir

logger = logging.getLogger(__name__)


def _iter_set_files() -> list[pathlib.Path]:
    return sorted(sets_dir().glob("*.yml"))


def load_sets_yaml() -> list[dict[str, Any]]:
    """Read every YML under ``data/sets/`` and return normalized set dicts.

    Each file must contain a mapping with at least ``set_code``. Lists
    (legacy ``sets: [...]`` shape) are not accepted here — they've been
    migrated to one-file-per-set.
    """
    files = _iter_set_files()
    if not files:
        raise RuntimeError(f"No set YML files found under {sets_dir()}")
    out: list[dict[str, Any]] = []
    for path in files:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected top-level mapping")
        out.append(_normalize(raw, source_path=path))
    return out


def _normalize(entry: dict[str, Any], *, source_path: pathlib.Path) -> dict[str, Any]:
    """Coerce YAML entry into a DB-insertable dict."""
    if "set_code" not in entry:
        raise ValueError(f"{source_path}: missing set_code")
    set_code = str(entry["set_code"]).upper()
    if source_path.stem != set_code:
        raise ValueError(
            f"{source_path}: filename stem {source_path.stem!r} != set_code {set_code!r}"
        )
    source_refs: dict[str, Any] = {"sets_yml": True}
    if entry.get("pokellector_slug"):
        source_refs["pokellector_slug"] = entry["pokellector_slug"]
    return {
        "set_code": set_code,
        "era_block": str(entry.get("era_block") or "unknown").lower(),
        "language": str(entry.get("language") or "jp").lower(),
        "name_ja": entry.get("name_ja"),
        "name_en": entry.get("name_en"),
        "release_date": entry.get("release_date"),
        "total": entry.get("total"),
        "parent_set_code": (
            str(entry["parent_set_code"]).upper()
            if entry.get("parent_set_code")
            else None
        ),
        "tcgdex_id": entry.get("tcgdex_id"),
        "source_refs": source_refs,
    }


async def upsert_sets(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> tuple[int, int]:
    """Upsert the provided set rows. Returns (attempted, rows_upserted)."""
    if not rows:
        return 0, 0

    stmt = pg_insert(Set).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["set_code"],
        set_={
            "era_block": stmt.excluded.era_block,
            "language": stmt.excluded.language,
            "name_ja": stmt.excluded.name_ja,
            "name_en": stmt.excluded.name_en,
            "release_date": stmt.excluded.release_date,
            "total": stmt.excluded.total,
            "parent_set_code": stmt.excluded.parent_set_code,
            "tcgdex_id": stmt.excluded.tcgdex_id,
            "source_refs": stmt.excluded.source_refs,
        },
    )
    result = await session.execute(stmt)
    await session.commit()
    return len(rows), int(result.rowcount or 0)  # type: ignore[attr-defined]


async def run() -> dict[str, int]:
    """CLI entrypoint: seed all sets from ``data/sets/*.yml``."""
    rows = load_sets_yaml()
    async with async_session_factory() as session:
        attempted, upserted = await upsert_sets(session, rows)
    logger.info("seed-sets: %d attempted, %d upserted", attempted, upserted)
    return {"attempted": attempted, "upserted": upserted}
