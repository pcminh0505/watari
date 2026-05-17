"""Per-tier token-bucket rate limiting — in-memory implementation.

Replaces the Redis-backed version for online mode. The same
``tier:capacity:rate`` config format and ``Decision`` interface are preserved
so callers do not change.

All state is process-local: limits reset on restart and are NOT shared across
multiple API instances. For a personal project running one process this is
fine; add Redis back if horizontal scaling is ever needed.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status

from watari_api.auth import AuthContext, get_auth_context


@dataclass(frozen=True)
class Bucket:
    capacity: int
    rate: float


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: int
    bucket: Bucket


def parse_rate_limits(spec: str) -> dict[str, Bucket]:
    """Parse a ``tier:capacity:rate,…`` spec.

    ``free`` is mandatory — it's both the anonymous tier and the fallback.
    """
    out: dict[str, Bucket] = {}
    for raw in spec.split(","):
        piece = raw.strip()
        if not piece:
            continue
        try:
            tier, capacity_s, rate_s = piece.split(":")
        except ValueError as exc:
            raise ValueError(
                f"invalid rate-limit entry {piece!r}; expected 'tier:capacity:rate'"
            ) from exc
        out[tier.strip()] = Bucket(int(capacity_s), float(rate_s))
    if "free" not in out:
        raise ValueError("api_rate_limits must include a 'free' tier")
    return out


@dataclass
class _BucketState:
    tokens: float
    ts: float


class RateLimiter:
    """In-memory token-bucket limiter. One instance per process."""

    def __init__(self, buckets: dict[str, Bucket]) -> None:
        self.buckets = buckets
        self._states: dict[str, _BucketState] = {}
        self._lock = asyncio.Lock()

    def _bucket_for(self, tier: str) -> Bucket:
        return self.buckets.get(tier) or self.buckets["free"]

    async def check(self, tier: str, identifier: str, cost: int = 1) -> Decision:
        bucket = self._bucket_for(tier)
        key = f"rl:{tier}:{identifier}"
        now = time.monotonic()

        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _BucketState(tokens=float(bucket.capacity), ts=now)
                self._states[key] = state

            delta = max(0.0, now - state.ts)
            state.tokens = min(float(bucket.capacity), state.tokens + delta * bucket.rate)
            state.ts = now

            if state.tokens >= cost:
                state.tokens -= cost
                return Decision(
                    allowed=True,
                    remaining=int(state.tokens),
                    retry_after=0,
                    bucket=bucket,
                )

            retry_after = max(1, int((cost - state.tokens) / max(bucket.rate, 0.001)))
            return Decision(
                allowed=False,
                remaining=0,
                retry_after=retry_after,
                bucket=bucket,
            )


def get_rate_limiter(request: Request) -> RateLimiter:
    """Fetch the process-wide :class:`RateLimiter` from ``app.state``."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        raise RuntimeError("rate limiter not installed on app.state; check the FastAPI lifespan")
    return limiter


async def rate_limit_dep(
    response: Response,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AuthContext:
    """Rate-limit the current request and stamp ``X-RateLimit-*`` headers."""
    decision = await limiter.check(auth.tier, auth.identifier)
    response.headers["X-RateLimit-Tier"] = auth.tier
    response.headers["X-RateLimit-Limit"] = str(decision.bucket.capacity)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={
                "Retry-After": str(max(decision.retry_after, 1)),
                "X-RateLimit-Tier": auth.tier,
                "X-RateLimit-Limit": str(decision.bucket.capacity),
                "X-RateLimit-Remaining": "0",
            },
        )
    return auth


RateLimitedAuthDep = Annotated[AuthContext, Depends(rate_limit_dep)]
