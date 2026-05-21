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
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import httpx
from watari_catalog.tcgdex_client import TcgdexClient
from watari_core.catalog import make_card_id, pad_local_id
from watari_snkrdunk.client import SnkrdunkClient
from watari_snkrdunk.parser import parse_sales_history
from watari_snkrdunk.run import _SNKRDUNK_ERA_SLUG_OVERRIDE

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(minutes=30)
_SNKRDUNK_7D = timedelta(days=7)
# Redis key TTL = cache TTL + small buffer so Redis auto-expires stale entries.
_REDIS_TTL_SEC = int(CACHE_TTL.total_seconds()) + 120

# --- International price constants ----------------------------------------

_FX_TTL = timedelta(hours=1)
# Fallback rates: 1 JPY expressed in the foreign currency.
# To convert foreign price → JPY: foreign_price / rate.
_FX_FALLBACK: dict[str, float] = {"USD": 0.0065, "EUR": 0.0083}

_PC_BASE = "https://www.pricecharting.com"
# HTML element IDs on PriceCharting product pages → human-readable labels.
_PC_PRICE_IDS: dict[str, str] = {
    "used-price": "Ungraded",
    "graded-price-PSA-10": "PSA 10",
    "graded-price-PSA-9": "PSA 9",
    "graded-price-PSA-8": "PSA 8",
    "graded-price-PSA-7": "PSA 7",
}


@dataclass
class _CacheEntry:
    data: Any
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _is_stale(entry: _CacheEntry) -> bool:
    return datetime.now(UTC) - entry.fetched_at >= CACHE_TTL


