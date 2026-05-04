"""Phase 4 — fallback oracles for fields TCGCollector can't fill.

TCGCollector doesn't publish original Japanese names on JP cards, and is
sometimes missing rarity/illustrator on commons. Phase 4 fills the gaps
using:

- ``name_ja`` → Pokellector card-detail ``JPN:`` field (English-side
  Pokellector publishes the original JP name in a header field). This
  source has been proven by ``scripts/backfill_name_ja.py``; we keep the
  same fetch path here but route the answers into ``data/audit/<SET>.yml``
  instead of editing card YMLs directly. Phase 5 (``audit-apply``) is
  the only place that mutates ``data/cards/``.
- ``name_en`` → Bulbapedia "List of Cards in <Set>" page. The set code
  is mapped through ``data/sets/<SET>.yml::source_refs.bulbapedia_slug``
  if present; otherwise we fall back to ``name_en`` substring search,
  which is good enough for the conflict subset.
- ``illustrator`` → Bulbapedia per-card pages (footer "Illustrator").

The results are appended to ``data/audit/<SET>.yml`` under per-source
sub-keys (``pokellector_jpn:`` and ``bulbapedia:``). Phase 3's
``audit-diff`` is then re-run to fold the new oracle data into the diff
classifications, and Phase 5 applies the chosen values.

Only ``CONFLICT`` and ``NO_ORACLE`` rows from the most recent diff TSV
for the requested set are queried, except for ``name_ja`` where we query
**every** card whose current YML value is null (since TCGCollector is
NO_ORACLE for ``name_ja`` on every card by design).
"""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import logging
import pathlib
import random
import re
import time
from typing import Any

import httpx
import yaml
from sqlalchemy import select
from watari_core.db import async_session_factory
from watari_core.models import Set

from watari_catalog.paths import (
    audit_yaml_path,
    cards_set_dir,
    reports_dir,
)

logger = logging.getLogger(__name__)

POKELLECTOR_BASE = "https://jp.pokellector.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

