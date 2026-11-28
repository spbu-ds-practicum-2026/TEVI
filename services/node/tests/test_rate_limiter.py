from app.services.rate_limiter.rate_limiter import RateLimiter
from app.services.rate_limiter.quota_calculator import QuotaCalculator
from app.services.rate_limiter.window_store import WindowStore

from collections import defaultdict

import pytest

def test_limiter():
    store = WindowStore(10, 10, defaultdict()) 
    quota_calculator = QuotaCalculator(9, 3)
    now_ns = 0
    limiter = RateLimiter(store, quota_calculator, clock_ns = lambda: now_ns)

    assert limiter.allow("A").admitted_at_ns == 0
    now_ns = 5
    for i in range(2):
        assert limiter.allow("A").admitted_at_ns == 5
    
    assert limiter.allow("A").allowed == False

    now_ns = 11
    assert limiter.allow("A").admitted_at_ns == 11
