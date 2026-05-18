"""FastAPI dependencies for hybrid mode (in-memory catalog + DB for prices).

Catalog and price-proxy instances live on ``app.state`` and are wired up
in the FastAPI lifespan (see :mod:`watari_api.main`).  Both can be overridden
in tests via ``app.dependency_overrides``.

``get_session`` yields a SQLAlchemy async session for reading price MVs
(Cardrush) and graded history.  ``get_price_proxy`` returns the process-wide
Snkrdunk on-demand proxy.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from watari_api.catalog_mem import MemCatalog
from watari_api.price_proxy import PriceProxy
from watari_core.db import async_session_factory

SUPPORTED_LANGS = {"jp"}


def get_catalog(request: Request) -> MemCatalog:
    """Return the process-wide in-memory catalog from ``app.state``."""
    catalog: MemCatalog | None = getattr(request.app.state, "catalog", None)
    if catalog is None:
        raise RuntimeError("catalog not installed on app.state; check the FastAPI lifespan")
    return catalog


def get_price_proxy(request: Request) -> PriceProxy:
    """Return the process-wide Snkrdunk price proxy from ``app.state``."""
    proxy: PriceProxy | None = getattr(request.app.state, "price_proxy", None)
    if proxy is None:
        raise RuntimeError("price_proxy not installed on app.state; check the FastAPI lifespan")
    return proxy


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a SQLAlchemy async session for DB reads (Cardrush MVs, graded history)."""
    async with async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def validate_lang(lang: str, request: Request) -> str:
    """Validate locale path segment and stash it on request state."""
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=404, detail=f"unsupported language: {lang!r}")
    request.state.lang = lang
    return lang
