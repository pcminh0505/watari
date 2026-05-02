"""Cross-check committed card YAMLs against live jp.pokellector.com set indexes."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.db import async_session_factory
from watari_core.models import Set

from watari_catalog.paths import cards_set_dir
from watari_catalog.pokellector_client import (
    PokellectorClient,
    parse_set_index,
)


def _local_ids_on_disk(set_code: str) -> set[int]:
    d = cards_set_dir(set_code)
    if not d.is_dir():
        return set()
    return {int(p.stem) for p in d.glob("*.yml")}


def diff_local_ids(
    pokellector_local_ids: set[int], disk_ids: set[int]
) -> tuple[list[int], list[int]]:
    """Return (only on Pokellector, only on disk), sorted."""
    only_pk = sorted(pokellector_local_ids - disk_ids)
    only_disk = sorted(disk_ids - pokellector_local_ids)
    return only_pk, only_disk


def _preview_nums(nums: list[int], *, limit: int = 40) -> str:
    head = nums[:limit]
    tail = " …" if len(nums) > limit else ""
    return f"{head}{tail}"


async def _sets_to_check(
    session: AsyncSession, filter_codes: list[str] | None
) -> list[tuple[str, str]]:
    stmt = select(Set.set_code, Set.source_refs).order_by(Set.set_code)
    result = await session.execute(stmt)
    rows: list[tuple[str, str]] = []
    want = {c.upper() for c in filter_codes} if filter_codes else None
    for set_code, source_refs in result.all():
        if want is not None and set_code.upper() not in want:
            continue
        slug = (source_refs or {}).get("pokellector_slug")
        if not slug:
            continue
        rows.append((set_code, slug))
    return rows


async def run(
    *,
    sets: list[str] | None = None,
    timeout: float = 60.0,
) -> int:
    """Fetch Pokellector set indexes and compare local_ids to ``data/cards/{SET}``.

    Returns 0 if every checked set matches, 1 if any mismatch or fetch error.
    """
    async with async_session_factory() as session:
        targets = await _sets_to_check(session, sets)

    if not targets:
        print("verify-pokellector: no sets with pokellector_slug" + (
            f" (filter={sets})" if sets else ""
        ))
        return 1

    observed_at = datetime.now(UTC)
    run_id = 0
    problems = 0
    checked = 0

    print("=== verify-pokellector (jp.pokellector.com index vs data/cards) ===")
    print()

    async with PokellectorClient(timeout=timeout) as client:
        for set_code, slug in targets:
            disk_ids = _local_ids_on_disk(set_code)
            if not disk_ids:
                print(f"{set_code}: skip (no *.yml under data/cards/{set_code}/)")
                continue
            checked += 1
            try:
                html = await client.fetch_set_index(
                    slug,
                    set_code=set_code,
                    run_id=run_id,
                    observed_at=observed_at,
                    bronze=False,
                )
            except Exception as exc:
                problems += 1
                print(f"{set_code}: FETCH FAILED ({slug}/): {exc}")
                continue

            index = parse_set_index(html, slug)
            pk_ids = {int(c.local_id) for c in index.cards}
            only_pk, only_disk = diff_local_ids(pk_ids, disk_ids)

            url = f"https://jp.pokellector.com/{slug}/"
            if not only_pk and not only_disk:
                print(
                    f"{set_code}: OK  pokellector={len(pk_ids)}  disk={len(disk_ids)}  "
                    f"name_en={index.name_en!r}  {url}"
                )
            else:
                problems += 1
                print(f"{set_code}: MISMATCH  {url}")
                print(f"    pokellector cards: {len(pk_ids)}  disk yml: {len(disk_ids)}")
                if only_pk:
                    print(f"    only on Pokellector (#): {_preview_nums(only_pk)}")
                if only_disk:
                    print(f"    only on disk (#):        {_preview_nums(only_disk)}")

    print()
    if checked == 0:
        print("verify-pokellector: nothing checked (all sets skipped — missing yml dirs?)")
        return 1
    if problems:
        print(f"verify-pokellector: {problems} set(s) failed or mismatched (checked {checked})")
        return 1
    print(f"verify-pokellector: all {checked} set(s) match Pokellector card numbering")
    return 0
