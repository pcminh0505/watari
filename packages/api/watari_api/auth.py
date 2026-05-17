"""Authentication stub for online mode.

In online mode (no PostgreSQL) all requests are treated as anonymous/free-tier.
The ``X-API-Key`` header is ignored. Rate limiting still applies via the
in-memory token bucket in :mod:`watari_api.ratelimit`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request


@dataclass(frozen=True)
class AuthContext:
    """Resolved auth for the current request."""

    authed: bool
    tier: str
    api_key_id: int | None
    key_prefix: str | None
    identifier: str


def _client_ip(request: Request) -> str:
    client = request.client
    return client.host if client is not None else "unknown"


async def get_auth_context(request: Request) -> AuthContext:
    """Always returns anonymous/free-tier auth in online mode."""
    return AuthContext(
        authed=False,
        tier="free",
        api_key_id=None,
        key_prefix=None,
        identifier=f"ip:{_client_ip(request)}",
    )


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
