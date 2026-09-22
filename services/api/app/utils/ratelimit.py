"""In-memory sliding-window rate limiter. Pure; no I/O.

State lives in the process, so the limits are per worker. That is enough to blunt
credential stuffing against a single API instance; multi-worker deployments put a shared
limiter (reverse proxy or gateway) in front as well.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

_SWEEP_EVERY = 1024


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until the oldest counted attempt leaves the window


class SlidingWindowLimiter:
    def __init__(
        self, *, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = float(window_seconds)
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._ops = 0

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    def check(self, key: str) -> Decision:
        if not self.enabled:
            return Decision(True, remaining=-1, retry_after=0)
        now = self._clock()
        bucket = self._prune(key, now)
        count = len(bucket)
        if count < self._limit:
            return Decision(True, remaining=self._limit - count, retry_after=0)
        wait = max(1, int(bucket[0] + self._window - now + 0.999))
        return Decision(False, remaining=0, retry_after=wait)

    def hit(self, key: str) -> None:
        if not self.enabled:
            return
        now = self._clock()
        self._prune(key, now).append(now)
        self._maybe_sweep(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    # -- internals ------------------------------------------------------------------------------

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._hits.setdefault(key, deque())
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def _maybe_sweep(self, now: float) -> None:
        """Drop keys whose attempts have all expired so memory stays bounded."""
        self._ops += 1
        if self._ops % _SWEEP_EVERY:
            return
        cutoff = now - self._window
        for key in [k for k, b in self._hits.items() if not b or b[-1] <= cutoff]:
            del self._hits[key]
