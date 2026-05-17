"""FastAPI application factory for the watari read API — online mode.

Catalog (sets / artworks / cards) is loaded from YAML at startup.
Prices are fetched on demand from Cardrush and Snkrdunk and cached in memory
for :data:`watari_api.price_proxy.CACHE_TTL` (default 30 min).

No PostgreSQL required. Redis is optional: set REDIS_URL to enable a shared
L2 cache that survives process restarts. If unset, memory-only mode is used.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from watari_core.config import settings

from watari_api.catalog_mem import MemCatalog
from watari_api.deps import validate_lang
from watari_api.price_proxy import PriceProxy
from watari_api.ratelimit import RateLimiter, parse_rate_limits, rate_limit_dep
from watari_api.routers import admin, cards, prices, sets

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Process-scoped setup: load YAML catalog + install price proxy + rate limiter."""
    # Run the synchronous catalog loader off the event loop so other coroutines
    # (e.g. /healthz) remain responsive during the 1–3 s startup I/O burst.
    app.state.catalog = await asyncio.to_thread(MemCatalog.load)

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
        allow_methods=["GET"],
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
