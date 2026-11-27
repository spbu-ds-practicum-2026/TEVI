class QuotaCalculator:
    def __init__(self, limit: int, n_0: int):
        self.limit = limit
        self.n_0 = n_0

    def quota_ns(self, now_ns: int) -> tuple[int, int]:
        q = self.limit // self.n_0
        return (self.n_0, q)

    def read_membership(self):
        ...
