"""Cardmarket EU prices for JP cards, served from memory.

Two inputs:

- ``data/cardmarket/<SET>.yml`` — generated ``local_id → idProduct`` maps
  (``python -m watari_catalog cardmarket-map``), loaded once at startup.
- Cardmarket's public daily price guide (``price_guide_6.json``, ~15 MB),
  downloaded by a background task and filtered to mapped products.

Lookups never do I/O. Until the first successful download they return None.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from watari_catalog.paths import cardmarket_dir
from watari_core.catalog import pad_local_id

from watari_api.schemas import EuPrice

logger = logging.getLogger(__name__)

PRICE_GUIDE_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
)
REFRESH_INTERVAL_SEC = 6 * 60 * 60
RETRY_INTERVAL_SEC = 15 * 60

# Product page filtered to Japanese (language=7) and Near Mint or better (minCondition=2).
_PRODUCT_URL = (
    "https://www.cardmarket.com/en/Pokemon/Products?idProduct={id}&language=7&minCondition=2"
)

CardKey = tuple[str, str]  # (SET_CODE, padded local_id)


def load_mappings(directory: Path) -> dict[CardKey, int]:
    """Read every ``<SET>.yml`` map in ``directory`` into one lookup dict.

    Cardmarket has one product per artwork, so an idProduct claimed by more
    than one card is a TCGdex data error; every card sharing it is dropped
    (we can't tell which one is right).
    """
    mapping: dict[CardKey, int] = {}
    if not directory.is_dir():
        return mapping
    for path in sorted(directory.glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        set_code = str(raw.get("set_code") or path.stem).upper()
        for local_id, pid in (raw.get("products") or {}).items():
            mapping[(set_code, pad_local_id(str(local_id)))] = int(pid)
    counts = Counter(mapping.values())
    ambiguous = sorted(key for key, pid in mapping.items() if counts[pid] > 1)
    if ambiguous:
        logger.warning(
            "cardmarket_guide: dropped %d cards sharing an idProduct: %s",
            len(ambiguous),
            ", ".join(f"{s}/{local}={mapping[(s, local)]}" for s, local in ambiguous),
        )
    return {key: pid for key, pid in mapping.items() if counts[pid] == 1}


def _eur(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _parse_created_at(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def build_eu_price(
    id_product: int, row: dict[str, Any], *, variant: str, guide_date: datetime
) -> EuPrice | None:
    """Pick base or reverse-holo fields for ``variant``; None if nothing usable."""
    mirror = variant != "normal"
    suffix = "-holo" if mirror else ""
    trend = _eur(row, f"trend{suffix}")
    avg7 = _eur(row, f"avg7{suffix}")
    avg30 = _eur(row, f"avg30{suffix}")
    headline = trend or avg30 or avg7
    if headline is None:
        return None
    return EuPrice(
        id_product=id_product,
        url=_PRODUCT_URL.format(id=id_product),
        price_eur=headline,
        trend_eur=trend,
        avg7_eur=avg7,
        avg30_eur=avg30,
        basis="mirror" if mirror else "normal",
        guide_date=guide_date,
    )


class CardmarketGuide:
    """Mapped Cardmarket price-guide rows, keyed by our (set_code, local_id)."""

    def __init__(self, mapping: dict[CardKey, int]) -> None:
        self._mapping = mapping
        self._rows: dict[int, dict[str, Any]] = {}
        self._guide_date: datetime | None = None

    @classmethod
    def load(cls) -> CardmarketGuide:
        mapping = load_mappings(cardmarket_dir())
        logger.info("cardmarket_guide: %d cards mapped to Cardmarket products", len(mapping))
        return cls(mapping)

    @property
    def ready(self) -> bool:
        """True once a price guide has been applied."""
        return self._guide_date is not None

    def apply_guide(self, payload: dict[str, Any]) -> int:
        """Swap in a downloaded price guide, keeping only mapped products."""
        wanted = set(self._mapping.values())
        rows = {
            row["idProduct"]: row
            for row in payload.get("priceGuides") or []
            if row.get("idProduct") in wanted
        }
        if self._mapping and not rows:
            raise ValueError(f"price guide matched none of {len(wanted)} mapped products")
        self._rows = rows
        self._guide_date = _parse_created_at(payload.get("createdAt"))
        return len(rows)

    def lookup(self, set_code: str, local_id: str, variant: str = "normal") -> EuPrice | None:
        if self._guide_date is None:
            return None
        pid = self._mapping.get((set_code.upper(), pad_local_id(local_id)))
        row = self._rows.get(pid) if pid is not None else None
        if pid is None or row is None:
            return None
        return build_eu_price(pid, row, variant=variant, guide_date=self._guide_date)

    async def refresh(self, client: httpx.AsyncClient) -> None:
        """Download the price guide and apply it. Raises on failure (old data stays)."""
        resp = await client.get(PRICE_GUIDE_URL)
        resp.raise_for_status()
        payload = await asyncio.to_thread(json.loads, resp.content)
        kept = self.apply_guide(payload)
        logger.info(
            "cardmarket_guide: price guide %s applied (%d mapped products)",
            payload.get("createdAt"),
            kept,
        )

    async def run_refresh_loop(
        self, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ) -> None:
        """Refresh forever: every 6 h after success, every 15 min after a failure."""
        if not self._mapping:
            logger.info("cardmarket_guide: no mapping files; EU prices disabled")
            return
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            while True:
                try:
                    await self.refresh(client)
                    delay = REFRESH_INTERVAL_SEC
                except Exception:
                    logger.warning(
                        "cardmarket_guide: refresh failed; keeping previous data", exc_info=True
                    )
                    delay = RETRY_INTERVAL_SEC
                await sleep(delay)
