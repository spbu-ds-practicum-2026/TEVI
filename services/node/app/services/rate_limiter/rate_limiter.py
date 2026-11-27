from .limit_decision import LimitDecision
from .window_store import WindowStore
from .quota_calculator import QuotaCalculator

from collections.abc import Callable
from time import monotonic_ns

class RateLimiter:
    def __init__(
        self,
        store: WindowStore,
        quota_calculator: QuotaCalculator,
        clock_ns: Callable[[], int] = monotonic_ns
    ):
        self.store = store
        self.quota_calculator = quota_calculator
        self.clock_ns = clock_ns

    def allow(self, user_id: str) -> LimitDecision:
        now_ns = self.clock_ns()
        n_0, q = self.quota_calculator.quota_ns(now_ns)
        user_req = self.store.prune_and_count(user_id, now_ns)

        if(user_req < q):
            self.store.record(user_id, now_ns)
            return LimitDecision(True, n_0, q, now_ns)
        else:
            return LimitDecision(False, n_0, q, None)