def _is_stale_ttl(entry: _CacheEntry, ttl: timedelta) -> bool:
    return datetime.now(UTC) - entry.fetched_at >= ttl


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
    """On-demand price fetcher with per-card TTL cache (L1 memory + optional L2 Redis).

    Sources:
    - Snkrdunk (JP sold comps + graded)
    - TCGdex EN (TCGPlayer USD + Cardmarket EUR)
    - PriceCharting (eBay aggregated raw + PSA graded)
    """

    def __init__(self, redis: Any | None = None) -> None:
        self._sd_cache: dict[str, _CacheEntry] = {}
        self._sd_locks: dict[str, asyncio.Lock] = {}
        self._redis = redis  # optional aioredis client; None = memory-only

        # International price caches
        self._fx_cache: dict[str, _CacheEntry] = {}
        self._fx_lock: asyncio.Lock = asyncio.Lock()
        self._tcgdex_cache: dict[str, _CacheEntry] = {}
        self._tcgdex_locks: dict[str, asyncio.Lock] = {}
        self._pc_cache: dict[str, _CacheEntry] = {}
        self._pc_locks: dict[str, asyncio.Lock] = {}
        self._pc_sem: asyncio.Semaphore = asyncio.Semaphore(10)

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


    # --- FX rates ------------------------------------------------------------

    async def _fetch_fx_rates(self) -> dict[str, float]:
        """Return JPY→currency rates (e.g. {"USD": 0.0065, "EUR": 0.0083}).

        Cached for 1 hour; falls back to _FX_FALLBACK on any error.
        """
        key = "fx:rates"
        entry = self._fx_cache.get(key)
        if entry and not _is_stale_ttl(entry, _FX_TTL):
            return entry.data  # type: ignore[return-value]

        async with self._fx_lock:
            entry = self._fx_cache.get(key)
            if entry and not _is_stale_ttl(entry, _FX_TTL):
                return entry.data  # type: ignore[return-value]

            rates = await _do_fetch_fx_rates()
            self._fx_cache[key] = _CacheEntry(data=rates)
            return rates

    # --- TCGdex (TCGPlayer + Cardmarket) -------------------------------------

    async def fetch_tcgdex_prices(
        self, set_code: str, local_id: str, tcgdex_id: str
    ) -> dict[str, Any] | None:
        """Fetch EN TCGdex card payload (contains tcgplayer + cardmarket price blocks).

        Returns None if the card is not found in TCGdex EN or on any error.
        Result is cached for 30 min.
        """
        key = f"tcgdex:{set_code.upper()}/{pad_local_id(local_id)}"

        entry = self._tcgdex_cache.get(key)
        if entry and not _is_stale(entry):
            return entry.data  # type: ignore[return-value]

        lock = self._tcgdex_locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._tcgdex_cache.get(key)
            if entry and not _is_stale(entry):
                return entry.data  # type: ignore[return-value]

            data = await _do_fetch_tcgdex(tcgdex_id, local_id)
            self._tcgdex_cache[key] = _CacheEntry(data=data)
            return data

    async def tcgdex_international(
        self,
        set_code: str,
        local_id: str,
        tcgdex_id: str | None,
        card_id: str,
    ) -> list[dict[str, Any]]:
        """Return InternationalPrice-like dicts for TCGPlayer and Cardmarket."""
        if not tcgdex_id:
            return []

        data = await self.fetch_tcgdex_prices(set_code, local_id, tcgdex_id)
        if not data:
            return []

        rates = await self._fetch_fx_rates()
        results: list[dict[str, Any]] = []

        # --- TCGPlayer (USD) -------------------------------------------------
        tcp: dict[str, Any] = data.get("tcgplayer") or {}
        if tcp:
            tcp_url = tcp.get("url")
            tcp_updated = _parse_tcgdex_date(tcp.get("updatedAt") or {})
            tcp_prices: dict[str, Any] = (tcp.get("prices") or {}).get("normal") or {}
            for field_key, label in [("market", "Market"), ("mid", "Mid"), ("low", "Low")]:
                price = tcp_prices.get(field_key)
                if isinstance(price, (int, float)) and price > 0:
                    results.append({
                        "card_id": card_id,
                        "market": "tcgplayer",
                        "condition_label": label,
                        "price_jpy": _to_jpy(float(price), "USD", rates),
                        "price_raw": float(price),
                        "currency": "USD",
                        "observed_at": tcp_updated,
                        "external_url": tcp_url,
                    })

        # --- Cardmarket (EUR) ------------------------------------------------
        cm: dict[str, Any] = data.get("cardmarket") or {}
        if cm:
            cm_url = cm.get("url")
            cm_updated = _parse_tcgdex_date(cm.get("updatedAt") or {})
            cm_prices: dict[str, Any] = cm.get("prices") or {}
            for field_key, label in [
                ("averageSellPrice", "Avg Sell"),
                ("trendPrice", "Trend"),
                ("lowPrice", "Low"),
            ]:
                price = cm_prices.get(field_key)
                if isinstance(price, (int, float)) and price > 0:
                    results.append({
                        "card_id": card_id,
                        "market": "cardmarket",
                        "condition_label": label,
                        "price_jpy": _to_jpy(float(price), "EUR", rates),
                        "price_raw": float(price),
                        "currency": "EUR",
                        "observed_at": cm_updated,
                        "external_url": cm_url,
                    })

        return results

    # --- PriceCharting (eBay aggregated) -------------------------------------

    async def fetch_pricecharting(
        self,
        set_code: str,
        local_id: str,
        name_en: str | None,
        set_name_en: str | None,
    ) -> list[dict[str, Any]]:
        """Fetch PriceCharting prices via search + detail scrape (curl_cffi).

        Returns a list of {label, price, url} dicts.  Caches [] (not-found
        sentinel) for the full 30-min TTL to prevent hammering the search.
        """
        if not name_en:
            return []

        key = f"pc:{set_code.upper()}/{pad_local_id(local_id)}"

        entry = self._pc_cache.get(key)
        if entry and not _is_stale(entry):
            return entry.data  # type: ignore[return-value]

        lock = self._pc_locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._pc_cache.get(key)
            if entry and not _is_stale(entry):
                return entry.data  # type: ignore[return-value]

            async with self._pc_sem:
                data = await _do_fetch_pricecharting(name_en, set_name_en or "")

            self._pc_cache[key] = _CacheEntry(data=data)
            return data

    async def pricecharting_international(
        self,
        set_code: str,
        local_id: str,
        name_en: str | None,
        set_name_en: str | None,
        card_id: str,
    ) -> list[dict[str, Any]]:
        """Return InternationalPrice-like dicts from PriceCharting."""
        rows = await self.fetch_pricecharting(set_code, local_id, name_en, set_name_en)
        if not rows:
            return []

        rates = await self._fetch_fx_rates()
        now = datetime.now(UTC)
        results: list[dict[str, Any]] = []
        for row in rows:
            price = row.get("price")
            if not isinstance(price, (int, float)) or price <= 0:
                continue
            results.append({
                "card_id": card_id,
                "market": "pricecharting",
                "condition_label": row.get("label", ""),
                "price_jpy": _to_jpy(float(price), "USD", rates),
                "price_raw": float(price),
                "currency": "USD",
                "observed_at": now,
                "external_url": row.get("url"),
            })
        return results


