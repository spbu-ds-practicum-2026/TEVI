import asyncio

import httpx
import pytest

from app.main import app
from app.services.upstream_client import UpstreamClient
from app.services.upstream_errors import (
    UpstreamConnectionError,
    UpstreamPoolTimeoutError,
    UpstreamTimeoutError,
)


@pytest.mark.parametrize("status", [200, 429, 503, 307])
def test_check_sends_one_post_and_returns_original_response(status):
    body = b"\x00\xff{\"x\": 1}\n"
    response = httpx.Response(
        status, content=b"\x00upstream\xff", headers={"Location": "/other"}
    )
    requests = []

    def handle(request):
        requests.append(request)
        return response

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), follow_redirects=True
        ) as client:
            upstream = UpstreamClient(client, t_req=2)
            actual = await upstream.check("http://node1:8080", "alice", "req-1", body)
            assert not client.is_closed
            return actual

    actual = asyncio.run(check())

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == "http://node1:8080/internal/check"
    assert request.headers["X-User-Id"] == "alice"
    assert request.headers["X-Request-Id"] == "req-1"
    assert request.content == body
    assert actual is response
    assert actual.status_code == status
    assert actual.content == b"\x00upstream\xff"


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("http://node/", "http://node/internal/check"),
        ("http://node/gateway", "http://node/gateway/internal/check"),
        ("http://node/gateway/internal/check/", "http://node/gateway/internal/check"),
        (
            "https://node/gateway%2Fv1/?region=a%2Fb#local",
            "https://node/gateway%2Fv1/internal/check?region=a%2Fb",
        ),
    ],
)
def test_check_builds_url(address, expected):
    def handle(request):
        assert request.url == expected
        return httpx.Response(200)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await UpstreamClient(client, t_req=2).check(address, "alice", "req-1", b"")

    asyncio.run(check())


@pytest.mark.parametrize(
    ("original_error", "expected_error"),
    [
        (httpx.ConnectTimeout, UpstreamTimeoutError),
        (httpx.ReadTimeout, UpstreamTimeoutError),
        (httpx.WriteTimeout, UpstreamTimeoutError),
        (httpx.ConnectError, UpstreamConnectionError),
        (httpx.ReadError, UpstreamConnectionError),
        (httpx.RemoteProtocolError, UpstreamConnectionError),
        (httpx.PoolTimeout, UpstreamPoolTimeoutError),
    ],
)
def test_check_classifies_transport_errors(original_error, expected_error):
    original = original_error("test failure")
    attempts = 0

    def handle(request):
        nonlocal attempts
        attempts += 1
        raise original

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            upstream = UpstreamClient(client, t_req=2)
            with pytest.raises(expected_error) as caught:
                await upstream.check("http://node", "alice", "req-1", b"")
            assert caught.value.__cause__ is original

    asyncio.run(check())
    assert attempts == 1


def test_check_deadline_includes_reading_response_body():
    reading_body = False

    class BlockingBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal reading_body
            reading_body = True
            await asyncio.Event().wait()
            yield b""

    def handle(request):
        return httpx.Response(200, stream=BlockingBody())

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            upstream = UpstreamClient(client, t_req=0.02)
            with pytest.raises(UpstreamTimeoutError) as caught:
                await upstream.check("http://node", "alice", "req-1", b"")
            assert isinstance(caught.value.__cause__, TimeoutError)

    asyncio.run(check())
    assert reading_body


def test_check_propagates_external_cancellation():
    async def check():
        started = asyncio.Event()

        async def handle(request):
            started.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            upstream = UpstreamClient(client, t_req=2)
            task = asyncio.create_task(
                upstream.check("http://node", "alice", "req-1", b"")
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(check())


@pytest.mark.parametrize("shutdown_error", [False, True])
def test_lifespan_owns_and_closes_one_http_client(monkeypatch, tmp_path, shutdown_error):
    config_path = tmp_path / "cluster.json"
    config_path.write_text(
        '{"n0":1,"nodes":{"n1":"http://node"},"t_req":0.5,"R_max":0}', encoding="utf-8"
    )
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setattr(app, "state", type(app.state)())
    created_clients = []
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200)

    async_client = httpx.AsyncClient

    def create_client():
        client = async_client(transport=httpx.MockTransport(handle))
        created_clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", create_client)

    async def check():
        async with app.router.lifespan_context(app):
            upstream = app.state.upstream_client
            assert isinstance(upstream, UpstreamClient)
            for request_id in ("req-1", "req-2"):
                await upstream.check("http://node", "alice", request_id, b"")
            assert len(created_clients) == 1
            assert not created_clients[0].is_closed
            if shutdown_error:
                raise RuntimeError("shutdown error")

    if shutdown_error:
        with pytest.raises(RuntimeError, match="shutdown error"):
            asyncio.run(check())
    else:
        asyncio.run(check())

    assert len(requests) == 2
    assert requests[0].extensions["timeout"]["read"] == 0.5
    assert created_clients[0].is_closed
