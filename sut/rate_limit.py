"""Sliding-window in-memory rate limiter with injectable deterministic clock."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    """Decision metadata returned by the sliding-window rate limiter."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """Thread-safe-for-single-worker sliding-window request rate limiter."""

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitResult:
        """Record an attempt for `key` if under quota and return decision headers."""
        now = self._clock()
        cutoff = now - self._window_seconds
        bucket = self._hits[key]

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            oldest = bucket[0]
            retry_after = max(1, math.ceil(self._window_seconds - (now - oldest)))
            return RateLimitResult(
                allowed=False,
                limit=self._max_requests,
                remaining=0,
                retry_after_seconds=retry_after,
            )

        bucket.append(now)
        remaining = max(0, self._max_requests - len(bucket))
        return RateLimitResult(
            allowed=True,
            limit=self._max_requests,
            remaining=remaining,
            retry_after_seconds=0,
        )

    def reset(self) -> None:
        """Clear all tracked rate-limit windows."""
        self._hits.clear()
