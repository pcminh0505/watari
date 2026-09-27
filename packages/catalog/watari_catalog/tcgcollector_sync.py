"""Sync JP sets that exist on TCGCollector but not in ``data/sets/``.

Source page: https://www.tcgcollector.com/sets/jp (every JP set, grouped by
era, with code / release date / card count / symbol / logo).

For each TCGCollector set whose numeric id is not yet referenced by any
``data/sets/*.yml`` (``tcgcollector_id``), this module:

1. assigns a unique, hyphen-free ``set_code`` (see ``assign_set_codes``),
2. writes ``data/sets/<CODE>.yml`` (era, names, release date, official
   total, TCGdex id when known, TCGCollector id/slug/code, logo + symbol),
3. writes ``data/cards/<CODE>/<local_id>.yml`` for every card, using two
   pages per set: the list view (number, English name, rarity, card type)
   and the image view (card image). TCGdex JP — when the set is indexed
   there — adds ``name_ja``, ``illustrator`` and ``category``.

Only two requests per set, so the whole JP catalogue (~350 sets, ~16k
cards) syncs in well under an hour. Per-card detail pages (illustrator for
sets TCGdex doesn't cover) are left to ``audit-fetch``.

Existing sets are never modified: codes are assigned once and persisted in
the YAML, and re-runs skip every TCGCollector id that is already mapped.
Card YMLs honour ``# manual: true`` via ``emit_yml.write_card_yaml``.
"""

from __future__ import annotations

import logging
import pathlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import yaml
from bs4 import BeautifulSoup, Tag

from watari_catalog.bootstrap import TcgdexCardMeta, _fetch_tcgdex_set
from watari_catalog.emit_yml import CardYamlPayload, EmitResult, write_card_yaml
from watari_catalog.paths import sets_dir
from watari_catalog.rarities import canonicalize_tcgcollector, canonicalize_tcgdex
from watari_catalog.tcgcollector_client import SOURCE, TcgCollectorClient, _best_image
from watari_catalog.tcgdex_client import TcgdexClient
from watari_catalog.variants import DEFAULT_VARIANT

logger = logging.getLogger(__name__)

SETS_LIST_PATH = (
    "/sets/jp?cardCountMode=anyCardVariant&releaseDateOrder=newToOld&displayAs=images"
)

# TCGCollector era heading → our ``era_block``. The four modern eras reuse
# the existing blocks; everything older gets its own block so the sets
# page can filter by it.
ERA_BLOCKS: dict[str, str] = {
    "Mega Evolution Era": "me",
    "Scarlet & Violet Era": "sv",
    "Sword & Shield Era": "sw",
    "Sun & Moon Era": "sm",
    "XY Era": "xy",
    "Black & White Era": "bw",
    "LEGEND Era": "legend",
    "Platinum Era": "pt",
    "Diamond & Pearl Era": "dp",
    "PCG Era": "pcg",
    "ADV Era": "adv",
    "Web Era": "web",
    "VS Era": "vs",
    "e-Card Era": "e",
    "Neo Era": "neo",
    "Original Era": "original",
    "Vending Machine Series": "vending",
    "Movie Commemorations": "movie",
    "Unnumbered Energies": "energy",
    "Other": "other",
}

# Prefix for generated codes (sets with no TCGCollector code and no TCGdex id).
CODE_PREFIX: dict[str, str] = {
    "me": "M",
    "sv": "SV",
    "sw": "S",
    "sm": "SM",
    "xy": "XY",
    "bw": "BW",
    "legend": "L",
    "pt": "PT",
    "dp": "DP",
    "pcg": "PCG",
    "adv": "ADV",
    "web": "WEB",
    "vs": "VS",
    "e": "EC",  # not "E": "EX01" would read as "ex"
    "neo": "NEO",
    "original": "OR",
    "vending": "VM",
    "movie": "MV",
    "energy": "EN",
    "other": "OT",
}

