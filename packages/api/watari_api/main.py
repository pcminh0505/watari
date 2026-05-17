"""FastAPI application factory for the watari read API — online mode.

Catalog (sets / artworks / cards) is loaded from YAML at startup.
Prices are fetched on demand from Cardrush and Snkrdunk and cached in memory
for :data:`watari_api.price_proxy.CACHE_TTL` (default 30 min).

No PostgreSQL or Redis required.
"""

from __future__ import annotations

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Process-scoped setup: load YAML catalog + install price proxy + rate limiter."""
    app.state.catalog = MemCatalog.load()
    app.state.price_proxy = PriceProxy()
    app.state.rate_limiter = RateLimiter(
        parse_rate_limits(settings.api_rate_limits),
    )
    yield


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
