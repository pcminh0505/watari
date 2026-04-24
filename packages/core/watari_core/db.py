"""SQLAlchemy async engine, session factory, and declarative Base."""

import ssl
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from watari_core.config import settings


def _connect_args() -> dict:
    """Return connect_args for the async engine.

    SSL is passed here — not in the URL — to avoid SQLAlchemy 2.0 injecting
    a `channel_binding` kwarg that asyncpg does not accept.
    """
    host = urlparse(settings.database_url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1", ""):
        return {}
    return {"ssl": ssl.create_default_context()}


engine = create_async_engine(settings.database_url, echo=False, connect_args=_connect_args())
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