# TCGCollector set id → TCGdex JP set id, for sets whose TCGCollector code
# doesn't equal the TCGdex id (or that have no code at all). Built by
# matching era + card count + name and reviewed by hand; the legacy eras are
# closed, so this table only grows when TCGdex indexes another old set.
# Sets whose normalized TCGCollector code equals a TCGdex id (CP1, XY2, M6a,
# SVLN, …) are matched automatically and don't need an entry.
TCGDEX_ID_BY_TCGCOLLECTOR_ID: dict[str, str] = {
    # Original era
    "11182": "PMCG1",  # Expansion Pack / 拡張パック
    "11201": "PMCG2",  # Pokémon Jungle
    "11172": "PMCG3",  # Mystery of the Fossils
    "11249": "PMCG4",  # Team Rocket
    "11242": "PMCG5",  # Leaders' Stadium
    "11302": "PMCG6",  # Challenge from the Darkness
    # Neo / VS / web
    "11290": "neo1",  # Gold, Silver, to a New World...
    "11266": "neo2",  # Crossing the Ruins...
    "11173": "neo3",  # Awakening Legends
    "11252": "neo4",  # Darkness, and to Light...
    "11283": "VS1",  # Pokémon VS
    "11168": "web1",  # Pokémon Web
    # e-Card
    "11205": "E1",  # Base Expansion Pack
    "11218": "E2",  # The Town on No Map
    "11227": "E3",  # Wind from the Sea
    "11188": "E4",  # Split Earth
    "11183": "E5",  # Mysterious Mountains
    # ADV
    "11165": "ADV1",  # ADV Expansion Pack
    "11222": "ADV2",  # Miracle of the Desert
    "11281": "ADV3",  # Rulers of the Heavens
    "11233": "ADV4",  # Magma vs Aqua: Two Ambitions
    "11248": "ADV5",  # Undone Seal
    # PCG
    "11225": "PCG1",  # Flight of Legends
    "11181": "PCG2",  # Clash of the Blue Sky
    "11179": "PCG3",  # Team Rocket Strikes Back
    "11193": "PCG4",  # Golden Sky, Silvery Ocean
    "11254": "PCG5",  # Mirage Forest
    "11186": "PCG6",  # Holon Research Tower
    "11299": "PCG7",  # Holon Phantom
    "11278": "PCG8",  # Miracle Crystal
    "11295": "PCG9",  # Offense and Defense of the Furthest Ends
    "11271": "PCG10",  # World Champions Pack
    # LEGEND
    "11259": "L1a",  # HeartGold Collection
    "11300": "L1b",  # SoulSilver Collection
    "11226": "L2",  # Reviving Legends (TCGCollector code L2 is shared by 2 decks)
    # XY
    "11258": "XY1a",  # Collection X
    "11228": "XY1b",  # Collection Y
    "11174": "XY5a",  # Gaia Volcano
    "11197": "XY5b",  # Tidal Storm
    "11236": "XY8a",  # Blue Shock
    "11241": "XY8b",  # Red Flash
    "11195": "XY11a",  # Fever-Burst Fighter
    "11257": "XY11b",  # Cruel Traitor
}

_DATE_FORMAT = "%b %d, %Y"  # "Jul 31, 2026"
_NUMBER_RE = re.compile(r"^(?:No\.\s*)?([A-Za-z0-9]+)(?:\s*/\s*(.+))?$")


@dataclass(frozen=True)
class TcgCollectorSet:
    """One row of the TCGCollector JP set list."""

    tcgcollector_id: str
    slug: str
    name_en: str
    code: str | None          # TCGCollector's own code, verbatim ("S8a-G")
    era_block: str
    release_date: date | None
    card_count: int | None
    logo_url: str | None
    symbol_url: str | None


@dataclass(frozen=True)
class TcgCollectorListCard:
    """One card row from a set page in list view."""

    card_id: str
    number_raw: str           # "001/103", "No. 001", "R/RGB"
    local_id: str             # "001", "1234", "R"
    denominator: str | None   # "103", "SV-P", None for "No. NNN"
    name_en: str
    rarity_raw: str | None
    card_type: str | None     # "Grass", "Trainer", "Energy", …


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el is not None else ""


