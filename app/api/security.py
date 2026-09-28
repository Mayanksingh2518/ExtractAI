"""Optional API-key authentication and per-client rate limiting for the document endpoint.

Both are configured in .env (API_KEYS, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS) and stored
on app.state in app/main.py. They run before the request body is validated, so a caller without
a valid key learns nothing about the request format and never costs a download or a model call.
(Only a body that isn't JSON at all is rejected first, with a 422: FastAPI parses JSON before
dependencies run. That 422 echoes nothing and costs nothing.)
"""

import hashlib
import hmac
import logging
import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="Required when the server sets API_KEYS."
)


class RateLimiter:
    """Sliding window: at most max_requests per window_seconds for each client.

    Kept in memory, so the limit is per server process (run one worker, or put a shared
    limiter in front if you run several).
    """

    def __init__(self, max_requests: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, client: str) -> float | None:
        """Record a request. None if it is allowed, otherwise the seconds until the client may retry."""
        now = self._clock()
        if len(self._hits) > 10_000:
            self._forget_idle(now)
        hits = self._hits.setdefault(client, deque())
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return hits[0] + self.window_seconds - now
        hits.append(now)
        return None

    def _forget_idle(self, now: float) -> None:
        """Drop clients with no request inside the window, so memory can't grow without limit."""
        for client in [c for c, hits in self._hits.items() if not hits or hits[-1] <= now - self.window_seconds]:
            del self._hits[client]


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is not used: any caller can set it. Behind a proxy, rate-limit at the proxy.
    return request.client.host if request.client else "unknown"


async def authorize(request: Request, api_key: str | None = Security(api_key_header)) -> str:
    """Check the API key (if keys are configured) and the rate limit. Returns the client id."""
    keys: tuple[str, ...] = request.app.state.api_keys
    if keys:
        # compare_digest takes the same time however much of the key matches.
        if not api_key or not any(hmac.compare_digest(api_key.encode(), key.encode()) for key in keys):
            logger.warning("Rejected request without a valid API key from %s", _client_ip(request))
            raise HTTPException(401, "missing or invalid API key", headers={"WWW-Authenticate": "APIKey"})
        # A hash, so the key itself is not kept around as a dictionary key.
        client = "key:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
    else:
        client = "ip:" + _client_ip(request)

    limiter: RateLimiter | None = request.app.state.rate_limiter
    if limiter is not None:
        retry_after = limiter.hit(client)
        if retry_after is not None:
            logger.warning("Rate limit reached for %s", client)
            raise HTTPException(
                429, "too many requests, try again later", headers={"Retry-After": str(max(1, math.ceil(retry_after)))}
            )
    return client
