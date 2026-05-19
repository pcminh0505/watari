"""On-demand Snkrdunk price fetching with in-memory TTL cache.

Cardrush prices are read from the DB (mv_* materialized views) via SessionDep;
this module handles only on-demand Snkrdunk fetches for card-detail endpoints.

Concurrent requests for the same card are coalesced via per-key asyncio locks
so the upstream is not hit more than once per TTL window.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from watari_core.catalog import make_card_id, pad_local_id
from watari_snkrdunk.client import SnkrdunkClient
from watari_snkrdunk.parser import parse_sales_history
from watari_snkrdunk.run import _SNKRDUNK_ERA_SLUG_OVERRIDE

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(minutes=30)
_SNKRDUNK_7D = timedelta(days=7)
# Redis key TTL = cache TTL + small buffer so Redis auto-expires stale entries.
_REDIS_TTL_SEC = int(CACHE_TTL.total_seconds()) + 120


@dataclass
class _CacheEntry:
    data: Any
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _is_stale(entry: _CacheEntry) -> bool:
    return datetime.now(UTC) - entry.fetched_at >= CACHE_TTL


# Shape of Snkrdunk result:
# ungraded: {card_id, source, source_type, condition, price_jpy, observed_at, ...}
# graded:   {card_id, source, source_type, grade_company, grade_score, price_jpy, observed_at, ...}
SnkrdunkResult = tuple[list[dict[str, Any]], list[dict[str, Any]]]


# --- JSON serialization helpers (handle datetime round-trip) -----------------


def _serialize(data: Any) -> str:
    """Serialize to JSON, encoding datetime as ``{"__dt__": "<ISO>"}}``."""

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return {"__dt__": obj.isoformat()}
        raise TypeError(f"Not JSON serializable: {type(obj)!r}")

    return json.dumps(data, default=_default)


def _deserialize(raw: str | bytes) -> Any:
    """Deserialize JSON, converting ``{"__dt__": "..."}`` back to datetime."""

    def _hook(d: dict) -> Any:
        if "__dt__" in d and len(d) == 1:
            return datetime.fromisoformat(d["__dt__"])
        return d

    return json.loads(raw, object_hook=_hook)


class PriceProxy:
    """On-demand Snkrdunk price fetcher with per-card TTL cache (L1 memory + optional L2 Redis)."""

    def __init__(self, redis: Any | None = None) -> None:
        self._sd_cache: dict[str, _CacheEntry] = {}
        self._sd_locks: dict[str, asyncio.Lock] = {}
        self._redis = redis  # optional aioredis client; None = memory-only

    # --- Redis helpers -------------------------------------------------------

    async def _redis_get(self, key: str) -> _CacheEntry | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            payload = _deserialize(raw)
            fetched_at: datetime = payload["fetched_at"]
            entry = _CacheEntry(data=payload["data"], fetched_at=fetched_at)
            if _is_stale(entry):
                return None
            return entry
        except Exception:
            logger.debug("price_proxy: redis get failed for %s", key)
            return None

    async def _redis_set(self, key: str, entry: _CacheEntry) -> None:
        if self._redis is None:
            return
        try:
            payload = {"fetched_at": entry.fetched_at, "data": entry.data}
            await self._redis.set(key, _serialize(payload), ex=_REDIS_TTL_SEC)
        except Exception:
            logger.debug("price_proxy: redis set failed for %s", key)

    # --- core fetch ----------------------------------------------------------

    async def fetch_snkrdunk(self, set_code: str, local_id: str) -> SnkrdunkResult:
        """Return (ungraded, graded) Snkrdunk rows for a card."""
        key = _sd_key(set_code, local_id)

        # L1 hit
        entry = self._sd_cache.get(key)
        if entry and not _is_stale(entry):
            return entry.data

        lock = self._sd_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # L1 re-check (another coroutine may have fetched while we waited)
            entry = self._sd_cache.get(key)
            if entry and not _is_stale(entry):
                return entry.data

            # L2 (Redis)
            entry = await self._redis_get(key)
            if entry is not None:
                self._sd_cache[key] = entry
                return entry.data

            # Live fetch
            data = await _do_fetch_snkrdunk(set_code, pad_local_id(local_id))
            entry = _CacheEntry(data=data)
            self._sd_cache[key] = entry
            await self._redis_set(key, entry)
            return data

    # --- public API (Snkrdunk-only) ------------------------------------------

    async def snkrdunk_latest_prices(
        self, set_code: str, local_id: str, variant: str, card_id: str
    ) -> list[dict[str, Any]]:
        """Most recent Snkrdunk sale per condition (sold comps)."""
        sd_rows, _ = await self.fetch_snkrdunk(set_code, local_id)

        best_sd: dict[str, dict[str, Any]] = {}
        for row in sd_rows:
            cond = row.get("condition", "")
            existing = best_sd.get(cond)
            if existing is None or row["observed_at"] > existing["observed_at"]:
                best_sd[cond] = row

        return [
            {
                "card_id": card_id,
                "source": "snkrdunk",
                "condition": row["condition"],
                "price_jpy": row["price_jpy"],
                "stock_qty": None,
                "observed_at": row["observed_at"],
            }
            for row in best_sd.values()
        ]

    async def snkrdunk_market_price(
        self, set_code: str, local_id: str, variant: str, card_id: str
    ) -> int | None:
        """Snkrdunk 7-day median for condition 'A'. Returns None if insufficient data."""
        sd_rows, _ = await self.fetch_snkrdunk(set_code, local_id)

        cutoff = datetime.now(UTC) - _SNKRDUNK_7D
        sd_recent_a = [
            r["price_jpy"]
            for r in sd_rows
            if r.get("condition") == "A" and r["observed_at"] >= cutoff
        ]
        if sd_recent_a:
            return int(statistics.median(sd_recent_a))
        return None

    async def graded_prices(
        self, set_code: str, local_id: str, card_id: str
    ) -> list[dict[str, Any]]:
        """Most recent Snkrdunk graded price per (grade_company, grade_score)."""
        _, graded_rows = await self.fetch_snkrdunk(set_code, local_id)

        best: dict[tuple[str, float, str], dict[str, Any]] = {}
        for row in graded_rows:
            k = (row.get("grade_company", ""), float(row.get("grade_score", 0)), row.get("source", ""))
            existing = best.get(k)
            if existing is None or row["observed_at"] > existing["observed_at"]:
                best[k] = row

        return [
            {
                "grade_company": r.get("grade_company"),
                "grade_score": float(r.get("grade_score", 0)),
                "source": r.get("source"),
                "price_jpy": r["price_jpy"],
                "observed_at": r["observed_at"],
            }
            for r in best.values()
        ]

    async def graded_history(
        self,
        set_code: str,
        local_id: str,
        card_id: str,
        *,
        days: int = 365,
        company: str | None = None,
    ) -> list[dict[str, Any]]:
        """Snkrdunk graded price history, newest first."""
        _, graded_rows = await self.fetch_snkrdunk(set_code, local_id)

        cutoff = datetime.now(UTC) - timedelta(days=days)
        rows = [r for r in graded_rows if r["observed_at"] >= cutoff]
        if company is not None:
            rows = [r for r in rows if r.get("grade_company", "").upper() == company.upper()]

        rows.sort(key=lambda r: r["observed_at"], reverse=True)
        # Assign synthetic IDs (router will renumber after merging with DB rows)
        return [
            {
                "id": i + 1,
                "card_id": card_id,
                "source": r.get("source", "snkrdunk"),
                "source_type": r.get("source_type", "sold"),
                "grade_company": r.get("grade_company"),
                "grade_score": float(r.get("grade_score", 0)),
                "price_jpy": r["price_jpy"],
                "observed_at": r["observed_at"],
                "external_url": r.get("external_url"),
            }
            for i, r in enumerate(rows)
        ]

    async def snkrdunk_raw_history(
        self,
        set_code: str,
        local_id: str,
        card_id: str,
        *,
        days: int = 90,
        condition: str | None = None,
    ) -> list[dict[str, Any]]:
        """Snkrdunk ungraded price history, newest first. 90-day max."""
        sd_rows, _ = await self.fetch_snkrdunk(set_code, local_id)

        cutoff = datetime.now(UTC) - timedelta(days=days)
        rows = [r for r in sd_rows if r["observed_at"] >= cutoff]
        if condition is not None:
            rows = [r for r in rows if r.get("condition", "").upper() == condition.upper()]

        rows.sort(key=lambda r: r["observed_at"], reverse=True)
        return [
            {
                "id": i + 1,
                "card_id": card_id,
                "source": r.get("source", "snkrdunk"),
                "source_type": r.get("source_type", "sold"),
                "condition": r.get("condition", "A"),
                "price_jpy": r["price_jpy"],
                "stock_qty": None,
                "observed_at": r["observed_at"],
                "created_at": r["observed_at"],
                "external_url": r.get("external_url"),
                "scrape_run_id": None,
            }
            for i, r in enumerate(rows)
        ]


# --- internal helpers --------------------------------------------------------


def _sd_key(set_code: str, local_id: str) -> str:
    return f"sd:{set_code.upper()}/{pad_local_id(local_id)}"


async def _do_fetch_snkrdunk(set_code: str, local_id: str) -> SnkrdunkResult:
    sc = set_code.upper()
    era_slug = _SNKRDUNK_ERA_SLUG_OVERRIDE.get(sc, sc.lower())

    logger.info(
        "price_proxy: snkrdunk fetch set=%s local_id=%s era=%s", sc, local_id, era_slug
    )

    try:
        async with SnkrdunkClient() as client:
            apparel = await client.resolve_apparel(era_slug, local_id)
            if apparel is None:
                logger.debug("price_proxy: snkrdunk no apparel for %s/%s", sc, local_id)
                return [], []

            apparel_id: int = apparel["apparel_id"]
            # Cap at 500 entries (~5 pages × 100). Full history is not needed
            # for market price (7-day window) or the history chart (365-day
            # display). Without a limit, popular cards with 10k+ sales trigger
            # 100+ sequential HTTP pages and 25+ seconds of polite delays.
            entries, _ = await client.fetch_sales_history(apparel_id, limit=500)

        card_id = make_card_id(sc, local_id)
        ungraded, graded = parse_sales_history(
            entries,
            card_id=card_id,
            apparel_id=apparel_id,
            scrape_run_id=None,
        )
        logger.debug(
            "price_proxy: snkrdunk %s/%s → %d ungraded %d graded",
            sc, local_id, len(ungraded), len(graded),
        )
        return ungraded, graded
    except Exception:
        logger.exception("price_proxy: snkrdunk fetch failed for %s/%s", sc, local_id)
        return [], []
