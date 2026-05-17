"""FastAPI dependencies for online mode (no database).

Catalog and price-proxy instances live on ``app.state`` and are wired up
in the FastAPI lifespan (see :mod:`watari_api.main`).  Both can be overridden
in tests via ``app.dependency_overrides``.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from watari_api.catalog_mem import MemCatalog
from watari_api.price_proxy import PriceProxy

SUPPORTED_LANGS = {"jp"}


def get_catalog(request: Request) -> MemCatalog:
    """Return the process-wide in-memory catalog from ``app.state``."""
    catalog: MemCatalog | None = getattr(request.app.state, "catalog", None)
    if catalog is None:
        raise RuntimeError("catalog not installed on app.state; check the FastAPI lifespan")
    return catalog


def get_price_proxy(request: Request) -> PriceProxy:
    """Return the process-wide price proxy from ``app.state``."""
    proxy: PriceProxy | None = getattr(request.app.state, "price_proxy", None)
    if proxy is None:
        raise RuntimeError("price_proxy not installed on app.state; check the FastAPI lifespan")
    return proxy


async def validate_lang(lang: str, request: Request) -> str:
    """Validate locale path segment and stash it on request state."""
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=404, detail=f"unsupported language: {lang!r}")
    request.state.lang = lang
    return lang
