"""FastAPI application factory for the watari read API.

The API is read-only and sits on top of the v3 catalog (``sets`` /
``artworks`` / ``cards``) plus the three materialized views that aggregate
``price_points``. See ``CLAUDE.md`` §3.1 for the schema and §5.2 for the
endpoint list.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from watari_core.config import settings

from watari_api.deps import validate_lang
from watari_api.ratelimit import RateLimiter, parse_rate_limits, rate_limit_dep
from watari_api.routers import cards, prices, sets


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Process-scoped setup: open a Redis pool + install the rate limiter.

    Both live on ``app.state`` so dependencies and tests can swap them. The
    pool is closed on shutdown; individual requests don't own connections.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis_client
    app.state.rate_limiter = RateLimiter(
        redis_client,
        parse_rate_limits(settings.api_rate_limits),
    )
    try:
        yield
    finally:
        await redis_client.aclose()


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

    lang_router = APIRouter(
        prefix="/{lang}",
        dependencies=[Depends(validate_lang), Depends(rate_limit_dep)],
    )
    lang_router.include_router(sets.router)
    lang_router.include_router(cards.router)
    lang_router.include_router(prices.router)
    app.include_router(lang_router)

    return app


app = create_app()
