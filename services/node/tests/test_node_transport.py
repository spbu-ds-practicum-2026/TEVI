import asyncio
import json

import httpx
import pytest

from app.transport import Transport, TransportError, TransportTimeout


def test_post_sends_gossip_request_and_decodes_object(monkeypatch):
    def upstream(request):
        assert str(request.url) == "http://peer:8080/internal/gossip"
        assert request.method == "POST"
        assert json.loads(request.content) == {"table": []}
        assert request.extensions["timeout"]["read"] == 0.25
        return httpx.Response(200, json={"table": []})

    async def scenario():
        transport = Transport()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            monkeypatch.setattr(transport, "_get_client", lambda: client)
            result = await transport.post("peer:8080", "/internal/gossip", {"table": []}, timeout_s=0.25)
            assert result == {"table": []}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (503, b"{}", "http 503"),
        (200, b"not JSON", "invalid json"),
        (200, b"[]", "expected json object"),
    ],
)
def test_post_rejects_invalid_gossip_reply(monkeypatch, status, body, reason):
    async def scenario():
        transport = Transport()
        mock = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
        async with httpx.AsyncClient(transport=mock) as client:
            monkeypatch.setattr(transport, "_get_client", lambda: client)
            with pytest.raises(TransportError, match=reason):
                await transport.post("peer:8080", "/internal/gossip", {})

    asyncio.run(scenario())


def test_post_raw_preserves_request_and_response(monkeypatch):
    def upstream(request):
        assert str(request.url) == "http://target:8080/handle"
        assert request.headers["content-type"] == "application/octet-stream"
        assert request.content == b"\x00\xff"
        return httpx.Response(409, content=b"conflict", headers={"Content-Type": "text/plain"})

    async def scenario():
        transport = Transport()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            monkeypatch.setattr(transport, "_get_client", lambda: client)
            response = await transport.post_raw(
                "target:8080", "/handle", b"\x00\xff", headers={"Content-Type": "application/octet-stream"},
            )
            assert response == (409, b"conflict", "text/plain")

    asyncio.run(scenario())


def test_post_raw_maps_httpx_timeout(monkeypatch):
    def upstream(request):
        raise httpx.ReadTimeout("timed out", request=request)

    async def scenario():
        transport = Transport()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            monkeypatch.setattr(transport, "_get_client", lambda: client)
            with pytest.raises(TransportTimeout) as error:
                await transport.post_raw("target:8080", "/handle", b"")
            assert error.value.addr == "target:8080"
            assert error.value.path == "/handle"

    asyncio.run(scenario())
