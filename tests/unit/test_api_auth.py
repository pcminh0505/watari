"""Unit tests for the auth stub — online mode.

In online mode all requests are anonymous/free-tier regardless of any
``X-API-Key`` header. These tests verify that :func:`get_auth_context` always
returns the correct anonymous context and that the :class:`AuthContext`
dataclass behaves as expected.
"""

from __future__ import annotations

import pytest
from watari_api.auth import AuthContext, get_auth_context


class FakeRequest:
    def __init__(self, ip: str | None = "1.2.3.4") -> None:
        if ip is not None:

            class _Client:
                host = ip

            self.client = _Client()
        else:
            self.client = None
        self.headers: dict[str, str] = {}


# --- AuthContext ---------------------------------------------------------


def test_auth_context_equality() -> None:
    a = AuthContext(authed=False, tier="free", api_key_id=None, key_prefix=None, identifier="ip:1.2.3.4")
    b = AuthContext(authed=False, tier="free", api_key_id=None, key_prefix=None, identifier="ip:1.2.3.4")
    assert a == b


def test_auth_context_is_frozen() -> None:
    ctx = AuthContext(authed=False, tier="free", api_key_id=None, key_prefix=None, identifier="ip:x")
    with pytest.raises((AttributeError, TypeError)):
        ctx.tier = "paid"  # type: ignore[misc]


# --- get_auth_context ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_auth_context_always_anonymous() -> None:
    req = FakeRequest(ip="10.0.0.1")
    ctx = await get_auth_context(req)  # type: ignore[arg-type]
    assert ctx == AuthContext(
        authed=False,
        tier="free",
        api_key_id=None,
        key_prefix=None,
        identifier="ip:10.0.0.1",
    )


@pytest.mark.asyncio
async def test_get_auth_context_ignores_api_key_header() -> None:
    req = FakeRequest(ip="2.3.4.5")
    req.headers["X-API-Key"] = "pk_some_secret_key"
    ctx = await get_auth_context(req)  # type: ignore[arg-type]
    assert ctx.authed is False
    assert ctx.tier == "free"
    assert ctx.api_key_id is None
    assert ctx.key_prefix is None


@pytest.mark.asyncio
async def test_get_auth_context_encodes_client_ip() -> None:
    req = FakeRequest(ip="192.168.1.42")
    ctx = await get_auth_context(req)  # type: ignore[arg-type]
    assert ctx.identifier == "ip:192.168.1.42"


@pytest.mark.asyncio
async def test_get_auth_context_unknown_client_falls_back_to_unknown() -> None:
    req = FakeRequest(ip=None)  # no client attached
    ctx = await get_auth_context(req)  # type: ignore[arg-type]
    assert ctx.identifier == "ip:unknown"
