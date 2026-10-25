"""Spreads search starts per source so one job board is not hit by many requests at once."""
import random
import threading
import time
from collections.abc import Callable


class StartSpacer:
    """Consecutive starts for the same key are at least a random gap (uniform in `gap`) apart.

    `delay()` reserves the next start slot and returns how long to wait for it (0 if free now).
    Thread-safe; the gap is measured from the previous reserved start, not from now.
    """

    def __init__(self, *, rng: random.Random | None = None, clock: Callable[[], float] = time.monotonic):
        self._rng = rng or random.Random()
        self._clock = clock
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def delay(self, key: str, gap: tuple[float, float]) -> float:
        low = max(0.0, float(gap[0]))
        high = max(low, float(gap[1]))
        with self._lock:
            now = self._clock()
            start = max(now, self._next.get(key, now))
            self._next[key] = start + (self._rng.uniform(low, high) if high > 0 else 0.0)
            return start - now
