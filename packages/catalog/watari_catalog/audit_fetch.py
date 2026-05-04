"""Phase 2 entrypoint — fetch a set's TCGCollector data into ``data/audit/``.

Per-set flow:

1. Look up ``tcgcollector_id`` and ``tcgcollector_slug`` in
   ``data/sets/<SET>.yml``. Bail with a clear error if missing.
2. Use ``TcgCollectorClient`` to fetch the set index + every per-card
   detail page (with ``curl_cffi`` and bronze mirroring).
3. Parse the rarity / illustrator / name_en triplet out of each detail page.
4. Write ``data/audit/<SET>.yml`` (committed): one row per card with
   ``rarity_raw``, ``rarity_canon``, ``illustrator``, ``name_en``,
   ``card_id``, ``detail_url``.

This is **never** wired into the live bootstrap pipeline. Phase 7 is the
only place where audit data feeds back into ``data/cards/``.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from watari_core.db import async_session_factory
from watari_core.ingestion import finish_scrape_run, start_scrape_run
from watari_core.models import Set

from watari_catalog.paths import audit_dir, audit_yaml_path
from watari_catalog.rarities import canonicalize_tcgcollector
from watari_catalog.tcgcollector_client import (
    TcgCollectorClient,
    fetch_full_set,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-set fetch
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AuditFetchResult:
    set_code: str
    cards_indexed: int
    cards_with_detail: int
    cards_with_rarity: int
    cards_with_illustrator: int
    audit_path: str

    def summary(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


async def _load_set_oracle_refs(
    set_code: str,
) -> tuple[str, str]:
    """Read ``tcgcollector`` source-refs out of the ``sets`` table.

    Raises ``RuntimeError`` if the slug is missing — operator must add
    it to ``data/sets/<SET>.yml`` before re-running.
    """
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(Set.source_refs).where(Set.set_code == set_code.upper())
            )
        ).scalar_one_or_none()
    if row is None:
        raise RuntimeError(
            f"audit-fetch {set_code}: not found in `sets` "
            f"(run `make catalog-seed-sets` first)"
        )
    refs = row.get("tcgcollector") if isinstance(row, dict) else None
    if not refs or not refs.get("slug") or not refs.get("id"):
        raise RuntimeError(
            f"audit-fetch {set_code}: data/sets/{set_code}.yml is missing "
            f"`tcgcollector_id` and/or `tcgcollector_slug`. Look up the set on "
            f"https://www.tcgcollector.com/expansions/jp and fill in both fields."
        )
    return str(refs["id"]), str(refs["slug"])


async def fetch_one(
    set_code: str,
    *,
    concurrency: int = 2,
    bronze: bool = True,
) -> AuditFetchResult:
    set_id, slug = await _load_set_oracle_refs(set_code)

    async with async_session_factory() as session:
        run_id = await start_scrape_run(
            session,
            "catalog.audit.tcgcollector",
            metadata={"set_code": set_code.upper()},
        )

    observed_at = datetime.now(UTC)
    rows_written = 0
    cards_indexed = 0
    cards_with_detail = 0
    cards_with_rarity = 0
    cards_with_illustrator = 0

    audit_dir().mkdir(parents=True, exist_ok=True)

    async with TcgCollectorClient() as client:
        try:
            entries, details = await fetch_full_set(
                client,
                set_id=set_id,
                slug=slug,
                set_code=set_code.upper(),
                run_id=run_id,
                observed_at=observed_at,
                detail_concurrency=concurrency,
                bronze=bronze,
            )
        except FileNotFoundError as exc:
            logger.error(
                "audit-fetch %s: TCGCollector returned 404 (%s) — "
                "verify tcgcollector_id/slug in data/sets/%s.yml",
                set_code,
                exc,
                set_code,
            )
            async with async_session_factory() as session:
                await finish_scrape_run(
                    session,
                    run_id=run_id,
                    status="failed",
                    cards_attempted=0,
                    cards_succeeded=0,
                    rows_written=0,
                )
            raise

    cards_indexed = len(entries)

    audit_cards: list[dict[str, Any]] = []
    for entry in entries:
        detail = details.get(entry.local_id)
        rarity_canon = (
            canonicalize_tcgcollector(detail.rarity_raw) if detail else None
        )
        if detail is not None:
            cards_with_detail += 1
            if detail.rarity_raw:
                cards_with_rarity += 1
            if detail.illustrator:
                cards_with_illustrator += 1

        audit_cards.append(
            {
                "local_id": entry.local_id,
                "card_id": entry.card_id,
                "name_en": detail.name_en if detail else None,
                "rarity_raw": detail.rarity_raw if detail else None,
                "rarity_canon": rarity_canon,
                "illustrator": detail.illustrator if detail else None,
                "card_number_raw": detail.card_number_raw if detail else None,
                "expansion_raw": detail.expansion_raw if detail else None,
                "detail_url": f"https://www.tcgcollector.com{entry.detail_path}",
            }
        )

    payload: dict[str, Any] = {
        "set_code": set_code.upper(),
        "fetched_at": observed_at.isoformat(),
        "source": "tcgcollector",
        "tcgcollector_id": set_id,
        "tcgcollector_slug": slug,
        "totals": {
            "cards_indexed": cards_indexed,
            "cards_with_detail": cards_with_detail,
            "cards_with_rarity": cards_with_rarity,
            "cards_with_illustrator": cards_with_illustrator,
        },
        "cards": audit_cards,
    }

    audit_path = audit_yaml_path(set_code)
    audit_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    rows_written = len(audit_cards)

    async with async_session_factory() as session:
        await finish_scrape_run(
            session,
            run_id=run_id,
            status="completed",
            cards_attempted=cards_indexed,
            cards_succeeded=cards_with_detail,
            rows_written=rows_written,
        )

    logger.info(
        "audit-fetch %s: indexed=%d details=%d rarity=%d ill=%d -> %s",
        set_code,
        cards_indexed,
        cards_with_detail,
        cards_with_rarity,
        cards_with_illustrator,
        audit_path,
    )
    print(
        f"audit-fetch {set_code.upper()}: "
        f"indexed={cards_indexed} details={cards_with_detail} "
        f"rarity={cards_with_rarity} illustrator={cards_with_illustrator}\n"
        f"  -> {audit_path}"
    )

    return AuditFetchResult(
        set_code=set_code.upper(),
        cards_indexed=cards_indexed,
        cards_with_detail=cards_with_detail,
        cards_with_rarity=cards_with_rarity,
        cards_with_illustrator=cards_with_illustrator,
        audit_path=str(audit_path),
    )


async def run(
    *,
    sets: list[str],
    concurrency: int = 2,
    bronze: bool = True,
) -> int:
    """CLI entrypoint."""
    failed: list[str] = []
    for set_code in sets:
        try:
            await fetch_one(set_code, concurrency=concurrency, bronze=bronze)
        except Exception as exc:  # pragma: no cover - network-ish
            logger.error("audit-fetch %s failed: %s", set_code, exc)
            failed.append(f"{set_code}: {exc}")
    if failed:
        print("\naudit-fetch FAILURES:")
        for line in failed:
            print(f"  - {line}")
        return 1
    return 0
