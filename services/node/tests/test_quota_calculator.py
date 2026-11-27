import pytest
from app.services.rate_limiter.quota_calculator import QuotaCalculator

@pytest.fixture
def quota_calculator():
    return [QuotaCalculator(10, 3), QuotaCalculator(9, 3)]

def test_accept(quota_calculator):
    assert all(x.quota_ns(3) == (3, 3) for x in quota_calculator)
