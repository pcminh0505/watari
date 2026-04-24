"""FastAPI dependencies (DB session, locale validation, etc.)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from watari_core.db import async_session_factory
from sqlalchemy.ext.asyncio import AsyncSession

SUPPORTED_LANGS = {"jp"}


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a SQLAlchemy async session scoped to the request."""
    async with async_session_factory() as session:
        yield session


async def validate_lang(lang: str, request: Request) -> str:
    """Validate locale path segment and stash it on request state."""
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=404, detail=f"unsupported language: {lang!r}")
    request.state.lang = lang
    return lang
