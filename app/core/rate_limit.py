"""
Per-tenant token-bucket rate limiting via Redis. Each tenant gets an
independent bucket keyed by tenant_id, so one tenant hammering the API
can never starve another's requests (the "noisy neighbor" problem the
handbook calls out).

Implemented as a single atomic Lua script so the check-and-decrement is
race-free under concurrent requests from the same tenant.
"""
import os
import time

import redis
from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_tenant
from app.models.db import Tenant

redis_client = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

# Bucket config: capacity = burst allowance, refill_rate = tokens/second
DEFAULT_CAPACITY = 60          # e.g. 60 requests
DEFAULT_REFILL_RATE = 1.0      # refills at 1 token/sec -> ~60 req/min sustained

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'timestamp')
local tokens = tonumber(bucket[1])
local timestamp = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  timestamp = now
end

-- refill based on elapsed time
local elapsed = math.max(0, now - timestamp)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'timestamp', now)
redis.call('EXPIRE', key, 3600)

return {allowed, tokens}
"""
_token_bucket_script = redis_client.register_script(_TOKEN_BUCKET_LUA)


def check_rate_limit(tenant_id: str, cost: int = 1,
                      capacity: int = DEFAULT_CAPACITY,
                      refill_rate: float = DEFAULT_REFILL_RATE) -> None:
    """Raises 429 if the tenant's bucket doesn't have `cost` tokens available."""
    key = f"rate_limit:{tenant_id}"
    allowed, remaining = _token_bucket_script(
        keys=[key], args=[capacity, refill_rate, time.time(), cost]
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for tenant. Retry shortly. "
                   f"({remaining:.1f} tokens remaining)",
            headers={"Retry-After": "5"},
        )


def rate_limited_tenant(tenant: Tenant = Depends(get_current_tenant)) -> Tenant:
    """FastAPI dependency combining auth + rate limiting in one step."""
    check_rate_limit(str(tenant.id))
    return tenant