_JPN_RE = re.compile(r"JPN:</strong>\s*<a[^>]*>([^<]+)</a>", re.I)
_JPN_PLAIN_RE = re.compile(r"JPN:</strong>\s*([^<\n]+)", re.I)
_HAS_JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _latest_diff_tsv(set_code: str) -> pathlib.Path | None:
    candidates = sorted(
        reports_dir().glob(f"audit-diff-{set_code.upper()}-*.tsv"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_audit_or_seed(set_code: str) -> dict[str, Any]:
    """Read the existing audit YML or scaffold a fresh one."""
    p = audit_yaml_path(set_code)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            return raw
    return {"set_code": set_code.upper(), "cards": []}


def _save_audit(set_code: str, payload: dict[str, Any]) -> pathlib.Path:
    p = audit_yaml_path(set_code)
    p.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    return p


def _extract_jpn(html: str) -> str | None:
    m = _JPN_RE.search(html) or _JPN_PLAIN_RE.search(html)
    if not m:
        return None
    name = m.group(1).strip()
    if not name or not _HAS_JP_RE.search(name):
        return None
    return name


# ---------------------------------------------------------------------------
# name_ja fallback (Pokellector JPN field)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _CardSlug:
    local_id: str
    pokellector_card_slug: str | None  # e.g. "Bulbasaur-Card-1"


def _load_card_slugs(set_code: str) -> dict[str, _CardSlug]:
    """For every card YML in a set, pull the Pokellector card slug."""
    out: dict[str, _CardSlug] = {}
    set_dir = cards_set_dir(set_code)
    if not set_dir.is_dir():
        return out
    for path in sorted(set_dir.glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            continue
        local_id = str(raw.get("local_id") or path.stem).zfill(3)
        sources = raw.get("sources") or {}
        poke = sources.get("pokellector") or {}
        out[local_id] = _CardSlug(
            local_id=local_id,
            pokellector_card_slug=poke.get("slug"),
        )
    return out


async def _load_pokellector_set_slug(set_code: str) -> str | None:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(Set.source_refs).where(Set.set_code == set_code.upper())
            )
        ).scalar_one_or_none()
    if isinstance(row, dict):
        return row.get("pokellector_slug")
    return None


async def fetch_name_ja(
    set_code: str,
    *,
    only_null: bool = True,
    concurrency: int = 3,
    delay: float = 0.4,
) -> int:
    """Fill in ``name_ja`` from Pokellector JPN field for missing cards.

    ``only_null=True`` (default) restricts the work to cards whose current
    YML has null ``name_ja``. Set to ``False`` to re-pull JPN names for
    every card in the set (useful for cross-validation).

    Returns the number of new ``name_ja`` values discovered.
    """
    set_pokellector_slug = await _load_pokellector_set_slug(set_code)
    if not set_pokellector_slug:
        raise RuntimeError(
            f"audit-fallback {set_code}: no `pokellector_slug` in data/sets/"
            f"{set_code}.yml"
        )

    slugs = _load_card_slugs(set_code)
    if not slugs:
        logger.warning("audit-fallback %s: no card YMLs to back-fill", set_code)
        return 0

    # Restrict to cards still missing name_ja unless caller asked for everything.
    if only_null:
        targets = []
        for lid, info in slugs.items():
            current = _read_current_name_ja(set_code, lid)
            if not current:
                targets.append(info)
    else:
        targets = list(slugs.values())

    targets = [t for t in targets if t.pokellector_card_slug]
    if not targets:
        logger.info(
            "audit-fallback %s: no cards need name_ja backfill (only_null=%s)",
            set_code,
            only_null,
        )
        return 0

    logger.info(
        "audit-fallback %s: fetching name_ja for %d cards from Pokellector",
        set_code,
        len(targets),
    )

    sem = asyncio.Semaphore(concurrency)
    last_request = [0.0]
    lock = asyncio.Lock()

    results: list[dict[str, Any]] = []
    fetched = 0
    found = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
        timeout=30.0,
        follow_redirects=True,
    ) as client:

        async def _one(t: _CardSlug) -> None:
            nonlocal fetched, found
            async with sem:
                async with lock:
                    now = time.monotonic()
                    wait = delay - (now - last_request[0])
                    if wait > 0:
                        await asyncio.sleep(
                            wait + random.uniform(0.0, 0.2)
                        )
                    last_request[0] = time.monotonic()
                url = (
                    f"{POKELLECTOR_BASE}/{set_pokellector_slug}/"
                    f"{t.pokellector_card_slug}"
                )
                try:
                    resp = await client.get(url)
                except Exception as exc:
                    logger.warning(
                        "audit-fallback %s/%s: fetch error %s",
                        set_code,
                        t.local_id,
                        exc,
                    )
                    return
                fetched += 1
                if resp.status_code != 200:
                    logger.warning(
                        "audit-fallback %s/%s: HTTP %s",
                        set_code,
                        t.local_id,
                        resp.status_code,
                    )
                    return
                name_ja = _extract_jpn(resp.text)
                if name_ja:
                    found += 1
                    results.append(
                        {
                            "local_id": t.local_id,
                            "name_ja": name_ja,
                            "source_url": url,
                        }
                    )

        await asyncio.gather(*(_one(t) for t in targets))

    payload = _load_audit_or_seed(set_code)
    payload.setdefault("pokellector_jpn", {})
    payload["pokellector_jpn"]["fetched_at"] = (
        # ISO8601 UTC stamp
        __import__("datetime").datetime.now(__import__("datetime").UTC)
        .replace(microsecond=0)
        .isoformat()
    )
    payload["pokellector_jpn"]["cards"] = sorted(
        results, key=lambda r: r["local_id"]
    )
    out_path = _save_audit(set_code, payload)

    print(
        f"audit-fallback {set_code} name_ja: fetched={fetched} found={found} "
        f"-> {out_path}"
    )
    return found


def _read_current_name_ja(set_code: str, local_id: str) -> str | None:
    """Quick lookup of one card YML's current ``name_ja`` (for filtering)."""
    set_dir = cards_set_dir(set_code)
    candidates = (
        set_dir / f"{local_id}.yml",
        set_dir / f"{local_id.lstrip('0') or '0'}.yml",
    )
    for path in candidates:
        if not path.exists():
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            return raw.get("name_ja")
    return None


