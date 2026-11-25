from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from .clients.client_handler import ClientHandler
from .config import Config
from .services.liveness_view import LivenessView
from .services.round_robin_balancer import RoundRobinBalancer
from .services.upstream_client import UpstreamClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = Config.from_env()
    app.state.config = config
    app.state.liveness_view = LivenessView(config)
    app.state.balancer = RoundRobinBalancer()
    async with httpx.AsyncClient() as http_client:
        app.state.upstream_client = UpstreamClient(http_client, config.t_req)
        app.state.client_handler = ClientHandler(
            config, app.state.liveness_view, app.state.balancer, app.state.upstream_client
        )
        yield


app = FastAPI(openapi_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/check")
async def check(request: Request) -> Response:
    return await request.app.state.client_handler.handle(request)
