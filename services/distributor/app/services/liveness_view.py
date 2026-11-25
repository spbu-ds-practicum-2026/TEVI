from ..config import Config


class LivenessView:
    def __init__(self, config: Config) -> None:
        self._config = config

    def live_nodes(self) -> list[str]:
        return list(self._config.nodes)
