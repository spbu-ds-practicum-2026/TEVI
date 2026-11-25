from itertools import count

from fastapi import Request, Response

from ..config import Config
from ..services.liveness_view import LivenessView
from ..services.round_robin_balancer import RoundRobinBalancer
from ..services.upstream_client import UpstreamClient
from ..services.upstream_errors import UpstreamConnectionError, UpstreamError, UpstreamTimeoutError


class ClientHandler:
    def __init__(
        self,
        config: Config,
        liveness_view: LivenessView,
        balancer: RoundRobinBalancer,
        upstream_client: UpstreamClient,
    ) -> None:
        self._config = config
        self._liveness_view = liveness_view
        self._balancer = balancer
        self._upstream_client = upstream_client
        self._request_ids = count(1)

    async def handle(self, request: Request) -> Response:
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            return Response(status_code=400)

        request_id = request.headers.get("X-Request-Id")
        if request_id is None:
            request_id = str(next(self._request_ids))
        elif not request_id:
            return Response(status_code=400)

        body = await request.body()
        attempted_nodes: set[str] = set()
        for _ in range(self._config.r_max + 1):
            candidates = [
                node_id for node_id in self._liveness_view.live_nodes()
                if node_id not in attempted_nodes
            ]
            node_id = self._balancer.pick(user_id, candidates)
            if node_id is None:
                return Response(status_code=503)

            node_addr = self._config.nodes[node_id]
            attempted_nodes.add(node_id)
            try:
                upstream_response = await self._upstream_client.check(
                    node_addr=node_addr,
                    user_id=user_id,
                    request_id=request_id,
                    body=body,
                )
            except (UpstreamTimeoutError, UpstreamConnectionError):
                continue
            except UpstreamError:
                return Response(status_code=503)

            if upstream_response.status_code == 503:
                continue

            content_type = upstream_response.headers.get("Content-Type")
            headers = {"Content-Type": content_type} if content_type is not None else None
            return Response(
                content=upstream_response.content,
                status_code=upstream_response.status_code,
                headers=headers,
            )
        return Response(status_code=503)
