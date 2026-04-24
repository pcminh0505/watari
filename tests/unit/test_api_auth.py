"""Unit tests for the API-key auth dependency.

These tests exercise :mod:`watari_api.auth` in isolation — they don't
boot the FastAPI app and don't talk to Redis. The DB is stubbed with a
minimal async session that queues canned rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from watari_api.auth import (
    API_KEY_PLAINTEXT_PREFIX,
    LAST_USED_THROTTLE,
    AuthContext,
    get_auth_context,
    hash_api_key,
    mint_api_key,
)

# --- Fakes ---------------------------------------------------------------


@dataclass
class FakeApiKey:
    id: int
    key_hash: str
    key_prefix: str
    owner_email: str
    tier: str
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


@dataclass
class FakeSession:
    rows: list[Any]
    commits: int = 0
    executed: list[Any] = field(default_factory=list)

    async def execute(self, stmt: Any) -> FakeScalarResult:
        self.executed.append(stmt)
        # pop FIFO so tests can queue multiple lookups if they want
        value = self.rows.pop(0) if self.rows else None
        return FakeScalarResult(value)

    async def commit(self) -> None:
        self.commits += 1


class FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None, ip: str = "1.2.3.4") -> None:
        self.headers = headers or {}

        class _Client:
            host = ip

        self.client = _Client()


# --- hash / mint ---------------------------------------------------------


def test_hash_api_key_is_deterministic_and_64_hex() -> None:
    h1 = hash_api_key("pk_abc_xxx")
    h2 = hash_api_key("pk_abc_xxx")
    assert h1 == h2
    assert len(h1) == 64
    assert set(h1) <= set("0123456789abcdef")


def test_mint_api_key_shape_and_hash_consistency() -> None:
    plaintext, prefix, key_hash = mint_api_key()
    assert plaintext.startswith(API_KEY_PLAINTEXT_PREFIX)
    assert prefix.startswith(API_KEY_PLAINTEXT_PREFIX)
    # the prefix must be a real substring of the plaintext
    assert plaintext.startswith(prefix + "_")
    # hash matches what auth computes
    assert key_hash == hash_api_key(plaintext)


def test_mint_api_key_is_random() -> None:
    k1 = mint_api_key()
    k2 = mint_api_key()
    assert k1[0] != k2[0]
    assert k1[1] != k2[1]
    assert k1[2] != k2[2]


# --- get_auth_context ---------------------------------------------------


async def test_no_header_returns_anonymous_free_by_ip() -> None:
    session = FakeSession(rows=[])
    req = FakeRequest(ip="10.0.0.1")
    ctx = await get_auth_context(req, session)  # type: ignore[arg-type]
    assert ctx == AuthContext(
        authed=False,
        tier="free",
        api_key_id=None,
        key_prefix=None,
        identifier="ip:10.0.0.1",
    )
    # no DB hit, no commit
    assert session.executed == []
    assert session.commits == 0


async def test_unknown_key_raises_401() -> None:
    session = FakeSession(rows=[None])  # no match in api_keys
    req = FakeRequest(headers={"X-API-Key": "pk_nope_xxx"})
    with pytest.raises(HTTPException) as excinfo:
        await get_auth_context(req, session)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 401
    assert "invalid" in excinfo.value.detail.lower()
    assert session.commits == 0


async def test_revoked_key_raises_401() -> None:
    row = FakeApiKey(
        id=1,
        key_hash=hash_api_key("pk_abc_xxx"),
        key_prefix="pk_abc",
        owner_email="x@y",
        tier="free",
        revoked_at=datetime.now(UTC),
    )
    session = FakeSession(rows=[row])
    req = FakeRequest(headers={"X-API-Key": "pk_abc_xxx"})
    with pytest.raises(HTTPException) as excinfo:
        await get_auth_context(req, session)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 401
    assert "revoked" in excinfo.value.detail.lower()
    assert session.commits == 0


async def test_valid_key_returns_authed_context_and_bumps_last_used() -> None:
    row = FakeApiKey(
        id=42,
        key_hash=hash_api_key("pk_ok_xxx"),
        key_prefix="pk_ok",
        owner_email="dev@example.com",
        tier="paid",
        last_used_at=None,  # never used → always bumped
    )
    session = FakeSession(rows=[row])
    req = FakeRequest(headers={"X-API-Key": "pk_ok_xxx"})
    before = datetime.now(UTC)
    ctx = await get_auth_context(req, session)  # type: ignore[arg-type]
    assert ctx.authed is True
    assert ctx.tier == "paid"
    assert ctx.api_key_id == 42
    assert ctx.key_prefix == "pk_ok"
    assert ctx.identifier == "key:42"
    assert row.last_used_at is not None and row.last_used_at >= before
    assert session.commits == 1


async def test_last_used_is_throttled_within_window() -> None:
    # Pretend the key was used a few seconds ago → auth should NOT bump.
    recent = datetime.now(UTC) - timedelta(seconds=5)
    row = FakeApiKey(
        id=7,
        key_hash=hash_api_key("pk_x_yyy"),
        key_prefix="pk_x",
        owner_email="x@y",
        tier="free",
        last_used_at=recent,
    )
    session = FakeSession(rows=[row])
    req = FakeRequest(headers={"X-API-Key": "pk_x_yyy"})
    ctx = await get_auth_context(req, session)  # type: ignore[arg-type]
    assert ctx.authed is True
    assert row.last_used_at == recent  # unchanged
    assert session.commits == 0


async def test_last_used_is_bumped_once_throttle_elapsed() -> None:
    stale = datetime.now(UTC) - LAST_USED_THROTTLE - timedelta(seconds=1)
    row = FakeApiKey(
        id=9,
        key_hash=hash_api_key("pk_y_zzz"),
        key_prefix="pk_y",
        owner_email="y@z",
        tier="free",
        last_used_at=stale,
    )
    session = FakeSession(rows=[row])
    req = FakeRequest(headers={"X-API-Key": "pk_y_zzz"})
    await get_auth_context(req, session)  # type: ignore[arg-type]
    assert row.last_used_at is not None and row.last_used_at > stale
    assert session.commits == 1