def _none_if_dash(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return None if stripped in ("", "—", "-", "–") else stripped


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), _DATE_FORMAT).date()
    except ValueError:
        return None


def parse_sets_page(html: str) -> list[TcgCollectorSet]:
    """Parse the JP set list (image view): one entry per set, in page order.

    The era comes from the nearest preceding ``<h2>`` heading.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[TcgCollectorSet] = []
    heading: str | None = None
    for el in soup.find_all(["h2", "div"]):
        if el.name == "h2":
            heading = _text(el)
            continue
        classes = el.get("class") or []
        if "set-logo-grid-item" not in classes or not el.get("data-set-id"):
            continue
        era_block = ERA_BLOCKS.get(heading or "")
        if era_block is None:
            # Fail loudly: silently skipping would drop a whole era, and a
            # guessed era_block would be persisted into every set YML.
            raise ValueError(
                f"sets under unknown TCGCollector era heading {heading!r} — "
                "add it to ERA_BLOCKS and CODE_PREFIX (and ERA_OPTIONS in apps/web)"
            )
        link = el.select_one("a.set-logo-grid-item-name")
        href = str(link.get("href") or "") if link else ""
        m = re.match(r"^/sets/(\d+)/([^?]+)", href)
        if not m:
            continue
        progress = _text(el.select_one(".progress-label"))
        count = progress.split("/")[-1] if "/" in progress else ""
        out.append(
            TcgCollectorSet(
                tcgcollector_id=m.group(1),
                slug=m.group(2),
                name_en=_text(link),
                code=_text(el.select_one(".set-logo-grid-item-code")) or None,
                era_block=era_block,
                release_date=_parse_date(_text(el.select_one(".set-logo-grid-item-release-date"))),
                card_count=int(count) if count.isdigit() else None,
                logo_url=_best_image(el.select_one("img.set-logo-grid-item-logo")),
                symbol_url=_best_image(el.select_one("img.set-logo-grid-item-symbol")),
            )
        )
    return out


def local_id_from_number(number_raw: str) -> tuple[str, str | None]:
    """``"001/103"`` → ``("001", "103")``; ``"No. 7"`` → ``("007", None)``.

    Non-numeric numbers keep their (uppercased) alphanumerics: ``"R/RGB"`` →
    ``("R", "RGB")``. Raises ``ValueError`` on anything else.
    """
    m = _NUMBER_RE.match(number_raw.strip())
    if not m:
        raise ValueError(f"unparseable card number {number_raw!r}")
    head, denominator = m.group(1), m.group(2)
    local_id = head.zfill(3) if head.isdigit() else head.upper()
    return local_id, (denominator.strip() if denominator else None)


def parse_set_card_list(html: str) -> list[TcgCollectorListCard]:
    """Parse a set page rendered with ``displayAs=list``."""
    soup = BeautifulSoup(html, "lxml")
    out: list[TcgCollectorListCard] = []
    seen: set[str] = set()
    for row in soup.select(".card-list-item[data-card-id]"):
        card_id = str(row["data-card-id"])
        if card_id in seen:
            continue
        seen.add(card_id)
        number_raw = _text(row.select_one(".card-list-item-number-entry"))
        local_id, denominator = local_id_from_number(number_raw)

        rarity_el = row.select_one(".card-list-item-rarity-entry")
        rarity_img = rarity_el.select_one("img") if rarity_el else None
        rarity_raw = str(rarity_img.get("alt") or "") if rarity_img else _text(rarity_el)

        type_el = row.select_one(".card-list-item-card-type-entry")
        type_img = type_el.select_one("img") if type_el else None
        card_type = str(type_img.get("alt") or "") if type_img else _text(type_el)

        out.append(
            TcgCollectorListCard(
                card_id=card_id,
                number_raw=number_raw,
                local_id=local_id,
                denominator=denominator,
                name_en=_text(row.select_one(".card-list-item-name-entry")),
                rarity_raw=_none_if_dash(rarity_raw),
                card_type=_none_if_dash(card_type),
            )
        )
    return out


def parse_card_images(html: str) -> dict[str, str]:
    """``{card_id: image_url}`` from a set page rendered with ``displayAs=images``."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for link in soup.select(".card-image-grid-item a.card-image-grid-item-link"):
        m = re.match(r"^/cards/(\d+)/", str(link.get("href") or ""))
        if not m or m.group(1) in out:
            continue
        image = _best_image(link.select_one("img.card-image-grid-item-image"))
        if image:
            out[m.group(1)] = image
    return out


