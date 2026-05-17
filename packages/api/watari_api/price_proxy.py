"""On-demand price fetching from Cardrush and Snkrdunk with in-memory TTL cache.

Replaces the DB materialized-views for online mode. Each card's price data is
fetched live on first request and cached for ``CACHE_TTL`` (default 30 min).
Concurrent requests for the same card are coalesced via per-key asyncio locks
so the upstream is not hit more than once per TTL window.

Optional Redis L2 cache: set ``REDIS_URL`` in the environment to enable a
shared cache that survives process restarts and is shared across instances.
L1 (in-process dict) is always checked first; Redis is only consulted when L1
misses. Errors on Redis are swallowed so a Redis outage degrades gracefully to
memory-only mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from watari_cardrush.client import CardrushClient
from watari_cardrush.parser import ListingRow, parse_listing_rows
from watari_cardrush.run import _CARDRUSH_BASE_ALIAS, _CARDRUSH_PROMO_KEYWORD
from watari_core.catalog import make_artwork_id, make_card_id, pad_local_id
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


# Shape of a Cardrush price row returned by fetch_cardrush():
#   {variant, condition, price_jpy, stock_qty, external_url, observed_at, source}
CardrushRow = dict[str, Any]

# Shape of Snkrdunk price row returned by fetch_snkrdunk():
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
    """On-demand price fetcher with per-card TTL cache (L1 memory + optional L2 Redis)."""

    def __init__(self, redis: Any | None = None) -> None:
        self._cr_cache: dict[str, _CacheEntry] = {}
        self._sd_cache: dict[str, _CacheEntry] = {}
        self._cr_locks: dict[str, asyncio.Lock] = {}
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

    # --- public API ----------------------------------------------------------

    async def fetch_cardrush(self, set_code: str, local_id: str) -> list[CardrushRow]:
        """Return Cardrush listing rows for a card, from cache or live fetch."""
        key = _cr_key(set_code, local_id)

        # L1 hit
        entry = self._cr_cache.get(key)
        if entry and not _is_stale(entry):
            return entry.data

        lock = self._cr_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # L1 re-check (another coroutine may have fetched while we waited)
            entry = self._cr_cache.get(key)
            if entry and not _is_stale(entry):
                return entry.data

            # L2 (Redis)
            entry = await self._redis_get(key)
            if entry is not None:
                self._cr_cache[key] = entry
                return entry.data

            # Live fetch
            data = await _do_fetch_cardrush(set_code, pad_local_id(local_id))
            entry = _CacheEntry(data=data)
            self._cr_cache[key] = entry
            await self._redis_set(key, entry)
            return data

    async def fetch_snkrdunk(self, set_code: str, local_id: str) -> SnkrdunkResult:
        """Return (ungraded, graded) Snkrdunk rows for a card."""
        key = _sd_key(set_code, local_id)

        # L1 hit
        entry = self._sd_cache.get(key)
        if entry and not _is_stale(entry):
            return entry.data

        lock = self._sd_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # L1 re-check
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

    # --- derived aggregates used by price endpoints --------------------------

    async def latest_prices(
        self, set_code: str, local_id: str, variant: str, card_id: str
    ) -> list[dict[str, Any]]:
        """Merge Cardrush listings + most recent Snkrdunk sale per condition.

        Returns list of LatestPrice-compatible dicts for the requested variant.
        """
        cr_rows, (sd_rows, _) = await asyncio.gather(
            self.fetch_cardrush(set_code, local_id),
            self.fetch_snkrdunk(set_code, local_id),
        )

        results: list[dict[str, Any]] = []

        # Cardrush: all listings for this variant (condition = current listing)
        for row in cr_rows:
            if row.get("variant") != variant:
                continue
            results.append(
                {
                    "card_id": card_id,
                    "source": "cardrush",
                    "condition": row["condition"],
                    "price_jpy": row["price_jpy"],
                    "stock_qty": row.get("stock_qty"),
                    "observed_at": row["observed_at"],
                }
            )

        # Snkrdunk: most recent sale per condition (sold comps, not listings)
        # SNKRDUNK apparel_id is per-card not per-variant; apply to all variants.
        best_sd: dict[str, dict[str, Any]] = {}
        for row in sd_rows:
            cond = row.get("condition", "")
            existing = best_sd.get(cond)
            if existing is None or row["observed_at"] > existing["observed_at"]:
                best_sd[cond] = row

        for row in best_sd.values():
            results.append(
                {
                    "card_id": card_id,
                    "source": "snkrdunk",
                    "condition": row["condition"],
                    "price_jpy": row["price_jpy"],
                    "stock_qty": None,
                    "observed_at": row["observed_at"],
                }
            )

        return results

    async def market_price(
        self, set_code: str, local_id: str, variant: str, card_id: str
    ) -> dict[str, Any] | None:
        """Compute market price: Snkrdunk 7d median preferred, Cardrush floor fallback."""
        cr_rows, (sd_rows, _) = await asyncio.gather(
            self.fetch_cardrush(set_code, local_id),
            self.fetch_snkrdunk(set_code, local_id),
        )

        cutoff = datetime.now(UTC) - _SNKRDUNK_7D
        sd_recent_a = [
            r["price_jpy"]
            for r in sd_rows
            if r.get("condition") == "A" and r["observed_at"] >= cutoff
        ]
        if sd_recent_a:
            median = int(statistics.median(sd_recent_a))
            return {"card_id": card_id, "market_price_jpy": median, "source_used": "snkrdunk"}

        # Cardrush condition-A floor (in-stock listings for this variant)
        cr_a = [
            r["price_jpy"]
            for r in cr_rows
            if r.get("variant") == variant
            and r.get("condition") == "A"
            and (r.get("stock_qty") or 0) > 0
        ]
        if cr_a:
            return {
                "card_id": card_id,
                "market_price_jpy": min(cr_a),
                "source_used": "cardrush",
            }

        return None

    async def spread(
        self, set_code: str, local_id: str, variant: str, card_id: str
    ) -> list[dict[str, Any]]:
        """Compute CR-floor vs SD-7d-median spread for condition 'A'."""
        cr_rows, (sd_rows, _) = await asyncio.gather(
            self.fetch_cardrush(set_code, local_id),
            self.fetch_snkrdunk(set_code, local_id),
        )

        cr_a = [
            r["price_jpy"]
            for r in cr_rows
            if r.get("variant") == variant and r.get("condition") == "A"
        ]
        cutoff = datetime.now(UTC) - _SNKRDUNK_7D
        sd_7d_a = [
            r["price_jpy"]
            for r in sd_rows
            if r.get("condition") == "A" and r["observed_at"] >= cutoff
        ]

        if not cr_a or not sd_7d_a:
            return []

        cr_floor = float(min(cr_a))
        sd_median = statistics.median(sd_7d_a)
        spread_jpy = sd_median - cr_floor
        spread_pct = (spread_jpy / cr_floor * 100) if cr_floor else None

        return [
            {
                "card_id": card_id,
                "condition": "A",
                "cardrush_floor": int(cr_floor),
                "snkrdunk_median_7d": sd_median,
                "spread_jpy": spread_jpy,
                "spread_pct": spread_pct,
            }
        ]

    async def graded_prices(
        self, set_code: str, local_id: str, card_id: str
    ) -> list[dict[str, Any]]:
        """Most recent graded price per (grade_company, grade_score, source)."""
        _, (_, graded_rows) = await asyncio.gather(
            self.fetch_cardrush(set_code, local_id),
            self.fetch_snkrdunk(set_code, local_id),
        )

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
        """Graded price history from Snkrdunk, newest first."""
        _, (_, graded_rows) = await asyncio.gather(
            self.fetch_cardrush(set_code, local_id),
            self.fetch_snkrdunk(set_code, local_id),
        )

        cutoff = datetime.now(UTC) - timedelta(days=days)
        rows = [r for r in graded_rows if r["observed_at"] >= cutoff]
        if company is not None:
            rows = [r for r in rows if r.get("grade_company", "").upper() == company.upper()]

        rows.sort(key=lambda r: r["observed_at"], reverse=True)
        # Assign synthetic IDs (no DB auto-increment available)
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


# --- internal helpers --------------------------------------------------------


def _cr_key(set_code: str, local_id: str) -> str:
    return f"cr:{set_code.upper()}/{pad_local_id(local_id)}"


def _sd_key(set_code: str, local_id: str) -> str:
    return f"sd:{set_code.upper()}/{pad_local_id(local_id)}"


async def _do_fetch_cardrush(set_code: str, local_id: str) -> list[CardrushRow]:
    sc = set_code.upper()

    if sc in _CARDRUSH_PROMO_KEYWORD:
        promo_suffix = _CARDRUSH_PROMO_KEYWORD[sc]
        keyword = f"{promo_suffix} {local_id}"
    else:
        base = _CARDRUSH_BASE_ALIAS.get(sc, sc)
        keyword = f"{base} {local_id}"

    logger.info("price_proxy: cardrush fetch set=%s local_id=%s keyword=%r", sc, local_id, keyword)
    rows: list[CardrushRow] = []
    now = datetime.now(UTC)

    try:
        async with CardrushClient() as client:
            # max_pages=1: a specific card ID fits on one result page. The
            # multi-page loop was designed for broad rarity-bucket scrapes; for
            # per-card online mode fetches it just adds a wasted HTTP round-trip
            # plus 0.3–0.8 s jitter before discovering the second page is empty.
            pages = await client.paginate(keyword, max_pages=1)

        for _, _, html in pages:
            ungraded, _ = parse_listing_rows(html)
            for row in ungraded:
                if not _cr_matches(row, sc, local_id):
                    continue
                rows.append(
                    {
                        "variant": row.variant,
                        "condition": row.condition.value,
                        "price_jpy": row.price_jpy,
                        "stock_qty": row.stock_qty,
                        "external_url": row.external_url,
                        "observed_at": now,
                        "source": "cardrush",
                    }
                )
    except Exception:
        logger.exception("price_proxy: cardrush fetch failed for %s/%s", sc, local_id)

    logger.debug("price_proxy: cardrush %s/%s → %d listings", sc, local_id, len(rows))
    return rows


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

        artwork_id = make_artwork_id(sc, local_id)
        card_id = make_card_id(artwork_id, "normal")
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


def _cr_matches(row: ListingRow, set_code: str, local_id: str) -> bool:
    """Check whether a Cardrush listing belongs to the requested card."""
    if row.local_id_padded is None or row.local_id_padded != local_id:
        return False
    if row.set_code is None:
        return False
    row_sc = row.set_code.upper()
    if row_sc == set_code:
        return True
    # Aliased sets (e.g. S1W/S1H both appear as "S1" in product names)
    base = _CARDRUSH_BASE_ALIAS.get(set_code)
    if base and row_sc == base:
        return True
    # Promo sets: already filtered by keyword, so any matching local_id is fine
    if set_code in _CARDRUSH_PROMO_KEYWORD:
        return True
    return False
