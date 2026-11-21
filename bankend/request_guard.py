import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> float | None:
        """Return None when allowed, otherwise seconds until the next slot."""
        current = time.monotonic() if now is None else now
        requests = self._requests[key]
        cutoff = current - self.window_seconds
        while requests and requests[0] <= cutoff:
            requests.popleft()

        if len(requests) < self.limit:
            requests.append(current)
            return None

        return max(0.1, self.window_seconds - (current - requests[0]))
