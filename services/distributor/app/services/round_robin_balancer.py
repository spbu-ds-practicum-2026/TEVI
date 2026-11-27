from collections import Counter


class RoundRobinBalancer:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def pick(self, user_id: str, live_nodes: list[str]) -> str | None:
        if not live_nodes:
            return None

        nodes = sorted(live_nodes)
        count = self._counts[user_id]
        node = nodes[count % len(nodes)]
        self._counts[user_id] += 1
        return node
