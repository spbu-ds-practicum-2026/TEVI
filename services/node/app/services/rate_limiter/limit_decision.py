from typing import Optional

class LimitDecision:
    def __init__(self, allowed: bool, n: int, q: int, admitted_at_ns: Optional[int]):
        self.allowed = allowed
        self.n = n
        self.q = q
        self.admitted_at_ns = admitted_at_ns
