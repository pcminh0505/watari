"""Per-set bootstrap: fetch → merge → emit ``data/cards/{SET}/*.yml``.

Sources (precedence for each field listed in the merge table below):

- Pokellector (primary): image URL, English name, card rarity (text label).
- TCGdex (fallback): Japanese name, illustrator, TCGdex-native rarity.
- Cardrush (variant list): which variant prints exist per local_id.
- **TCGCollector audit sidecar** (``data/audit/<SET>.yml``, optional):
  authoritative rarity/illustrator overrides surfaced by the Phase-2/5
  audit pipeline. When present, this layer corrects systematic
  Pokellector mistiers (e.g. all Pokellector "Secret Rare" labels in
  SV1S/SV1V/SV2D/SV2P) and fills in illustrator across ME-era / SM-era
  sets where TCGdex has nothing.

After a successful bootstrap, the resulting YML tree is the source of truth
for the catalog — no network access is needed to rebuild the DB.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from watari_core.catalog import pad_local_id
from watari_core.db import async_session_factory
from watari_core.ingestion import finish_scrape_run, start_scrape_run
from watari_core.models import Set

from watari_catalog.cardrush_client import CardrushClient, parse_listings_from_html
from watari_catalog.emit_yml import CardYamlPayload, EmitResult, write_card_yaml
from watari_catalog.parser import parse_cardrush_product_name
from watari_catalog.paths import audit_yaml_path
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
    canonicalize_tcgcollector,
    canonicalize_tcgdex,
)
from watari_catalog.tcgcollector_client import (
    TcgCollectorClient,
    fetch_full_set as fetch_full_set_tcgcollector,
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
    set_code: str                  # "SV2A"
    era_block: str | None          # sm | sv | sw | me | cl
    name_ja: str | None            # "ポケモンカード151"
    tcgdex_id: str | None          # "sv2a" or None for ME sets
    pokellector_slug: str | None   # "Pokemon-151-Expansion"
    tcgcollector_id: str | None    # "11598" (numeric, stored as str)
    tcgcollector_slug: str | None  # "pokemon-tcg-classic-venusaur"


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
    refs = source_refs or {}
    pokellector_slug = refs.get("pokellector_slug")
    tcgc = refs.get("tcgcollector") or {}
    tcgcollector_id = str(tcgc["id"]) if tcgc.get("id") else None
    tcgcollector_slug = tcgc.get("slug") or None
    return BootstrapSetCtx(
        set_code=set_code_db,
        era_block=era_block,
        name_ja=name_ja,
        tcgdex_id=tcgdex_id,
        pokellector_slug=pokellector_slug,
        tcgcollector_id=tcgcollector_id,
        tcgcollector_slug=tcgcollector_slug,
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
# TCGCollector audit sidecar
# ---------------------------------------------------------------------------


@dataclass
class TcgCollectorAuditMeta:
    """One card's row from ``data/audit/<SET>.yml``.

    Loaded by ``_load_tcgcollector_audit`` and consumed by ``_merge_one``
    (Phase 7) so re-running ``catalog-bootstrap`` after ``audit-apply``
    doesn't regress the chosen oracle values back to Pokellector.
    """

    local_id: str          # zero-padded ("001")
    name_en: str | None
    rarity_canon: str | None
    illustrator: str | None
    name_ja: str | None    # backfilled from `pokellector_jpn` block, if present


def _load_tcgcollector_audit(set_code: str) -> dict[str, TcgCollectorAuditMeta]:
    """Read ``data/audit/<SET>.yml`` and index by zero-padded local_id."""
    path: pathlib.Path = audit_yaml_path(set_code)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}

    # Optional Pokellector JPN backfill (Phase 4) keyed by local_id.
    jpn_block = raw.get("pokellector_jpn") or {}
    jpn_by_lid: dict[str, str] = {}
    for entry in jpn_block.get("cards") or []:
        lid = str(entry.get("local_id") or "").zfill(3)
        ja = entry.get("name_ja")
        if lid and ja:
            jpn_by_lid[lid] = ja

    out: dict[str, TcgCollectorAuditMeta] = {}
    for entry in raw.get("cards") or []:
        lid_raw = entry.get("local_id")
        if lid_raw is None:
            continue
        lid = str(lid_raw).zfill(3)
        out[lid] = TcgCollectorAuditMeta(
            local_id=lid,
            name_en=entry.get("name_en") or None,
            rarity_canon=entry.get("rarity_canon") or None,
            illustrator=entry.get("illustrator") or None,
            name_ja=jpn_by_lid.get(lid),
        )
    return out


# Pokellector raw rarity labels that we know are systematically too coarse
# (e.g. Pokellector lumps every shiny full-art into "Super Secret Rare"
# even though SV4A 320-336 are SSR while 290-319 are SAR). When the audit
# disagrees with one of these, the audit wins.
_POKELLECTOR_COARSE_LABELS: frozenset[str] = frozenset(
    {
        "Secret Rare",
        "Super Secret Rare",
    }
)


def _audit_overrides_pokellector(
    pokellector: PokellectorCardDetail | None,
    audit: TcgCollectorAuditMeta | None,
) -> bool:
    """Return True iff the audit's rarity should beat Pokellector's."""
    if not audit or not audit.rarity_canon:
        return False
    if pokellector is None:
        return True
    raw = (pokellector.rarity_raw or "").strip()
    return raw in _POKELLECTOR_COARSE_LABELS


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
    audit: TcgCollectorAuditMeta | None = None,
) -> str | None:
    """Pokellector wins when mappable; TCGdex fallback; else None.

    Cardrush is used only as a fallback when upstream labels are absent or
    unmappable (e.g. Pokellector "Secret Rare" in some SwSh sets).

    The TCGCollector audit (Phase 2) overrides Pokellector iff Pokellector's
    raw label is one of the known-coarse categories (``"Secret Rare"`` or
    ``"Super Secret Rare"``) — in that case the audit's specific rarity
    wins. This is the Phase-7 regression-proofing that prevents future
    bootstraps from un-doing the SV1S/SV1V/SV2D/SV2P style fixes.
    """
    if _audit_overrides_pokellector(pokellector, audit):
        # Safety: only override with codes we actually recognize.
        return audit.rarity_canon if audit else None  # type: ignore[union-attr]

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
    if audit and audit.rarity_canon:
        return audit.rarity_canon
    return None


def _merge_one(
    *,
    set_code: str,
    era_block: str | None,
    stub: PokellectorCardStub,
    pokel_detail: PokellectorCardDetail | None,
    tcgdex: TcgdexCardMeta | None,
    cardrush: CardrushCardHints | None,
    audit: TcgCollectorAuditMeta | None = None,
) -> CardYamlPayload:
    padded = pad_local_id(stub.local_id)

    # name_ja precedence: tcgdex → cardrush → audit-pokellector_jpn fallback.
    name_ja = (tcgdex.name_ja if tcgdex else None) or _strip_variant_suffix_ja(
        cardrush.name_ja if cardrush else None
    )
    if not name_ja and audit and audit.name_ja:
        name_ja = audit.name_ja

    name_en = stub.name_en

    rarity_code = _choose_rarity(
        era_block=era_block,
        name_en=name_en,
        pokellector=pokel_detail,
        tcgdex=tcgdex,
        cardrush=cardrush,
        audit=audit,
    )

    category = _infer_category(tcgdex=tcgdex, name_ja=name_ja, name_en=name_en)

    # illustrator precedence: tcgdex → tcgcollector audit (huge win for ME-era
    # and any SM/SW set where TCGdex has no illustrator).
    illustrator: str | None = tcgdex.illustrator if tcgdex else None
    if not illustrator and audit and audit.illustrator:
        illustrator = audit.illustrator

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
    if audit and (audit.rarity_canon or audit.illustrator or audit.name_ja):
        sources["tcgcollector"] = {
            "rarity_canon": audit.rarity_canon,
            "illustrator": audit.illustrator,
            "name_ja_via_pokellector_jpn": audit.name_ja,
        }

    return CardYamlPayload(
        set_code=set_code,
        local_id=padded,
        name_ja=name_ja,
        name_en=name_en,
        rarity_code=rarity_code,
        category=category,
        image=card_image_url(stub),
        illustrator=illustrator,
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

    # --- 3b. TCGCollector audit sidecar (Phase 7 regression-proofing) ----
    audit_by_id = _load_tcgcollector_audit(ctx.set_code)
    if audit_by_id:
        logger.info(
            "tcgcollector audit %s: %d cards (data/audit/%s.yml)",
            ctx.set_code,
            len(audit_by_id),
            ctx.set_code,
        )

    # --- 4. Merge + emit -------------------------------------------------
    emit_result = EmitResult()
    for stub in pokel_index.cards:
        detail = pokel_details.get(stub.local_id)
        tcgdex = tcgdex_by_id.get(stub.local_id)
        padded = pad_local_id(stub.local_id)
        cardrush = cardrush_hints.get(padded)
        audit = audit_by_id.get(padded)
        payload = _merge_one(
            set_code=ctx.set_code,
            era_block=ctx.era_block,
            stub=stub,
            pokel_detail=detail,
            tcgdex=tcgdex,
            cardrush=cardrush,
            audit=audit,
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


async def bootstrap_set_from_tcgcollector(
    set_code: str,
    *,
    run_id: int | None = None,
    with_tcgdex: bool = True,
    with_cardrush: bool = True,
    cardrush_rarities: list[str] | None = None,
    cardrush_max_pages: int = 15,
    detail_concurrency: int = 2,
    bronze: bool = True,
) -> BootstrapSetResult:
    """Fetch + merge + emit YMLs using TCGCollector as the primary card source.

    Used for sets not available on Pokellector (Classic sets CLF/CLL/CLK and
    promo series MP/SMPR/SP/SVP). Requires ``tcgcollector_id`` and
    ``tcgcollector_slug`` to be present in the set YML.

    Field precedence:
    - name_en / rarity / illustrator: TCGCollector
    - name_ja:                         TCGdex → Cardrush
    - category:                        TCGdex → keyword heuristic
    - variants:                        Cardrush (normal only by default)
    - image:                           None (not available from TCGCollector)
    """
    observed_at = datetime.now(UTC)

    async with async_session_factory() as session:
        ctx = await _load_set_ctx(session, set_code)
        if run_id is None:
            run_id = await start_scrape_run(
                session,
                "catalog.bootstrap",
                metadata={"set_code": ctx.set_code},
            )

    if not ctx.tcgcollector_id or not ctx.tcgcollector_slug:
        raise RuntimeError(
            f"Set {ctx.set_code} has no tcgcollector_id/tcgcollector_slug in sets YML"
        )

    # --- 1. TCGCollector (primary: card list + name_en + rarity + illustrator) --
    async with TcgCollectorClient() as tc:
        index_entries, details = await fetch_full_set_tcgcollector(
            tc,
            set_id=ctx.tcgcollector_id,
            slug=ctx.tcgcollector_slug,
            set_code=ctx.set_code,
            run_id=run_id,
            observed_at=observed_at,
            detail_concurrency=detail_concurrency,
            bronze=bronze,
        )

    logger.info(
        "tcgcollector %s: %d indexed, %d details",
        ctx.set_code,
        len(index_entries),
        len(details),
    )

    # --- 2. TCGdex (optional, for name_ja) ------------------------------------
    tcgdex_by_id: dict[str, TcgdexCardMeta] = {}
    if with_tcgdex and ctx.tcgdex_id:
        try:
            tcgdex_by_id = await _fetch_tcgdex_set(ctx.tcgdex_id)
            logger.info("tcgdex %s: %d entries", ctx.tcgdex_id, len(tcgdex_by_id))
        except Exception as exc:  # pragma: no cover
            logger.warning("tcgdex fetch failed for %s: %s", ctx.tcgdex_id, exc)

    # --- 3. Cardrush (optional, variant + name_ja hints) ----------------------
    cardrush_hints: dict[str, CardrushCardHints] = {}
    if with_cardrush:
        rarities = cardrush_rarities or _DEFAULT_DISCOVERY_RARITIES
        cardrush_hints = await _fetch_cardrush_variants(
            ctx.set_code, rarities=rarities, max_pages=cardrush_max_pages
        )
        logger.info(
            "cardrush %s: variant hints for %d cards", ctx.set_code, len(cardrush_hints)
        )

    # --- 4. Merge + emit -------------------------------------------------------
    emit_result = EmitResult()
    for entry in index_entries:
        padded = entry.local_id  # already zero-padded by parse_set_index
        detail = details.get(padded)

        # TCGdex keyed by non-padded local_id (e.g. "1", not "001")
        tcgdex = tcgdex_by_id.get(str(int(padded))) or tcgdex_by_id.get(padded)
        cardrush = cardrush_hints.get(padded)

        name_en = detail.name_en if detail else None
        rarity_raw = detail.rarity_raw if detail else None
        rarity_code = canonicalize_tcgcollector(rarity_raw) or (
            cardrush.rarity_code if cardrush else None
        )
        illustrator = (detail.illustrator if detail else None) or (
            tcgdex.illustrator if tcgdex else None
        )

        name_ja = (tcgdex.name_ja if tcgdex else None) or _strip_variant_suffix_ja(
            cardrush.name_ja if cardrush else None
        )

        category = _infer_category(tcgdex=tcgdex, name_ja=name_ja, name_en=name_en)

        variants: set[str] = {DEFAULT_VARIANT}
        if cardrush and cardrush.variants:
            variants |= cardrush.variants
        prints = [DEFAULT_VARIANT] + sorted(v for v in variants if v != DEFAULT_VARIANT)

        sources: dict[str, Any] = {
            "tcgcollector": {
                "id": entry.card_id,
                "rarity_raw": rarity_raw,
            }
        }
        if tcgdex:
            sources["tcgdex"] = {
                "id": str(int(padded)),
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

        payload = CardYamlPayload(
            set_code=ctx.set_code,
            local_id=padded,
            name_ja=name_ja,
            name_en=name_en,
            rarity_code=rarity_code,
            category=category,
            image=entry.image_url,  # extracted from TCGCollector grid tile
            illustrator=illustrator,
            prints=prints,
            sources=sources,
        )
        write_card_yaml(payload, emit_result)

    async with async_session_factory() as session:
        await finish_scrape_run(
            session,
            run_id=run_id,
            status="completed",
            cards_attempted=len(index_entries),
            cards_succeeded=len(index_entries),
            rows_written=emit_result.written,
        )

    return BootstrapSetResult(
        set_code=ctx.set_code,
        cards_total=len(index_entries),
        yml_written=emit_result.written,
        yml_unchanged=emit_result.unchanged,
        yml_skipped_manual=emit_result.skipped_manual,
    )


async def run(
    sets: list[str],
    *,
    no_fetch: bool = False,
    bronze: bool = True,
) -> list[dict[str, Any]]:
    """CLI entrypoint: bootstrap every requested set.

    Auto-routes to ``bootstrap_set_from_tcgcollector`` when the set has
    ``tcgcollector_id`` + ``tcgcollector_slug`` but no ``pokellector_slug``.
    """
    if no_fetch:
        raise NotImplementedError(
            "--no-fetch (rebuild from bronze) is not implemented yet; "
            "run without the flag to fetch fresh data."
        )

    summaries: list[dict[str, Any]] = []
    for set_code in sets:
        logger.info("=== bootstrap set %s ===", set_code)

        async with async_session_factory() as session:
            ctx = await _load_set_ctx(session, set_code)

        if ctx.pokellector_slug:
            result = await bootstrap_set(set_code)
        elif ctx.tcgcollector_id and ctx.tcgcollector_slug:
            result = await bootstrap_set_from_tcgcollector(set_code, bronze=bronze)
        else:
            raise RuntimeError(
                f"Set {set_code} has neither pokellector_slug nor "
                f"tcgcollector_id+tcgcollector_slug — cannot bootstrap. "
                f"Fill in data/sets/{set_code}.yml first."
            )

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
