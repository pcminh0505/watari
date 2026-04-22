"""Unit tests for rate limiting: config parsing + end-to-end dep wiring.

The Redis-backed :class:`~pokeprice_api.ratelimit.RateLimiter` itself is
exercised via a fake limiter that records calls and returns canned
:class:`~pokeprice_api.ratelimit.Decision` objects — we don't need the
token-bucket Lua correctness in the unit suite (it's tiny and covered by
the config-parse + integration-style tests).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pokeprice_api.auth import AuthContext, get_auth_context
from pokeprice_api.deps import get_session
from pokeprice_api.main import create_app
from pokeprice_api.ratelimit import (
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


class _MinimalRedisStub:
    """Just enough of an aioredis.Redis surface for RateLimiter.__init__."""

    def register_script(self, _: str) -> Any:  # pragma: no cover — never invoked
        return None


def test_bucket_for_unknown_tier_falls_back_to_free() -> None:
    limiter = RateLimiter(
        _MinimalRedisStub(),  # type: ignore[arg-type]
        {"free": Bucket(10, 1.0), "paid": Bucket(100, 10.0)},
    )
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


async def _fake_anonymous_auth() -> AuthContext:
    return AuthContext(
        authed=False,
        tier="free",
        api_key_id=None,
        key_prefix=None,
        identifier="ip:testclient",
    )


def _session_gen(session: Any) -> Any:
    async def _gen() -> AsyncGenerator[Any, None]:
        yield session

    return _gen


class _EmptyResult:
    """Returns zero rows for whatever the handler asks of it."""

    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[Any]:
        return []

    def scalar_one_or_none(self) -> Any:
        return None

    def mappings(self) -> _EmptyResult:
        return self

    def one_or_none(self) -> Any:
        return None


class _NoopSession:
    """Stand-in DB that returns empty results — rate-limit tests don't care
    about handler shape, they only care about headers/status codes."""

    async def execute(self, *_: Any, **__: Any) -> _EmptyResult:
        return _EmptyResult()

    async def commit(self) -> None:  # pragma: no cover
        return None


@pytest.fixture()
def rl_client():  # type: ignore[no-untyped-def]
    def _make(decisions: list[Decision]) -> tuple[TestClient, FakeLimiter]:
        app = create_app()
        limiter = FakeLimiter(decisions)
        # Override the rate-limiter + auth so we don't need Redis or DB.
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        app.dependency_overrides[get_auth_context] = _fake_anonymous_auth
        app.dependency_overrides[get_session] = _session_gen(_NoopSession())
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
    # Handler runs with _NoopSession returning 0 rows, so 200 + [].
    resp = client.get("/sets")
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
    resp = client.get("/sets")
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
