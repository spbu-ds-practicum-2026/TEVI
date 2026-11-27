import logging
import time

from fastapi import HTTPException

from ..config import Config
from ..models.gossip import GossipRequest, GossipResponse, validate_gossip_context
from ..services.liveness_view import LivenessView
from ..services.node_registry import NodeRegistry


logger = logging.getLogger(__name__)


class GossipReceiver:
    def __init__(
        self,
        config: Config,
        registry: NodeRegistry,
        liveness_view: LivenessView,
    ) -> None:
        self._config = config
        self._registry = registry
        self._liveness_view = liveness_view

    def handle(self, request: GossipRequest) -> GossipResponse:
        try:
            validate_gossip_context(request, self._config.nodes.keys())
        except ValueError as exc:
            logger.error("%s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        self._registry.put(request.sender, request.table, time.monotonic())
        return GossipResponse(
            table=[],
            is_in_active=self._liveness_view.is_in_active(request.sender),
            continuously_live=self._liveness_view.continuously_live(request.sender),
        )
