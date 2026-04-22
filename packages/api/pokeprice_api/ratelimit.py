"""Per-tier token-bucket rate limiting, backed by Redis.

Why a bucket per *tier × caller*:
    We want abusive free-tier traffic to hurt only that caller, and we want
    paid tiers to have headroom for bursts without permanently locking out
    free users. Keys look like ``rl:{tier}:{identifier}`` where
    ``identifier`` is ``key:{api_key_id}`` for authenticated calls and
    ``ip:{client_ip}`` for anonymous ones (see :mod:`pokeprice_api.auth`).

Config:
    ``settings.api_rate_limits`` is a comma-separated ``tier:capacity:rate``
    spec. ``capacity`` is the burst size (tokens at full bucket) and
    ``rate`` is tokens refilled per second. A ``free`` tier is always
    required because it doubles as the fallback when a key's tier is
    unknown to this process.

Implementation:
    A single Redis Lua script advances the bucket and performs the admit
    decision atomically. ``HMSET`` + ``EXPIRE`` cap idle keys so Redis
    reclaims memory for one-shot clients.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, Response, status

from pokeprice_api.auth import AuthContext, get_auth_context

# Lua is the atomicity primitive here. We read (tokens, ts), refill by
# (now - ts) * rate, try to deduct cost, write back. Returning the retry
# delay lets callers render a correct Retry-After even under race conditions.
TOKEN_BUCKET_SCRIPT = """
local key       = KEYS[1]
local capacity  = tonumber(ARGV[1])
local rate      = tonumber(ARGV[2])
local now       = tonumber(ARGV[3])
local cost      = tonumber(ARGV[4])

local data   = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts     = now
end

local delta = math.max(0, now - ts)
tokens = math.min(capacity, tokens + delta * rate)

local allowed = 0
local retry_after = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  -- seconds until enough tokens are back
  if rate > 0 then
    retry_after = math.ceil((cost - tokens) / rate)
  else
    retry_after = 1
  end
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / math.max(rate, 0.001)) + 1)
return {allowed, tokens, retry_after}
"""


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
    """Parse a ``tier:capacity:rate,tier:capacity:rate,…`` spec.

    ``free`` is mandatory — it's both the anonymous tier and the fallback
    when a key's ``tier`` string isn't known to this process.
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


class RateLimiter:
    """Redis token-bucket limiter. One instance per process is plenty."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        buckets: dict[str, Bucket],
    ) -> None:
        self.redis = redis_client
        self.buckets = buckets
        self._script = redis_client.register_script(TOKEN_BUCKET_SCRIPT)

    def _bucket_for(self, tier: str) -> Bucket:
        return self.buckets.get(tier) or self.buckets["free"]

    async def check(self, tier: str, identifier: str, cost: int = 1) -> Decision:
        bucket = self._bucket_for(tier)
        key = f"rl:{tier}:{identifier}"
        now = time.time()
        raw = await self._script(
            keys=[key],
            args=[bucket.capacity, bucket.rate, now, cost],
        )
        # redis-py returns ints/bytes depending on connection settings; coerce.
        allowed = int(raw[0]) == 1
        remaining = max(int(float(raw[1])), 0)
        retry_after = max(int(raw[2]), 0)
        return Decision(
            allowed=allowed,
            remaining=remaining,
            retry_after=retry_after,
            bucket=bucket,
        )


def get_rate_limiter(request: Request) -> RateLimiter:
    """Fetch the process-wide :class:`RateLimiter` from ``app.state``.

    Tests override this dep to install a fake; production installs the real
    one in the FastAPI lifespan.
    """
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        raise RuntimeError("rate limiter not installed on app.state; check the FastAPI lifespan")
    return limiter


async def rate_limit_dep(
    response: Response,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AuthContext:
    """Rate-limit the current request and stamp ``X-RateLimit-*`` headers.

    Returns the :class:`AuthContext` so routers that depend on this can
    reuse the resolved identity without re-running the auth lookup.
    """
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