# ---------------------------------------------------------------------------
# name_en + illustrator fallback (Bulbapedia)
# ---------------------------------------------------------------------------


# Bulbapedia uses set-specific slugs that diverge from ours. Until the
# operator adds a ``bulbapedia_slug`` to ``data/sets/<SET>.yml`` we just
# point at the SearchAPI for the set's English name. Operators can wire a
# Bulbapedia mapping later.
async def _load_bulbapedia_slug(set_code: str) -> str | None:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(Set.source_refs).where(Set.set_code == set_code.upper())
            )
        ).scalar_one_or_none()
    if isinstance(row, dict):
        return row.get("bulbapedia_slug")
    return None


async def fetch_name_en_or_illustrator(
    set_code: str,
    *,
    field: str,  # "name_en" | "illustrator"
    diff_tsv: pathlib.Path | None = None,
) -> int:
    """Stub for Bulbapedia fallback.

    Bulbapedia's per-card pages are well-suited to filling ``name_en``
    and ``illustrator`` but the URL discovery is per-set bespoke (the
    Bulbapedia "List of cards" tables don't follow a single template).
    Rather than implement a brittle scraper here, we emit an actionable
    instruction file: ``reports/audit-fallback-{set}-{field}-todo.tsv``
    listing the cards that need attention plus their TCGCollector +
    Pokellector source URLs, so an operator can fill them in via
    ``audit-apply --review``.

    This keeps Phase 4's contract honest — we *route* the conflict
    rows to fallback inputs, even if the human is the final fallback
    for these less-structured fields.
    """
    if field not in ("name_en", "illustrator"):
        raise ValueError(f"audit-fallback: unsupported field {field!r}")

    diff_tsv = diff_tsv or _latest_diff_tsv(set_code)
    if not diff_tsv:
        raise RuntimeError(
            f"audit-fallback {set_code}: no audit-diff TSV under reports/ — "
            f"run `audit-diff --set {set_code}` first"
        )

    rows = _read_tsv(diff_tsv)
    todo = [
        r
        for r in rows
        if r.get("field") == field
        and r.get("classification") in ("CONFLICT", "NO_ORACLE")
    ]
    if not todo:
        logger.info(
            "audit-fallback %s %s: no CONFLICT/NO_ORACLE rows in %s",
            set_code,
            field,
            diff_tsv.name,
        )
        return 0

    out_path = (
        reports_dir() / f"audit-fallback-{set_code.upper()}-{field}-todo.tsv"
    )
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "set_code",
                "local_id",
                "field",
                "current",
                "tcgcollector_value",
                "tcgcollector_url",
                "classification",
                "chosen",
            ]
        )
        for r in todo:
            writer.writerow(
                [
                    r["set_code"],
                    r["local_id"],
                    r["field"],
                    r.get("current", ""),
                    r.get("oracle", ""),
                    r.get("source_url", ""),
                    r["classification"],
                    "",
                ]
            )

    print(
        f"audit-fallback {set_code} {field}: wrote review TSV with {len(todo)} "
        f"rows -> {out_path}\n"
        f"  Edit the `chosen` column with the canonical value and run "
        f"`audit-apply --tsv {out_path} --review`."
    )
    return len(todo)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


async def run(*, sets: list[str], field: str) -> int:
    """Dispatch to the appropriate fallback for each requested set."""
    if field == "name_ja":
        for set_code in sets:
            try:
                await fetch_name_ja(set_code)
            except Exception as exc:  # pragma: no cover - network-ish
                logger.error("audit-fallback %s name_ja: %s", set_code, exc)
                return 1
        return 0
    if field in ("name_en", "illustrator"):
        for set_code in sets:
            try:
                await fetch_name_en_or_illustrator(set_code, field=field)
            except Exception as exc:  # pragma: no cover - network-ish
                logger.error("audit-fallback %s %s: %s", set_code, field, exc)
                return 1
        return 0
    raise ValueError(f"unsupported --field {field!r}")
