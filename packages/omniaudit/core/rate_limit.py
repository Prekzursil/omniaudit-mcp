from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class InMemoryRateLimiter:
    limit_per_minute: int
    window_seconds: int = 60
    _events: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque), init=False)

    def allow(self, bucket: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        q = self._events[bucket]
        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= self.limit_per_minute:
            return False

        q.append(now)
        return True
