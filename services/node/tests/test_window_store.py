from app.services.rate_limiter.window_store import WindowStore

from collections import defaultdict, deque
import pytest

window_ns = 10
idle_ttl_ns = 10

@pytest.fixture
def stores():
    return  [
                WindowStore(window_ns, idle_ttl_ns, defaultdict(deque, {"A" : deque()})),
                WindowStore(window_ns, idle_ttl_ns, defaultdict(deque, {"B" : deque([5, 5, 8])}))
            ]

def test_prune_and_count(stores):
    assert stores[0].prune_and_count("A", 15) == 0
    assert "A" not in stores[0].windows 
    assert stores[1].prune_and_count("A", 15) == 0
    assert stores[1].prune_and_count("B", 15) == 3
    assert stores[1].prune_and_count("B", 16) == 1
    assert stores[1].prune_and_count("B", 30) == 0

def test_record(stores):
    stores[0].record("A", 10)
    assert stores[0].prune_and_count("A", 11) == 1

    stores[1].record("B", 16)
    assert stores[1].prune_and_count("B", 16) == 2

def test_rejects_ttl_shorter_than_window():
    with pytest.raises(ValueError, match="idle_ttl_ns must be at least window_ns"):
        WindowStore(10, 5, defaultdict(deque))


def test_evict_idle(stores):
    stores[1].record("A", 14)
    assert stores[0].evict_idle(10) == 1
    assert stores[1].evict_idle(18) == 0
    assert stores[1].evict_idle(19) == 1
