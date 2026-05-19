"""FastAPI application factory for the watari read API — hybrid mode.

Catalog (sets / artworks / cards) is loaded from YAML at startup.
Cardrush prices are read from the DB (mv_* materialized views); Snkrdunk
prices are fetched on demand and cached in memory for
:data:`watari_api.price_proxy.CACHE_TTL` (default 30 min).

Requires DATABASE_URL pointing to Neon PostgreSQL.
Redis is optional: set REDIS_URL to enable a shared L2 cache.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from watari_core.config import settings
from watari_core.db import engine as db_engine

from watari_catalog.tcgdex_client import TcgdexClient

from watari_api.catalog_mem import MemCatalog
from watari_api.deps import validate_lang
from watari_api.price_proxy import PriceProxy
from watari_api.ratelimit import RateLimiter, parse_rate_limits, rate_limit_dep
from watari_api.routers import admin, cards, prices, sets

logger = logging.getLogger(__name__)


async def _populate_official_totals(catalog: MemCatalog) -> None:
    """Fetch official card counts from TCGdex and store on MemSet.total.

    One HTTP call returns all sets including cardCount.official (the number
    printed on cards as the denominator, e.g. 165 for SV2A where secret
    rares are numbered above 165).  Runs once at startup; errors are
    non-fatal — affected sets fall back to catalog artwork count.
    """
    sets_needing_total = [s for s in catalog._sets.values() if s.total is None and s.tcgdex_id]
    if not sets_needing_total:
        return
    try:
        async with TcgdexClient(language="en", timeout_sec=10.0, request_delay_sec=0.0) as client:
            all_sets = await client.get_all_sets()
        totals: dict[str, int] = {}
        for entry in all_sets:
            sid = (entry.get("id") or "").upper()
            cc = entry.get("cardCount")
            official = cc.get("official") if isinstance(cc, dict) else None
            if sid and isinstance(official, int) and official > 0:
                totals[sid] = official
        filled = 0
        for s in sets_needing_total:
            official = totals.get(s.tcgdex_id.upper())
            if official:
                s.total = official
                filled += 1
        logger.info("lifespan: populated official totals for %d/%d sets from TCGdex", filled, len(sets_needing_total))
    except Exception:
        logger.warning("lifespan: could not fetch official totals from TCGdex — card numbers will lack denominators", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Process-scoped setup: verify DB + load YAML catalog + install price proxy + rate limiter."""
    # Verify DB connection before serving traffic.
    async with db_engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("lifespan: DB connection verified (%s)", settings.database_url.split("@")[-1])

    # Run the synchronous catalog loader off the event loop so other coroutines
    # (e.g. /healthz) remain responsive during the 1–3 s startup I/O burst.
    app.state.catalog = await asyncio.to_thread(MemCatalog.load)

    # Backfill official set totals from TCGdex (one HTTP call, non-fatal).
    await _populate_official_totals(app.state.catalog)

    # Optional Redis L2 cache — gracefully degrades to memory-only on failure.
    redis = None
    if settings.redis_url:
        try:
            from redis.asyncio import Redis as AsyncRedis  # type: ignore[import]

            redis = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
            await redis.ping()
            logger.info("price_proxy: Redis L2 cache connected at %s", settings.redis_url)
        except Exception:
            logger.warning(
                "price_proxy: Redis unavailable (%s) — falling back to memory-only cache",
                settings.redis_url,
            )
            redis = None

    app.state.price_proxy = PriceProxy(redis=redis)
    app.state.rate_limiter = RateLimiter(
        parse_rate_limits(settings.api_rate_limits),
    )
    yield

    if redis is not None:
        await redis.aclose()


def create_app() -> FastAPI:
    """Build the FastAPI app. Use a factory so tests can build a fresh app."""
    app = FastAPI(
        title="PokePrice API",
        version="0.1.0",
        description="Read-only locale-aware price + catalog API for the Pokemon TCG market.",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.api_cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/rates", tags=["utility"])
    async def exchange_rates() -> dict[str, float]:
        """Proxy JPY→USD/VND exchange rates from Frankfurter.

        Runs server-side so the browser is never blocked by Frankfurter's
        missing CORS headers.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.frankfurter.app/latest?from=JPY&to=USD,VND"
                )
                resp.raise_for_status()
                data = resp.json()
            return {"USD": data["rates"]["USD"], "VND": data["rates"]["VND"]}
        except Exception as exc:
            raise HTTPException(status_code=502, detail="exchange rate service unavailable") from exc

    lang_router = APIRouter(
        prefix="/{lang}",
        dependencies=[Depends(validate_lang), Depends(rate_limit_dep)],
    )
    lang_router.include_router(sets.router)
    lang_router.include_router(cards.router)
    lang_router.include_router(prices.router)
    app.include_router(lang_router)

    # Admin endpoints — outside locale routing and rate limiting
    app.include_router(admin.router)

    return app


app = create_app()
