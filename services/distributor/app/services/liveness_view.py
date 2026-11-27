from ..config import Config


class LivenessView:
    def __init__(self, config: Config) -> None:
        self._config = config

    def live_nodes(self) -> list[str]:
        return list(self._config.nodes)

    def is_in_active(self, node_id: str) -> bool:
        """Temporarily treat every node as part of the active group."""
        return True

    def continuously_live(self, node_id: str) -> bool:
        """Temporarily treat every node as continuously live."""
        return True