# ---------------------------------------------------------------------------
# Set codes + TCGdex ids
# ---------------------------------------------------------------------------


def normalize_code(code: str | None) -> str:
    """Uppercase, ``+`` → ``P`` (``SM1+`` → ``SM1P``), drop other non-alnum."""
    if not code:
        return ""
    return re.sub(r"[^A-Z0-9]", "", code.upper().replace("+", "P"))


def resolve_tcgdex_ids(
    missing: list[TcgCollectorSet],
    tcgdex_set_ids: set[str],
    used: set[str],
) -> dict[str, str]:
    """``{tcgcollector_id: tcgdex_id}`` via the curated table or an exact code match.

    ``tcgdex_set_ids`` are TCGdex JP ids verbatim (``"M6a"``, ``"PMCG1"``).
    Ids already claimed by an existing set (``used``, uppercased) are
    skipped, and a code shared by several TCGCollector sets is never
    auto-matched.
    """
    by_upper = {i.upper(): i for i in tcgdex_set_ids}
    code_counts = Counter(normalize_code(s.code) for s in missing if s.code)
    out: dict[str, str] = {}
    for s in missing:
        curated = TCGDEX_ID_BY_TCGCOLLECTOR_ID.get(s.tcgcollector_id)
        if curated:
            out[s.tcgcollector_id] = curated
            continue
        code = normalize_code(s.code)
        if not code or code_counts[code] > 1 or code in used:
            continue
        if code in by_upper:
            out[s.tcgcollector_id] = by_upper[code]
    return out


def assign_set_codes(
    missing: list[TcgCollectorSet],
    *,
    all_sets: list[TcgCollectorSet],
    existing_codes: set[str],
    tcgdex_ids: dict[str, str],
) -> dict[str, str]:
    """Return ``{tcgcollector_id: set_code}`` for every set in ``missing``.

    Rules, in order:

    1. The normalized TCGCollector code, when no other TCGCollector set
       normalizes to the same code and it isn't already one of our codes.
    2. The TCGdex JP id (normalized), when the set is on TCGdex.
    3. Otherwise a generated code — ``<code>`` plus a letter for a shared
       code (``SA`` ×5 → ``SAA``…``SAE``), or ``<era prefix>X<nn>`` for a set
       with no code at all (``ORX01``). Ordered by release date, then id.

    Generated codes skip anything already taken, so re-runs are stable:
    existing sets keep their persisted codes and new ones take the next
    free slot.
    """
    code_counts = Counter(normalize_code(s.code) for s in all_sets if s.code)
    taken = {c.upper() for c in existing_codes}
    out: dict[str, str] = {}

    ordered = sorted(missing, key=lambda s: (s.release_date or date.min, int(s.tcgcollector_id)))
    deferred: list[TcgCollectorSet] = []
    for s in ordered:
        code = normalize_code(s.code)
        if not (code and code_counts[code] == 1 and code not in taken):
            code = normalize_code(tcgdex_ids.get(s.tcgcollector_id))
        if code and code not in taken:
            taken.add(code)
            out[s.tcgcollector_id] = code
        else:
            deferred.append(s)

    for s in deferred:
        base = normalize_code(s.code)
        if base:
            candidates = [f"{base}{chr(c)}" for c in range(ord("A"), ord("Z") + 1)]
        else:
            candidates = [f"{CODE_PREFIX[s.era_block]}X{n:02d}" for n in range(1, 100)]
        code = next((c for c in candidates if c not in taken), None)
        if code is None:
            raise RuntimeError(f"no free set code for TCGCollector set {s.tcgcollector_id}")
        taken.add(code)
        out[s.tcgcollector_id] = code
    return out


