import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding-window limit per key, held in memory.

    Only correct for a single server process. Move it to Redis once Redis exists (step 10).
    """

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: defaultdict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> None:
        """Record an attempt, or raise 429 if the key is over its limit."""
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.max_attempts:
            retry_after = int(attempts[0] + self.window_seconds - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
        attempts.append(now)

    def reset(self) -> None:
        self._attempts.clear()


login_limiter = RateLimiter(max_attempts=5, window_seconds=60)


def client_ip(request: Request) -> str:
    # Behind a proxy in production, run uvicorn with --proxy-headers so this is the real IP.
    return request.client.host if request.client else "unknown"