# --- internal helpers --------------------------------------------------------


def _sd_key(set_code: str, local_id: str) -> str:
    return f"sd:{set_code.upper()}/{pad_local_id(local_id)}"


# --- FX helpers --------------------------------------------------------------


async def _do_fetch_fx_rates() -> dict[str, float]:
    """Fetch JPY→USD,EUR rates from Frankfurter. Falls back to _FX_FALLBACK on error."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.frankfurter.app/latest",
                params={"from": "JPY", "to": "USD,EUR"},
            )
            resp.raise_for_status()
            rates = resp.json().get("rates", {})
            if "USD" in rates and "EUR" in rates:
                logger.debug(
                    "price_proxy: fx rates USD=%s EUR=%s", rates["USD"], rates["EUR"]
                )
                return {"USD": float(rates["USD"]), "EUR": float(rates["EUR"])}
    except Exception:
        logger.warning("price_proxy: fx rate fetch failed, using fallback")
    return dict(_FX_FALLBACK)


def _to_jpy(price: float, currency: str, rates: dict[str, float]) -> int:
    """Convert a foreign-currency price to JPY.

    ``rates`` is in JPY→currency form (e.g. rates["USD"]=0.0065 means 1 JPY=0.0065 USD).
    Conversion: foreign_price / rate = jpy.
    """
    rate = rates.get(currency) or _FX_FALLBACK.get(currency, 0.006)
    if rate <= 0:
        rate = _FX_FALLBACK.get(currency, 0.006)
    return max(1, int(price / rate))


# --- TCGdex helpers ----------------------------------------------------------


def _parse_tcgdex_date(d: dict[str, Any]) -> datetime:
    """Parse TCGdex ``updatedAt`` dict ``{year, month, day}`` → UTC datetime."""
    try:
        return datetime(int(d["year"]), int(d["month"]), int(d["day"]), tzinfo=UTC)
    except (KeyError, ValueError, TypeError):
        return datetime.now(UTC)


async def _do_fetch_tcgdex(tcgdex_id: str, local_id: str) -> dict[str, Any] | None:
    """Fetch an EN TCGdex card payload. Returns None on 404 or any error."""
    # TCGdex uses stripped IDs: "089" → "89", "001" → "1".
    stripped = local_id.lstrip("0") or "0"
    logger.info("price_proxy: tcgdex fetch %s-%s", tcgdex_id, stripped)
    try:
        async with TcgdexClient(language="en", timeout_sec=10.0, request_delay_sec=0.0) as client:
            return await client.get_card(tcgdex_id, stripped)
    except Exception:
        logger.exception("price_proxy: tcgdex fetch failed for %s-%s", tcgdex_id, stripped)
        return None


# --- PriceCharting helpers ---------------------------------------------------


async def _cffi_get(url: str, *, timeout: float = 15.0) -> str:
    """Fetch ``url`` with curl_cffi Chrome TLS impersonation. Runs in a thread."""
    from curl_cffi import requests as curl_requests  # lazy — not always needed

    def _sync() -> str:
        with curl_requests.Session(impersonate="chrome124") as sess:
            resp = sess.get(url, timeout=timeout)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code} fetching {url}")
            return str(resp.text)

    return await asyncio.to_thread(_sync)


def _parse_pc_search(html: str, name_en: str) -> str | None:
    """Parse PriceCharting search results page → best matching product URL, or None.

    Looks for ``<a href="/game/pokemon-japanese/...">`` links.
    Scores each candidate with SequenceMatcher; also boosts results whose text
    starts with the card name (handles short names like "Muk" where the full
    link text "Muk 89 - Pokemon Card 151" would otherwise score poorly).
    Minimum effective score: 0.75.
    """
    from bs4 import BeautifulSoup  # lazy — only needed for PriceCharting

    soup = BeautifulSoup(html, "lxml")
    name_lower = name_en.lower()

    best_score = 0.0
    best_href: str | None = None

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", ""))
        if "/game/pokemon-japanese/" not in href:
            continue
        text = a.get_text(strip=True).lower()
        if not text:
            continue

        score = SequenceMatcher(None, name_lower, text).ratio()
        # Boost: if the result text starts with the card name (e.g. "muk 89 - ...")
        # the short-name penalty from sequence ratio is misleading — treat it as a
        # strong match.
        if text.startswith(name_lower):
            score = max(score, 0.80)

        if score > best_score:
            best_score = score
            best_href = href

    if best_score < 0.75 or best_href is None:
        return None

    return best_href if best_href.startswith("http") else f"{_PC_BASE}{best_href}"


def _parse_dollar(text: str) -> float | None:
    """Parse a price string like ``$12.34`` or ``12.34`` → float, None if unparseable."""
    cleaned = text.strip().replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned.lower() in ("n/a", "—", "-", ""):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_pc_detail(html: str, product_url: str) -> list[dict[str, Any]]:
    """Parse a PriceCharting product page → list of {label, price, url} dicts.

    Looks for ``<td id="used-price">`` and ``<td id="graded-price-PSA-*">``
    elements that PriceCharting uses for the main price table.  Returns []
    if none are found (graceful degradation for HTML structure changes).
    """
    from bs4 import BeautifulSoup  # lazy

    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, Any]] = []

    for elem_id, label in _PC_PRICE_IDS.items():
        el = soup.find(id=elem_id)
        if el is None:
            continue
        text = el.get_text(strip=True)
        price = _parse_dollar(text)
        if price is not None and price > 0:
            results.append({"label": label, "price": price, "url": product_url})

    return results


async def _do_fetch_pricecharting(
    name_en: str, set_name_en: str
) -> list[dict[str, Any]]:
    """Two-step PriceCharting scrape: search → detail.  Returns [] on any failure."""
    try:
        query = f"{name_en} {set_name_en}".strip()
        search_url = (
            f"{_PC_BASE}/search-products"
            f"?q={quote(query)}&type=prices&genre=pokemon-japanese"
        )
        logger.info("price_proxy: pricecharting search %r", query)
        html = await _cffi_get(search_url)
        product_url = _parse_pc_search(html, name_en)
        if product_url is None:
            logger.debug("price_proxy: pricecharting no match for %r", query)
            return []

        detail_html = await _cffi_get(product_url)
        rows = _parse_pc_detail(detail_html, product_url)
        logger.debug("price_proxy: pricecharting %r → %d rows", query, len(rows))
        return rows
    except Exception:
        logger.exception("price_proxy: pricecharting fetch failed for %r", name_en)
        return []


# --- Snkrdunk helpers --------------------------------------------------------


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
