"""Unit tests for rate limiting: config parsing + end-to-end dep wiring.

The in-memory :class:`~watari_api.ratelimit.RateLimiter` is exercised via a
fake limiter that records calls and returns canned
:class:`~watari_api.ratelimit.Decision` objects. We verify the token-bucket
config parsing and the FastAPI dependency wiring, not the Lua/Redis details
(there are none in online mode).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from watari_api.auth import AuthContext, get_auth_context
from watari_api.deps import get_catalog
from watari_api.main import create_app
from watari_api.ratelimit import (
    Bucket,
    Decision,
    RateLimiter,
    get_rate_limiter,
    parse_rate_limits,
)

# --- parse_rate_limits ---------------------------------------------------


def test_parse_rate_limits_basic() -> None:
    buckets = parse_rate_limits("free:60:1.0,paid:600:10.0")
    assert buckets == {
        "free": Bucket(60, 1.0),
        "paid": Bucket(600, 10.0),
    }


def test_parse_rate_limits_ignores_blank_entries_and_trims() -> None:
    buckets = parse_rate_limits("  free:10:0.5  , , paid:100:1.5 ")
    assert buckets["free"] == Bucket(10, 0.5)
    assert buckets["paid"] == Bucket(100, 1.5)


def test_parse_rate_limits_requires_free_tier() -> None:
    with pytest.raises(ValueError, match="free"):
        parse_rate_limits("paid:100:1.0")


def test_parse_rate_limits_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="invalid rate-limit entry"):
        parse_rate_limits("free:60")


# --- bucket lookup -------------------------------------------------------


def test_bucket_for_unknown_tier_falls_back_to_free() -> None:
    limiter = RateLimiter({"free": Bucket(10, 1.0), "paid": Bucket(100, 10.0)})
    assert limiter._bucket_for("nonsense") == Bucket(10, 1.0)  # noqa: SLF001
    assert limiter._bucket_for("paid") == Bucket(100, 10.0)  # noqa: SLF001


# --- rate_limit_dep end-to-end with a fake limiter ----------------------


class FakeLimiter:
    """Canned :class:`Decision` responses; records ``(tier, identifier)`` calls."""

    def __init__(self, decisions: list[Decision]) -> None:
        self._decisions = list(decisions)
        self.calls: list[tuple[str, str]] = []

    async def check(
        self,
        tier: str,
        identifier: str,
        cost: int = 1,
    ) -> Decision:
        self.calls.append((tier, identifier))
        if not self._decisions:
            raise AssertionError("FakeLimiter exhausted")
        return self._decisions.pop(0)


class _EmptyCatalog:
    """Returns empty results for all catalog lookups — rate-limit tests only
    care about response headers, not handler body shape."""

    def get_sets(self, *, language: str = "jp", era: str | None = None) -> list[Any]:
        return []

    def get_set(self, set_code: str, *, language: str = "jp") -> None:
        return None

    def get_artworks(self, set_code: str) -> list[Any]:
        return []

    def get_artwork(self, set_code: str, local_id: str) -> None:
        return None

    def search_artworks(self, **kwargs: Any) -> list[Any]:
        return []

    def get_rarities(self, *, language: str, set_code: str | None = None) -> list[str]:
        return []


async def _fake_anonymous_auth() -> AuthContext:
    return AuthContext(
        authed=False,
        tier="free",
        api_key_id=None,
        key_prefix=None,
        identifier="ip:testclient",
    )


@pytest.fixture()
def rl_client():  # type: ignore[no-untyped-def]
    def _make(decisions: list[Decision]) -> tuple[TestClient, FakeLimiter]:
        app = create_app()
        limiter = FakeLimiter(decisions)
        # Override rate-limiter + auth so we don't need Redis or a DB.
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        app.dependency_overrides[get_auth_context] = _fake_anonymous_auth
        app.dependency_overrides[get_catalog] = lambda: _EmptyCatalog()
        return TestClient(app), limiter

    return _make


def test_allowed_request_sets_rate_limit_headers(rl_client) -> None:  # type: ignore[no-untyped-def]
    decision = Decision(
        allowed=True,
        remaining=59,
        retry_after=0,
        bucket=Bucket(60, 1.0),
    )
    client, limiter = rl_client([decision])
    # Handler runs with empty catalog, returns 200 + [].
    resp = client.get("/jp/sets")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers.get("X-RateLimit-Tier") == "free"
    assert resp.headers.get("X-RateLimit-Limit") == "60"
    assert resp.headers.get("X-RateLimit-Remaining") == "59"
    assert limiter.calls == [("free", "ip:testclient")]


def test_denied_request_returns_429_with_retry_after(rl_client) -> None:  # type: ignore[no-untyped-def]
    decision = Decision(
        allowed=False,
        remaining=0,
        retry_after=5,
        bucket=Bucket(60, 1.0),
    )
    client, _ = rl_client([decision])
    resp = client.get("/jp/sets")
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "5"
    assert resp.headers.get("X-RateLimit-Tier") == "free"
    assert resp.headers.get("X-RateLimit-Remaining") == "0"
    body = resp.json()
    assert body.get("detail") == "rate limit exceeded"


def test_healthz_bypasses_rate_limit(rl_client) -> None:  # type: ignore[no-untyped-def]
    # No decisions queued; FakeLimiter.check would AssertionError if called.
    client, limiter = rl_client([])
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert limiter.calls == []
    # Healthz must not leak rate-limit metadata either.
    assert "X-RateLimit-Tier" not in resp.headers
