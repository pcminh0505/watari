"""Build ``data/cardmarket/<SET>.yml``: local_id → Cardmarket idProduct.

TCGdex's JP card payload carries Cardmarket's product id under
``pricing.cardmarket.idProduct``. Cardmarket product names are not unique
within an expansion (SV2a has four "Mew ex" products), so this map is the
only reliable join between our catalog and Cardmarket's price guide.

Product ids are stable: by default only local_ids missing from the existing
file are fetched. ``--refresh`` re-fetches every card; a card whose fetch
yields nothing keeps its previous id.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from watari_catalog.paths import cardmarket_dir, cardmarket_yaml_path, cards_set_dir
from watari_catalog.seed_sets import load_sets_yaml
from watari_catalog.tcgdex_client import TcgdexClient

logger = logging.getLogger(__name__)

# Every entry in this file is a Pokémon single (idCategory 51).
PRODUCT_CATALOG_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_6.json"
)

# Sets without a YAML tcgdex_id whose TCGdex JP id differs from our set_code
# (our promo set_codes must stay hyphen-free; TCGdex's are hyphenated).
_TCGDEX_ID_OVERRIDE: dict[str, str] = {"SVP": "SV-P", "MP": "M-P"}

FetchId = Callable[[str], Awaitable[int | None]]


def resolve_tcgdex_id(set_code: str, tcgdex_id: str | None) -> str:
    """TCGdex JP set id: YAML value, else override, else set_code (ids are case-insensitive)."""
    code = set_code.upper()
    return tcgdex_id or _TCGDEX_ID_OVERRIDE.get(code, code)


def extract_id_product(card: dict[str, Any] | None) -> int | None:
    """``pricing.cardmarket.idProduct`` from a TCGdex card payload, if present."""
    if not card:
        return None
    cardmarket = (card.get("pricing") or {}).get("cardmarket") or {}
    pid = cardmarket.get("idProduct")
    return pid if isinstance(pid, int) and pid > 0 else None


def read_mapping(path: Path) -> dict[str, int]:
    """Existing ``products`` block of a map file, or ``{}`` if the file is absent."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): int(v) for k, v in (raw.get("products") or {}).items()}


def render_mapping(
    *,
    set_code: str,
    tcgdex_id: str,
    fetched_at: str,
    artworks: int,
    products: dict[str, int],
) -> str:
    doc = {
        "set_code": set_code,
        "source": "tcgdex",
        "tcgdex_id": tcgdex_id,
        "fetched_at": fetched_at,
        "totals": {"artworks": artworks, "mapped": len(products)},
        "products": {k: products[k] for k in sorted(products)},
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


async def build_products(
    local_ids: list[str],
    existing: dict[str, int],
    fetch_id: FetchId,
    valid_ids: set[int],
    *,
    refresh: bool = False,
    concurrency: int = 5,
) -> dict[str, int]:
    """Return the complete local_id → idProduct map for one set.

    Existing entries survive only if the card still exists and the id is still
    a known Cardmarket product. Fetch errors are logged and skipped.
    """
    wanted = set(local_ids)
    products = {k: v for k, v in existing.items() if k in wanted and v in valid_ids}
    todo = local_ids if refresh else [lid for lid in local_ids if lid not in products]
    sem = asyncio.Semaphore(concurrency)

    async def one(local_id: str) -> tuple[str, int | None]:
        async with sem:
            try:
                return local_id, await fetch_id(local_id)
            except Exception:
                logger.warning("cardmarket-map: fetch failed for %s", local_id, exc_info=True)
                return local_id, None

    for local_id, pid in await asyncio.gather(*(one(lid) for lid in todo)):
        if pid is None:
            continue
        if pid not in valid_ids:
            logger.warning(
                "cardmarket-map: idProduct %s for %s is not a known Pokémon single; dropped",
                pid,
                local_id,
            )
            continue
        products[local_id] = pid
    return products


async def fetch_valid_product_ids(client: httpx.AsyncClient) -> set[int]:
    """All Pokémon single idProducts from Cardmarket's public product catalog."""
    resp = await client.get(PRODUCT_CATALOG_URL)
    resp.raise_for_status()
    return {int(p["idProduct"]) for p in resp.json().get("products") or []}


def _local_ids(set_code: str) -> list[str]:
    return sorted(p.stem for p in cards_set_dir(set_code).glob("*.yml"))


async def run(*, sets: list[str] | None, refresh: bool = False, concurrency: int = 5) -> int:
    rows = load_sets_yaml()
    if sets:
        wanted = {s.upper() for s in sets}
        unknown = wanted - {r["set_code"] for r in rows}
        if unknown:
            logger.error("cardmarket-map: unknown set code(s): %s", ", ".join(sorted(unknown)))
            return 1
        rows = [r for r in rows if r["set_code"] in wanted]

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
            valid_ids = await fetch_valid_product_ids(http)
    except Exception:
        logger.exception("cardmarket-map: could not download Cardmarket product catalog")
        return 1
    logger.info("cardmarket-map: %d known Cardmarket Pokémon singles", len(valid_ids))

    cardmarket_dir().mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    async with TcgdexClient(language="ja", timeout_sec=15.0, request_delay_sec=0.0) as tcgdex:
        for row in rows:
            set_code = row["set_code"]
            local_ids = _local_ids(set_code)
            if not local_ids:
                logger.info("cardmarket-map: %s has no card YAMLs; skipped", set_code)
                continue
            tcgdex_id = resolve_tcgdex_id(set_code, row.get("tcgdex_id"))
            path = cardmarket_yaml_path(set_code)
            existing = read_mapping(path)

            async def fetch_id(local_id: str, _tid: str = tcgdex_id) -> int | None:
                return extract_id_product(await tcgdex.get_card(_tid, local_id))

            products = await build_products(
                local_ids, existing, fetch_id, valid_ids, refresh=refresh, concurrency=concurrency
            )
            if not products and not path.exists():
                logger.info(
                    "cardmarket-map: %s — no Cardmarket products via TCGdex %r; no file written",
                    set_code,
                    tcgdex_id,
                )
                continue
            if path.exists() and products == existing:
                logger.info("cardmarket-map: %s unchanged (%d mapped)", set_code, len(products))
                continue
            path.write_text(
                render_mapping(
                    set_code=set_code,
                    tcgdex_id=tcgdex_id,
                    fetched_at=fetched_at,
                    artworks=len(local_ids),
                    products=products,
                ),
                encoding="utf-8",
            )
            logger.info(
                "cardmarket-map: %s — %d/%d mapped → %s",
                set_code,
                len(products),
                len(local_ids),
                path,
            )
    return 0
