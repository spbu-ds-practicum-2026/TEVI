from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

Handler = Callable[[bytes, dict], Any]


class TransportError(Exception):

    def __init__(self, addr: str, path: str, reason: str) -> None:
        super().__init__(f"{addr}{path}: {reason}")
        self.addr = addr
        self.path = path
        self.reason = reason


class TransportTimeout(TransportError):
    pass


def _url(addr: str, path: str) -> str:
    base = addr if addr.startswith(("http://", "https://")) else f"http://{addr}"
    return base.rstrip("/") + path


class Transport:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        *,
        default_timeout_s: float = 0.5,
    ) -> None:
        self._host = host
        self._port = port
        self._default_timeout_s = default_timeout_s
        self._app = FastAPI()
        self._client: Optional[httpx.AsyncClient] = None
        self._server: Optional[uvicorn.Server] = None

        self._app.get("/health")(self._health)

    # --- сервер ---

    async def _health(self) -> dict:
        return {"status": "ok"}

    def register(self, path: str, handler: Handler) -> None:

        async def endpoint(request: Request) -> Response:
            raw = await request.body()
            headers = {k.lower(): v for k, v in request.headers.items()}
            try:
                result = handler(raw, headers)
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                log.exception("handler %s failed", path)
                return JSONResponse({"error": "internal error"}, status_code=500)

            if (isinstance(result, tuple) and len(result) >= 2
                    and isinstance(result[0], int)):
                status, body = result[0], result[1]
                ctype = result[2] if len(result) >= 3 else None
                if isinstance(body, (bytes, bytearray)):
                    resp = Response(content=bytes(body), status_code=status)
                    if ctype is not None:
                        resp.headers["content-type"] = ctype
                    return resp      
                return JSONResponse(body, status_code=status)

            if isinstance(result, (bytes, bytearray)):
                return Response(content=bytes(result), status_code=200)
            return JSONResponse(result)

        self._app.add_api_route(path, endpoint, methods=["POST"], name=path)

    async def start(self) -> None:
        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    # --- клиент ---

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def post(
        self,
        addr: str,
        path: str,
        payload: dict,
        *,
        timeout_s: Optional[float] = None,
    ) -> dict:
        client = self._get_client()
        timeout = timeout_s if timeout_s is not None else self._default_timeout_s
        try:
            resp = await client.post(_url(addr, path), json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise TransportTimeout(addr, path, "timeout") from exc
        except httpx.HTTPError as exc:
            raise TransportError(addr, path, str(exc)) from exc

        if resp.status_code != 200:
            raise TransportError(addr, path, f"http {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise TransportError(addr, path, "invalid json") from exc
        if not isinstance(data, dict):
            raise TransportError(addr, path, "expected json object")
        return data

    async def post_raw(
        self,
        addr: str,
        path: str,
        body: bytes,
        *,
        timeout_s: Optional[float] = None,
        headers: Optional[dict] = None,
    ) -> tuple[int, bytes, Optional[str]]:
        client = self._get_client()
        timeout = timeout_s if timeout_s is not None else self._default_timeout_s
        try:
            resp = await client.post(
                _url(addr, path), content=body, timeout=timeout, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise TransportTimeout(addr, path, "timeout") from exc
        except httpx.HTTPError as exc:
            raise TransportError(addr, path, str(exc)) from exc
        return resp.status_code, resp.content, resp.headers.get("content-type")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._server is not None:
            self._server.should_exit = True
