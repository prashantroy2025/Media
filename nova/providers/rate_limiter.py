"""Token-Bucket Rate Limiter per Provider."""

import threading
import time


class TokenBucketRateLimiter:
    """Thread-safe token-bucket rate limiter."""

    def __init__(self, requests_per_minute: int = 60):
        self.capacity = float(requests_per_minute)
        self.tokens = float(requests_per_minute)
        self.fill_rate = float(requests_per_minute) / 60.0  # tokens per second
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: float = 10.0) -> bool:
        """Acquires a single token, optionally blocking until available."""
        start_time = time.monotonic()
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

                if not blocking:
                    return False

                sleep_time = (1.0 - self.tokens) / self.fill_rate

            if time.monotonic() - start_time + sleep_time > timeout:
                return False

            time.sleep(min(sleep_time, 0.5))