# ---------------------------------------------------------------------------
# Card + set assembly
# ---------------------------------------------------------------------------


def category_from_card_type(card_type: str | None) -> str:
    if card_type == "Trainer":
        return "trainer"
    if card_type == "Energy":
        return "energy"
    return "card"


def official_total(cards: list[TcgCollectorListCard]) -> int | None:
    """Most common numeric denominator, if at least half the cards carry one."""
    numeric = [c.denominator for c in cards if c.denominator and c.denominator.isdigit()]
    if not numeric or len(numeric) * 2 < len(cards):
        return None
    return int(Counter(numeric).most_common(1)[0][0])


def dedupe_local_ids(
    cards: list[TcgCollectorListCard],
) -> list[tuple[str, TcgCollectorListCard]]:
    """Pair each card with a unique local_id (``001``, ``001B``, ``001C``…)."""
    seen: Counter[str] = Counter()
    out: list[tuple[str, TcgCollectorListCard]] = []
    for card in cards:
        seen[card.local_id] += 1
        n = seen[card.local_id]
        local_id = card.local_id if n == 1 else f"{card.local_id}{chr(ord('A') + n - 1)}"
        if n > 1:
            logger.warning(
                "tcgcollector-sync: duplicate number %r (card %s) → local_id %s",
                card.number_raw,
                card.card_id,
                local_id,
            )
        out.append((local_id, card))
    return out


def tcgdex_lookup(meta: dict[str, TcgdexCardMeta], local_id: str) -> TcgdexCardMeta | None:
    """TCGdex keys are padded for some sets (``"001"``) and bare for others (``"1"``)."""
    if local_id in meta:
        return meta[local_id]
    return meta.get(str(int(local_id))) if local_id.isdigit() else None


def build_card_payload(
    *,
    set_code: str,
    local_id: str,
    card: TcgCollectorListCard,
    image_url: str | None,
    tcgdex: TcgdexCardMeta | None,
) -> CardYamlPayload:
    sources: dict[str, Any] = {
        "tcgcollector": {"id": card.card_id, "rarity_raw": card.rarity_raw},
    }
    if tcgdex is not None:
        sources["tcgdex"] = {"id": tcgdex.local_id, "rarity_raw": tcgdex.rarity_raw}
    category = (tcgdex.category if tcgdex else None) or category_from_card_type(card.card_type)
    return CardYamlPayload(
        set_code=set_code,
        local_id=local_id,
        name_ja=tcgdex.name_ja if tcgdex else None,
        name_en=card.name_en or None,
        rarity_code=canonicalize_tcgcollector(card.rarity_raw)
        or (canonicalize_tcgdex(tcgdex.rarity_raw) if tcgdex else None),
        category=category,
        image=image_url,
        illustrator=tcgdex.illustrator if tcgdex else None,
        prints=[DEFAULT_VARIANT],
        sources=sources,
    )


