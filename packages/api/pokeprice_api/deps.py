"""FastAPI dependencies (DB session, etc.)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from pokeprice_core.db import async_session_factory
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a SQLAlchemy async session scoped to the request."""
    async with async_session_factory() as session:
        yield session
