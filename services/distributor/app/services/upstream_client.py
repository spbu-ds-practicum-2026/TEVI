import asyncio

import httpx

from .upstream_errors import (
    UpstreamConnectionError,
    UpstreamPoolTimeoutError,
    UpstreamTimeoutError,
)


class UpstreamClient:
    def __init__(self, client: httpx.AsyncClient, t_req: float) -> None:
        self._client = client
        self._t_req = t_req

    async def check(
        self, node_addr: str, user_id: str, request_id: str, body: bytes
    ) -> httpx.Response:
        url = httpx.URL(node_addr)
        path, separator, query = url.raw_path.partition(b"?")
        path = path.rstrip(b"/")
        endpoint = b"/internal/check"
        if not path.endswith(endpoint):
            path += endpoint
        url = url.copy_with(raw_path=path + separator + query, fragment=None)

        try:
            async with asyncio.timeout(self._t_req):
                return await self._client.post(
                    url,
                    headers={"X-User-Id": user_id, "X-Request-Id": request_id},
                    content=body,
                    timeout=self._t_req,
                    follow_redirects=False,
                )
        except httpx.PoolTimeout as exc:
            raise UpstreamPoolTimeoutError("Timed out waiting for a pooled connection") from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise UpstreamTimeoutError("Upstream check timed out") from exc
        except (httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise UpstreamConnectionError("Upstream check connection failed") from exc
