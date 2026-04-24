"""API-key authentication for the read API.

Contract:

- Reads an optional ``X-API-Key`` header (name configurable via
  ``settings.api_key_header``). No header → anonymous caller, ``free`` tier.
- If a header is present we look it up by **SHA-256 hash** of the raw key
  (``api_keys.key_hash``). The raw plaintext is never stored.
    - Unknown hash → 401. We don't silently downgrade to anonymous: the
      caller explicitly tried to authenticate.
    - Revoked (``revoked_at IS NOT NULL``) → 401.
    - Otherwise → authenticated; the key's ``tier`` is used downstream.
- ``last_used_at`` is bumped at most once per :data:`LAST_USED_THROTTLE` per
  key so this stays cheap on hot paths.

Issuance is handled via :func:`mint_api_key` (see the ``create-key`` CLI).
Keys look like ``pk_<prefix>_<body>``; we persist only ``(key_hash,
key_prefix)``. The prefix is safe to log/display and is what operators use to
revoke a key without ever needing the plaintext.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from watari_core.config import settings
from watari_core.models import ApiKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watari_api.deps import get_session

API_KEY_PLAINTEXT_PREFIX = "pk_"
_PREFIX_BYTES = 3
_BODY_BYTES = 32

LAST_USED_THROTTLE = timedelta(minutes=1)


@dataclass(frozen=True)
class AuthContext:
    """Resolved auth for the current request.

    ``identifier`` is the stable-per-caller string the rate limiter buckets on.
    For authenticated callers it's ``"key:{id}"``; for anonymous callers it's
    ``"ip:{client_ip}"`` so abusive anonymous traffic from one origin doesn't
    starve everyone else on the free tier.
    """

    authed: bool
    tier: str
    api_key_id: int | None
    key_prefix: str | None
    identifier: str


def hash_api_key(raw_key: str) -> str:
    """Deterministic SHA-256 hex digest for ``api_keys.key_hash`` lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def mint_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns ``(plaintext, key_prefix, key_hash)``. The plaintext MUST be
    shown exactly once at issuance — we never persist it, only the hash.
    The ``key_prefix`` is stored alongside the hash so operators can list
    and revoke keys without ever handling the raw secret.
    """
    prefix_raw = secrets.token_hex(_PREFIX_BYTES)
    body = secrets.token_hex(_BODY_BYTES)
    plaintext = f"{API_KEY_PLAINTEXT_PREFIX}{prefix_raw}_{body}"
    key_prefix = f"{API_KEY_PLAINTEXT_PREFIX}{prefix_raw}"
    return plaintext, key_prefix, hash_api_key(plaintext)


def _client_ip(request: Request) -> str:
    client = request.client
    return client.host if client is not None else "unknown"


async def get_auth_context(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    """Resolve the auth context for the current request.

    Commits a ``last_used_at`` bump at most once per
    :data:`LAST_USED_THROTTLE` per key. Anonymous requests never write.
    """
    raw = request.headers.get(settings.api_key_header)
    if not raw:
        return AuthContext(
            authed=False,
            tier="free",
            api_key_id=None,
            key_prefix=None,
            identifier=f"ip:{_client_ip(request)}",
        )

    key_hash = hash_api_key(raw)
    row = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
        )
    if row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key revoked",
        )

    now = datetime.now(UTC)
    if row.last_used_at is None or (now - row.last_used_at) > LAST_USED_THROTTLE:
        row.last_used_at = now
        await session.commit()

    return AuthContext(
        authed=True,
        tier=row.tier,
        api_key_id=row.id,
        key_prefix=row.key_prefix,
        identifier=f"key:{row.id}",
    )


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
