from collections import defaultdict, deque

import pytest

from app.services.rate_limiter.quota_calculator import QuotaCalculator
from app.services.rate_limiter.rate_limiter import RateLimiter
from app.services.rate_limiter.window_store import WindowStore


@pytest.mark.parametrize(("limit", "nodes", "quota"), [(100, 4, 25), (10, 4, 2), (4, 4, 1)])
def test_fixed_quota_rounds_down_and_is_independent_of_time(limit, nodes, quota):
    calculator = QuotaCalculator(limit, nodes)

    assert calculator.quota_ns(0) == (nodes, quota)
    assert calculator.quota_ns(10_000_000_000) == (nodes, quota)


def test_users_have_independent_quotas_and_decisions_expose_quota():
    store = WindowStore(10, 10, defaultdict(deque))
    limiter = RateLimiter(store, QuotaCalculator(3, 2), clock_ns=lambda: 4)

    first = limiter.allow("alice")
    denied = limiter.allow("alice")
    other = limiter.allow("bob")

    assert (first.allowed, first.n, first.q, first.admitted_at_ns) == (True, 2, 1, 4)
    assert (denied.allowed, denied.n, denied.q, denied.admitted_at_ns) == (False, 2, 1, None)
    assert other.allowed


def test_rejected_requests_do_not_extend_the_window():
    now_ns = 0
    store = WindowStore(10, 10, defaultdict(deque))
    limiter = RateLimiter(store, QuotaCalculator(1, 1), clock_ns=lambda: now_ns)

    assert limiter.allow("alice").allowed
    now_ns = 9
    assert not limiter.allow("alice").allowed
    now_ns = 10
    assert not limiter.allow("alice").allowed
    now_ns = 11
    assert limiter.allow("alice").admitted_at_ns == 11


def test_idle_cleanup_does_not_release_quota_at_the_window_boundary():
    now_ns = 0
    store = WindowStore(10, 10, defaultdict(deque))
    limiter = RateLimiter(store, QuotaCalculator(1, 1), clock_ns=lambda: now_ns)
    assert limiter.allow("alice").allowed

    now_ns = 10
    assert store.evict_idle(now_ns) == 0
    assert not limiter.allow("alice").allowed
    now_ns = 11
    assert store.evict_idle(now_ns) == 1
    assert limiter.allow("alice").allowed


def test_idle_cleanup_uses_last_admission_and_leaves_active_user_intact():
    windows = defaultdict(deque)
    store = WindowStore(10, 20, windows)
    store.record("idle", 0)
    store.record("active", 0)
    store.record("active", 15)

    assert store.evict_idle(20) == 0
    assert store.evict_idle(21) == 1
    assert "idle" not in windows
    assert store.prune_and_count("active", 21) == 1
    assert store.evict_idle(21) == 0


def test_count_for_unknown_user_does_not_create_empty_window():
    windows = defaultdict(deque)
    store = WindowStore(10, 10, windows)

    assert store.prune_and_count("unknown", 0) == 0
    assert not windows