def set_yaml_text(
    s: TcgCollectorSet,
    *,
    set_code: str,
    name_ja: str | None,
    total: int | None,
    tcgdex_id: str | None,
) -> str:
    doc: dict[str, Any] = {
        "set_code": set_code,
        "era_block": s.era_block,
        "language": "jp",
        "name_ja": name_ja,
        "name_en": s.name_en,
        "release_date": s.release_date,
        "total": total,
        "tcgdex_id": tcgdex_id,
        "pokellector_slug": None,
        "tcgcollector_id": s.tcgcollector_id,
        "tcgcollector_slug": s.slug,
        "tcgcollector_code": s.code,
        "logo_url": s.logo_url,
        "symbol_url": s.symbol_url,
    }
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=200)
    # PyYAML writes ``key: null``; match the hand-written files' ``key:``.
    body = re.sub(r": null$", ":", body, flags=re.M)
    return (
        "# Japanese Pokémon TCG set entry. Edit with care: used by seed-sets.\n"
        "# Generated by `python -m watari_catalog tcgcollector-sync`.\n\n" + body
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_existing_sets() -> tuple[set[str], set[str], set[str]]:
    """Return ``(set_codes, tcgcollector_ids, tcgdex_ids_upper)`` from data/sets."""
    codes: set[str] = set()
    tcgc_ids: set[str] = set()
    tcgdex_ids: set[str] = set()
    for path in sorted(sets_dir().glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        codes.add(str(doc["set_code"]).upper())
        if doc.get("tcgcollector_id"):
            tcgc_ids.add(str(doc["tcgcollector_id"]))
        if doc.get("tcgdex_id"):
            tcgdex_ids.add(str(doc["tcgdex_id"]).upper())
    # A set's own code counts as claiming the TCGdex id of the same name
    # (M1L, M5, … have no tcgdex_id in YAML but are the TCGdex "M1L", "M5").
    return codes, tcgc_ids, tcgdex_ids | codes


class _PageSource:
    """TCGCollector page fetcher with an optional on-disk HTML cache."""

    def __init__(self, client: TcgCollectorClient, cache_dir: pathlib.Path | None) -> None:
        self._client = client
        self._cache_dir = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, path: str, cache_name: str) -> str:
        cached = self._cache_dir / cache_name if self._cache_dir else None
        if cached is not None and cached.exists():
            return cached.read_text(encoding="utf-8")
        html = await self._client.fetch_page(path)
        if cached is not None:
            cached.write_text(html, encoding="utf-8")
        await self._client._sleep_jitter()
        return html

    async def sets_list(self) -> str:
        return await self.get(SETS_LIST_PATH, "sets_jp_images.html")

    async def set_page(self, s: TcgCollectorSet, display: str) -> str:
        path = f"/sets/{s.tcgcollector_id}/{s.slug}?cardSetType=anyCardVariant&displayAs={display}"
        return await self.get(path, f"{s.tcgcollector_id}_{display}.html")

    def forget(self, s: TcgCollectorSet) -> None:
        """Drop a set's cached pages so the next run refetches them."""
        if self._cache_dir is None:
            return
        for display in ("list", "images"):
            (self._cache_dir / f"{s.tcgcollector_id}_{display}.html").unlink(missing_ok=True)


def _mirror_bronze(
    set_code: str, run_id: int, observed_at: datetime, name: str, html: str
) -> None:
    from watari_core.bronze import write_bronze_set

    write_bronze_set(
        source=SOURCE,
        set_code=set_code,
        run_id=run_id,
        observed_at=observed_at,
        payload=html,
        key_suffix=f"set-sync/{name}",
    )


async def _sync_one_set(
    s: TcgCollectorSet,
    *,
    set_code: str,
    pages: _PageSource,
    tcgdex_id: str | None,
    tcgdex_name: str | None,
    bronze: tuple[int, datetime] | None,
) -> EmitResult:
    list_html = await pages.set_page(s, "list")
    images_html = await pages.set_page(s, "images")
    if bronze is not None:
        run_id, observed_at = bronze
        _mirror_bronze(set_code, run_id, observed_at, f"{s.tcgcollector_id}-list.html", list_html)
        _mirror_bronze(
            set_code, run_id, observed_at, f"{s.tcgcollector_id}-images.html", images_html
        )
    cards = parse_set_card_list(list_html)
    images = parse_card_images(images_html)
    # Writing the set YML marks the set as synced for good, so an empty parse of
    # a set that should have cards (Cloudflare challenge served as 200, markup
    # change) must fail the set instead. SX01 genuinely lists no cards.
    if not cards and s.card_count:
        raise RuntimeError(
            f"{s.tcgcollector_id}: list page parsed to 0 cards, set list says {s.card_count}"
        )
    if s.card_count is not None and len(cards) != s.card_count:
        logger.warning(
            "tcgcollector-sync: %s parsed %d cards but the set list says %d",
            set_code,
            len(cards),
            s.card_count,
        )
    tcgdex_meta = await _fetch_tcgdex_set(tcgdex_id) if tcgdex_id else {}

    emit = EmitResult()
    for local_id, card in dedupe_local_ids(cards):
        payload = build_card_payload(
            set_code=set_code,
            local_id=local_id,
            card=card,
            image_url=images.get(card.card_id),
            tcgdex=tcgdex_lookup(tcgdex_meta, local_id),
        )
        write_card_yaml(payload, emit)
    (sets_dir() / f"{set_code}.yml").write_text(
        set_yaml_text(
            s,
            set_code=set_code,
            name_ja=tcgdex_name,
            total=official_total(cards),
            tcgdex_id=tcgdex_id,
        ),
        encoding="utf-8",
    )
    logger.info(
        "%s: %d cards (%d images, %d tcgdex) written=%d",
        set_code,
        len(cards),
        len(images),
        len(tcgdex_meta),
        emit.written,
    )
    return emit


async def run(
    *,
    dry_run: bool = False,
    cache_dir: pathlib.Path | None = None,
    only_ids: list[str] | None = None,
    with_tcgdex: bool = True,
    bronze: bool = True,
) -> int:
    """CLI entrypoint for ``tcgcollector-sync``. Returns a process exit code."""
    observed_at = datetime.now(UTC)
    existing_codes, mapped_ids, used_tcgdex = load_existing_sets()

    tcgdex_sets: dict[str, str] = {}  # {id: name_ja}
    if with_tcgdex:
        async with TcgdexClient(language="ja") as tc:
            tcgdex_sets = {str(s["id"]): s.get("name") for s in await tc.get_all_sets()}

    async with TcgCollectorClient() as client:
        pages = _PageSource(client, cache_dir)
        all_sets = parse_sets_page(await pages.sets_list())
        if not all_sets:
            logger.error("tcgcollector-sync: set list parsed to 0 sets — markup changed?")
            return 1
        missing = [s for s in all_sets if s.tcgcollector_id not in mapped_ids]
        if only_ids:
            missing = [s for s in missing if s.tcgcollector_id in set(only_ids)]

        tcgdex_ids = resolve_tcgdex_ids(missing, set(tcgdex_sets), used_tcgdex)
        codes = assign_set_codes(
            missing, all_sets=all_sets, existing_codes=existing_codes, tcgdex_ids=tcgdex_ids
        )
        logger.info(
            "tcgcollector-sync: %d TCGCollector sets, %d mapped, %d to add",
            len(all_sets),
            len(mapped_ids),
            len(missing),
        )
        for s in missing:
            logger.info(
                "  %-8s ← %-6s %-8s [%s] %s (tcgdex=%s)",
                codes[s.tcgcollector_id],
                s.tcgcollector_id,
                s.code or "-",
                s.era_block,
                s.name_en,
                tcgdex_ids.get(s.tcgcollector_id) or "-",
            )
        if dry_run:
            return 0

        totals = EmitResult()
        failed: list[str] = []
        for i, s in enumerate(missing, start=1):
            tcgdex_id = tcgdex_ids.get(s.tcgcollector_id)
            logger.info("[%d/%d] %s", i, len(missing), s.name_en)
            try:
                emit = await _sync_one_set(
                    s,
                    set_code=codes[s.tcgcollector_id],
                    pages=pages,
                    tcgdex_id=tcgdex_id,
                    tcgdex_name=tcgdex_sets.get(tcgdex_id) if tcgdex_id else None,
                    bronze=(int(observed_at.timestamp()), observed_at) if bronze else None,
                )
            except Exception:
                # The set YML is written last, so a failed set stays unmapped
                # and the next run retries it under the same code.
                logger.exception("tcgcollector-sync: %s failed", s.tcgcollector_id)
                pages.forget(s)
                failed.append(s.tcgcollector_id)
                continue
            totals.written += emit.written
            totals.unchanged += emit.unchanged
            totals.skipped_manual += emit.skipped_manual

    logger.info(
        "tcgcollector-sync: %d sets, cards written=%d unchanged=%d manual=%d, failed=%s",
        len(missing) - len(failed),
        totals.written,
        totals.unchanged,
        totals.skipped_manual,
        failed or "none",
    )
    return 1 if failed else 0
