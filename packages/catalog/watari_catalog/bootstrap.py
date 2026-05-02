"""Per-set bootstrap: fetch → merge → emit ``data/cards/{SET}/*.yml``.

Sources (precedence for each field listed in the merge table below):

- Pokellector (primary): image URL, English name, card rarity (text label).
- TCGdex (fallback): Japanese name, illustrator, TCGdex-native rarity.
- Cardrush (variant list): which variant prints exist per local_id.

After a successful bootstrap, the resulting YML tree is the source of truth
for the catalog — no network access is needed to rebuild the DB.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.catalog import pad_local_id
from watari_core.db import async_session_factory
from watari_core.ingestion import finish_scrape_run, start_scrape_run
from watari_core.models import Set

from watari_catalog.cardrush_client import CardrushClient, parse_listings_from_html
from watari_catalog.emit_yml import CardYamlPayload, EmitResult, write_card_yaml
from watari_catalog.parser import parse_cardrush_product_name
from watari_catalog.pokellector_client import (
    PokellectorCardDetail,
    PokellectorCardStub,
    PokellectorClient,
    card_image_url,
    fetch_full_set,
)
from watari_catalog.rarities import (
    canonicalize_cardrush,
    canonicalize_pokellector,
    canonicalize_tcgdex,
)
from watari_catalog.tcgdex_client import TcgdexClient
from watari_catalog.variants import DEFAULT_VARIANT

logger = logging.getLogger(__name__)

# Cardrush merges multiple rarity-bucket crawls onto the same local_id; pick the
# most specific canonical tag instead of retaining the earliest hit only.
_CARDRUSH_HINT_RANK: dict[str, int] = {
    "SSR": 98,
    "SAR": 100,
    "AR": 97,
    "SR": 95,
    "RRR": 92,
    "RR": 90,
    "MUR": 89,
    "UR": 88,
    "HR": 86,
    "CSR": 85,
    "CHR": 84,
    "TR": 83,
    "MA": 82,
    "K": 80,
    "R": 50,
    "U": 35,
    "C": 20,
}


def _cardrush_hint_rank(code: str) -> int:
    return _CARDRUSH_HINT_RANK.get(code.upper(), -1)


def _prefer_cardrush_rarity(current: str | None, incoming: str | None) -> str | None:
    """When the same listing appears across Cardrush rarity searches, prefer
    higher-specificity canon codes (RR over R over mistaken UR prefixes)."""
    if not incoming:
        return current
    if not current:
        return incoming
    ri = _cardrush_hint_rank(incoming)
    rc = _cardrush_hint_rank(current)
    if ri != rc:
        return incoming if ri > rc else current
    # Same specificity (e.g. two RR hits); normalized listing suffix wins stale.
    return incoming


_COLLECTORS_NUM_RE = re.compile(r"^(\d+)/(\d+)$")


def _is_secret_collectors_print(detail: PokellectorCardDetail | None) -> bool:
    """``104/098`` Secret-style collector numbers exceed the apparent set size."""
    if not detail or not detail.set_total_raw:
        return False
    m = _COLLECTORS_NUM_RE.match(detail.set_total_raw.strip())
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return a > b


def _likely_legacy_double_rare(name_en: str | None) -> bool:
    """Heuristic SM/S SwSh-era double-rare GX / TT / Pokémon V prints."""
    if not name_en:
        return False
    if "GX" in name_en:
        return True
    # Tag Team
    if " & " in name_en:
        return True
    if re.search(r"\bVMAX\b", name_en):
        return True
    if re.search(r"\bV\b$", name_en.rstrip()):
        return True
    return False


# ---------------------------------------------------------------------------
# Per-set context loaded from sets table
# ---------------------------------------------------------------------------


@dataclass
class BootstrapSetCtx:
    set_code: str                 # "SV2A"
    era_block: str | None          # sm | sv | sw | me
    name_ja: str | None           # "ポケモンカード151"
    tcgdex_id: str | None         # "sv2a" or None for ME sets
    pokellector_slug: str | None  # "Pokemon-151-Expansion"


async def _load_set_ctx(session: AsyncSession, set_code: str) -> BootstrapSetCtx:
    result = await session.execute(
        select(Set.set_code, Set.era_block, Set.name_ja, Set.tcgdex_id, Set.source_refs).where(
            Set.set_code == set_code.upper()
        )
    )
    row = result.one_or_none()
    if row is None:
        raise RuntimeError(
            f"Set {set_code} not found — run `seed-sets` first."
        )
    set_code_db, era_block, name_ja, tcgdex_id, source_refs = row
    pokellector_slug = (source_refs or {}).get("pokellector_slug")
    return BootstrapSetCtx(
        set_code=set_code_db,
        era_block=era_block,
        name_ja=name_ja,
        tcgdex_id=tcgdex_id,
        pokellector_slug=pokellector_slug,
    )


# ---------------------------------------------------------------------------
# TCGdex → per-card metadata
# ---------------------------------------------------------------------------


@dataclass
class TcgdexCardMeta:
    local_id: str                 # non-padded ("1", "150")
    name_ja: str | None
    rarity_raw: str | None
    illustrator: str | None
    category: str | None          # 'card' | 'trainer' | 'energy' | None


async def _fetch_tcgdex_set(
    tcgdex_id: str | None,
) -> dict[str, TcgdexCardMeta]:
    """Return ``{local_id (non-padded): meta}`` or empty when tcgdex_id is None."""
    if not tcgdex_id:
        return {}

    out: dict[str, TcgdexCardMeta] = {}
    async with TcgdexClient(language="ja") as c:
        payload = await c.get_set(tcgdex_id)
        if payload is None:
            logger.warning("tcgdex: set %s returned 404", tcgdex_id)
            return out
        cards = payload.get("cards") or []
        sem = asyncio.Semaphore(6)

        async def _one(card: dict[str, Any]) -> None:
            local_id = str(card.get("localId") or "").strip()
            if not local_id:
                return
            async with sem:
                full = await c.get_card(tcgdex_id, local_id)
            if full is None:
                return
            category = full.get("category")
            if isinstance(category, str):
                category_norm = category.lower()
                category_norm = (
                    "trainer" if "trainer" in category_norm
                    else "energy" if "energy" in category_norm
                    else "card"
                )
            else:
                category_norm = None
            out[local_id] = TcgdexCardMeta(
                local_id=local_id,
                name_ja=(full.get("name") or None),
                rarity_raw=full.get("rarity"),
                illustrator=full.get("illustrator"),
                category=category_norm,
            )

        await asyncio.gather(*[_one(c) for c in cards])
    return out


# ---------------------------------------------------------------------------
# Cardrush → variant + name_ja hints per local_id
# ---------------------------------------------------------------------------


@dataclass
class CardrushCardHints:
    name_ja: str | None
    variants: set[str]
    rarity_code: str | None


async def _fetch_cardrush_variants(
    set_code: str,
    *,
    rarities: list[str],
    max_pages: int = 15,
) -> dict[str, CardrushCardHints]:
    """Crawl Cardrush per rarity and build ``{padded_local_id: hints}``.

    Used purely for variant discovery and best-effort JA names. Network errors
    are logged; the merge still succeeds with whatever we got.
    """
    hints: dict[str, CardrushCardHints] = defaultdict(
        lambda: CardrushCardHints(
            name_ja=None,
            variants={DEFAULT_VARIANT},
            rarity_code=None,
        )
    )
    # Keep per-card the best name we've seen (ranked: normal variant wins over
    # a variant-suffixed name like ``ミュウツー(モンスターボールミラー)``).
    _best_name_rank: dict[str, int] = {}

    try:
        async with CardrushClient() as client:
            for rarity in rarities:
                keyword = f"{set_code} {rarity}"
                query_rarity = canonicalize_cardrush(rarity)
                try:
                    pages = await client.search_all_pages(keyword, max_pages=max_pages)
                except Exception as exc:  # pragma: no cover - network-ish
                    logger.warning("cardrush crawl %s failed: %s", keyword, exc)
                    continue
                for _page, html in pages:
                    for listing in parse_listings_from_html(html):
                        parsed = parse_cardrush_product_name(listing.name)
                        if not parsed or not parsed.local_id:
                            continue
                        if parsed.set_code and parsed.set_code.upper() != set_code.upper():
                            continue
                        padded = pad_local_id(str(parsed.local_id))
                        h = hints[padded]
                        if parsed.variant:
                            h.variants.add(parsed.variant)
                        parsed_or_query_rarity = parsed.rarity_code or query_rarity
                        if parsed_or_query_rarity:
                            h.rarity_code = _prefer_cardrush_rarity(
                                h.rarity_code,
                                parsed_or_query_rarity,
                            )
                        if parsed.name_ja:
                            # Prefer names from the "normal" variant listing
                            # over variant-suffixed ones.
                            rank = 2 if parsed.variant == DEFAULT_VARIANT else 1
                            if rank > _best_name_rank.get(padded, 0):
                                h.name_ja = parsed.name_ja
                                _best_name_rank[padded] = rank
    except Exception as exc:  # pragma: no cover - network-ish
        logger.warning("cardrush bootstrap-for-variants aborted: %s", exc)

    return dict(hints)


# Fallback rarity list used when the DB doesn't have any yet (bootstrap is
# usually the first thing we do for a set).
_DEFAULT_DISCOVERY_RARITIES = ["C", "U", "R", "RR", "AR", "SR", "SAR", "UR", "MA"]


# ---------------------------------------------------------------------------
# Merge + category inference
# ---------------------------------------------------------------------------


_TRAINER_KEYWORDS_JA = ("サポート", "グッズ", "スタジアム", "トレーナー")
_ENERGY_KEYWORDS_JA = ("エネルギー",)

# Strip a trailing Japanese variant-qualifier parenthesis (Cardrush style)
# e.g. ``ベトベトン(マスターボールミラー)`` → ``ベトベトン``.
_JA_VARIANT_SUFFIX_RE = re.compile(
    r"[(（](?:マスターボール|モンスターボール|クイックボール|ハイパーボール)"
    r"(?:柄|ミラー)[)）]\s*$"
)


def _strip_variant_suffix_ja(name_ja: str | None) -> str | None:
    if not name_ja:
        return name_ja
    return _JA_VARIANT_SUFFIX_RE.sub("", name_ja).rstrip()


def _infer_category(
    *,
    tcgdex: TcgdexCardMeta | None,
    name_ja: str | None,
    name_en: str | None,
) -> str:
    if tcgdex and tcgdex.category:
        return tcgdex.category
    joined = " ".join(filter(None, [name_ja or "", name_en or ""]))
    if any(k in joined for k in _TRAINER_KEYWORDS_JA) or "Trainer" in joined:
        return "trainer"
    if any(k in joined for k in _ENERGY_KEYWORDS_JA) or "Energy" in joined:
        return "energy"
    return "card"


def _choose_rarity(
    *,
    era_block: str | None,
    name_en: str | None,
    pokellector: PokellectorCardDetail | None,
    tcgdex: TcgdexCardMeta | None,
    cardrush: CardrushCardHints | None,
) -> str | None:
    """Pokellector wins when mappable; TCGdex fallback; else None.

    Cardrush is used only as a fallback when upstream labels are absent or
    unmappable (e.g. Pokellector "Secret Rare" in some SwSh sets).
    """
    if pokellector and pokellector.rarity_raw:
        mapped = canonicalize_pokellector(pokellector.rarity_raw)
        if mapped:
            raw_label = pokellector.rarity_raw.strip()
            legacy_ultra_miscast = (
                mapped == "UR"
                and raw_label == "Ultra Rare"
                and (era_block in ("sm", "sw"))
            )
            if legacy_ultra_miscast:
                cr = cardrush.rarity_code if cardrush else None
                if cr and cr != "UR":
                    return cr
                if tcgdex and tcgdex.rarity_raw:
                    tcg_mapped = canonicalize_tcgdex(tcgdex.rarity_raw)
                    if tcg_mapped == "RR":
                        return "RR"
                if not _is_secret_collectors_print(pokellector):
                    if _likely_legacy_double_rare(name_en):
                        return "RR"
            # Any era: trust Cardrush RR against Pokéllector UR.
            if mapped == "UR" and cardrush and cardrush.rarity_code == "RR":
                return "RR"
            return mapped
    if tcgdex and tcgdex.rarity_raw:
        mapped = canonicalize_tcgdex(tcgdex.rarity_raw)
        if mapped:
            return mapped
    if cardrush and cardrush.rarity_code:
        return cardrush.rarity_code
    return None


def _merge_one(
    *,
    set_code: str,
    era_block: str | None,
    stub: PokellectorCardStub,
    pokel_detail: PokellectorCardDetail | None,
    tcgdex: TcgdexCardMeta | None,
    cardrush: CardrushCardHints | None,
) -> CardYamlPayload:
    padded = pad_local_id(stub.local_id)

    name_ja = (tcgdex.name_ja if tcgdex else None) or _strip_variant_suffix_ja(
        cardrush.name_ja if cardrush else None
    )
    name_en = stub.name_en

    rarity_code = _choose_rarity(
        era_block=era_block,
        name_en=name_en,
        pokellector=pokel_detail,
        tcgdex=tcgdex,
        cardrush=cardrush,
    )

    category = _infer_category(tcgdex=tcgdex, name_ja=name_ja, name_en=name_en)

    variants = {DEFAULT_VARIANT}
    if cardrush and cardrush.variants:
        variants |= cardrush.variants
    prints = [DEFAULT_VARIANT] + sorted(v for v in variants if v != DEFAULT_VARIANT)

    sources: dict[str, Any] = {
        "pokellector": {
            "id": stub.pokellector_id,
            "series_id": stub.series_id,
            "slug": stub.slug,
            "rarity_raw": (pokel_detail.rarity_raw if pokel_detail else None),
        }
    }
    if tcgdex:
        sources["tcgdex"] = {
            "id": f"{stub.local_id}",
            "rarity_raw": tcgdex.rarity_raw,
        }
    if cardrush and (
        cardrush.name_ja
        or cardrush.variants - {DEFAULT_VARIANT}
        or cardrush.rarity_code is not None
    ):
        sources["cardrush"] = {
            "name_ja": cardrush.name_ja,
            "variants_seen": sorted(cardrush.variants),
            "rarity_code": cardrush.rarity_code,
        }

    return CardYamlPayload(
        set_code=set_code,
        local_id=padded,
        name_ja=name_ja,
        name_en=name_en,
        rarity_code=rarity_code,
        category=category,
        image=card_image_url(stub),
        illustrator=(tcgdex.illustrator if tcgdex else None),
        prints=prints,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@dataclass
class BootstrapSetResult:
    set_code: str
    cards_total: int
    yml_written: int
    yml_unchanged: int
    yml_skipped_manual: int

    def summary(self) -> dict[str, Any]:
        return {
            "set_code": self.set_code,
            "cards_total": self.cards_total,
            "yml_written": self.yml_written,
            "yml_unchanged": self.yml_unchanged,
            "yml_skipped_manual": self.yml_skipped_manual,
        }


async def bootstrap_set(
    set_code: str,
    *,
    run_id: int | None = None,
    cardrush_rarities: list[str] | None = None,
    cardrush_max_pages: int = 15,
    with_cardrush: bool = True,
    with_tcgdex: bool = True,
) -> BootstrapSetResult:
    """Fetch + merge + emit one set's per-card YMLs."""
    observed_at = datetime.now(UTC)

    async with async_session_factory() as session:
        ctx = await _load_set_ctx(session, set_code)
        if run_id is None:
            run_id = await start_scrape_run(
                session,
                "catalog.bootstrap",
                metadata={"set_code": ctx.set_code},
            )

    if not ctx.pokellector_slug:
        raise RuntimeError(
            f"Set {ctx.set_code} has no pokellector_slug in sets YML"
        )

    # --- 1. Pokellector --------------------------------------------------
    async with PokellectorClient() as pc:
        pokel_index, pokel_details = await fetch_full_set(
            pc,
            set_code=ctx.set_code,
            set_slug=ctx.pokellector_slug,
            run_id=run_id,
            observed_at=observed_at,
        )

    logger.info(
        "pokellector %s: indexed %d cards, detailed %d",
        ctx.set_code,
        len(pokel_index.cards),
        len(pokel_details),
    )

    # --- 2. TCGdex (optional) -------------------------------------------
    tcgdex_by_id: dict[str, TcgdexCardMeta] = {}
    if with_tcgdex:
        try:
            tcgdex_by_id = await _fetch_tcgdex_set(ctx.tcgdex_id)
            logger.info(
                "tcgdex %s: %d entries", ctx.tcgdex_id, len(tcgdex_by_id)
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("tcgdex fetch failed for %s: %s", ctx.tcgdex_id, exc)

    # --- 3. Cardrush (optional) -----------------------------------------
    cardrush_hints: dict[str, CardrushCardHints] = {}
    if with_cardrush:
        rarities = cardrush_rarities or _DEFAULT_DISCOVERY_RARITIES
        cardrush_hints = await _fetch_cardrush_variants(
            ctx.set_code, rarities=rarities, max_pages=cardrush_max_pages
        )
        logger.info(
            "cardrush %s: variant hints for %d cards", ctx.set_code, len(cardrush_hints)
        )

    # --- 4. Merge + emit -------------------------------------------------
    emit_result = EmitResult()
    for stub in pokel_index.cards:
        detail = pokel_details.get(stub.local_id)
        tcgdex = tcgdex_by_id.get(stub.local_id)
        padded = pad_local_id(stub.local_id)
        cardrush = cardrush_hints.get(padded)
        payload = _merge_one(
            set_code=ctx.set_code,
            era_block=ctx.era_block,
            stub=stub,
            pokel_detail=detail,
            tcgdex=tcgdex,
            cardrush=cardrush,
        )
        write_card_yaml(payload, emit_result)

    async with async_session_factory() as session:
        await finish_scrape_run(
            session,
            run_id=run_id,
            status="completed",
            cards_attempted=len(pokel_index.cards),
            cards_succeeded=len(pokel_index.cards),
            rows_written=emit_result.written,
        )

    return BootstrapSetResult(
        set_code=ctx.set_code,
        cards_total=len(pokel_index.cards),
        yml_written=emit_result.written,
        yml_unchanged=emit_result.unchanged,
        yml_skipped_manual=emit_result.skipped_manual,
    )


async def run(
    sets: list[str],
    *,
    no_fetch: bool = False,
) -> list[dict[str, Any]]:
    """CLI entrypoint: bootstrap every requested set."""
    if no_fetch:
        raise NotImplementedError(
            "--no-fetch (rebuild from bronze) is not implemented yet; "
            "run without the flag to fetch fresh data."
        )

    summaries: list[dict[str, Any]] = []
    for set_code in sets:
        logger.info("=== bootstrap set %s ===", set_code)
        result = await bootstrap_set(set_code)
        summaries.append(result.summary())
        logger.info(
            "%s: total=%d written=%d unchanged=%d skipped_manual=%d",
            result.set_code,
            result.cards_total,
            result.yml_written,
            result.yml_unchanged,
            result.yml_skipped_manual,
        )
    return summaries
