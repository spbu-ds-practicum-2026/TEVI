from ..models.gossip import NodeEntry


class NodeRegistry:
    """
    Stores the latest gossip table received from each node.

    Stored and returned tables must be treated as read-only.
    No defensive copies are made.
    """

    def __init__(self) -> None:
        self._tables: dict[str, tuple[list[NodeEntry], float]] = {}

    def put(self, node_id: str, table: list[NodeEntry], ts: float) -> None:
        self._tables[node_id] = (table, ts)

    def latest(self, node_id: str) -> tuple[list[NodeEntry], float] | None:
        return self._tables.get(node_id)

    def all_fresh(self, now: float, t_view: float) -> dict[str, list[NodeEntry]]:
        return {
            node_id: table
            for node_id, (table, received_at) in self._tables.items()
            if now - received_at <= t_view
        }
