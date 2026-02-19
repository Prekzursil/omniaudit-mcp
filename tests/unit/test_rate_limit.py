import time

from omniaudit.core.rate_limit import InMemoryRateLimiter


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = InMemoryRateLimiter(limit_per_minute=2)

    assert limiter.allow("scan") is True
    assert limiter.allow("scan") is True
    assert limiter.allow("scan") is False


def test_rate_limiter_allows_after_window_passes() -> None:
    limiter = InMemoryRateLimiter(limit_per_minute=1, window_seconds=1)

    assert limiter.allow("github-write") is True
    assert limiter.allow("github-write") is False
    time.sleep(1.05)
    assert limiter.allow("github-write") is True
