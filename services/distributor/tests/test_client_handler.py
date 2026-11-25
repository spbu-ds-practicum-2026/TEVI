import asyncio
from unittest.mock import AsyncMock, Mock, call, create_autospec
from uuid import uuid4

import httpx
import pytest
from fastapi import Request

from app.clients.client_handler import ClientHandler
from app.config import Config
from app.main import app
from app.services.liveness_view import LivenessView
from app.services.round_robin_balancer import RoundRobinBalancer
from app.services.upstream_client import UpstreamClient
from app.services.upstream_errors import (
    UpstreamConnectionError,
    UpstreamError,
    UpstreamPoolTimeoutError,
    UpstreamTimeoutError,
)


@pytest.fixture
def retry_limit():
    return 2


@pytest.fixture
def components(retry_limit):
    config = Config(
        n0=4,
        nodes={f"n{i}": f"http://node{i}" for i in range(1, 5)},
        t_req=2,
        r_max=retry_limit,
    )
    liveness = create_autospec(LivenessView, instance=True)
    liveness.live_nodes.return_value = ["n2"]
    balancer = Mock(spec=RoundRobinBalancer, wraps=RoundRobinBalancer())
    upstream = create_autospec(UpstreamClient, instance=True)
    upstream.check.return_value = httpx.Response(200)
    handler = ClientHandler(config, liveness, balancer, upstream)
    return handler, liveness, balancer, upstream


def make_request(headers, body=b""):
    raw_headers = [
        (name.lower().encode("ascii"), value.encode("latin-1"))
        for name, value in headers.items()
    ]

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "headers": raw_headers}, receive)


@pytest.mark.parametrize("value", [None, ""], ids=["missing", "empty"])
def test_missing_or_empty_user_id_returns_400(components, value):
    handler, liveness, _, upstream = components
    headers = {} if value is None else {"X-User-Id": value}

    response = asyncio.run(handler.handle(make_request(headers)))

    assert response.status_code == 400
    liveness.live_nodes.assert_not_called()
    upstream.check.assert_not_called()


def test_empty_request_id_returns_400(components):
    handler, liveness, _, upstream = components
    headers = {"X-User-Id": "1", "X-Request-Id": ""}

    response = asyncio.run(handler.handle(make_request(headers)))

    assert response.status_code == 400
    liveness.live_nodes.assert_not_called()
    upstream.check.assert_not_called()


@pytest.mark.parametrize(
    ("user_id", "request_id"),
    [
        ("0", "0007"),
        ("1", "0007"),
        ("12345", "0007"),
        ("0012", "0007"),
        ("demo-user", "54BD1178-6227-4AC3-9496-CF58A1B7FB43"),
        ("user_123", "trace:abc"),
        ("alice", "request 42"),
    ],
)
def test_handler_passes_original_ids_body_and_selected_address(components, user_id, request_id):
    handler, liveness, balancer, upstream = components
    headers = {"X-User-Id": user_id, "X-Request-Id": request_id}
    body = b"\x00\xff not JSON\n"

    response = asyncio.run(handler.handle(make_request(headers, body)))

    assert response.status_code == 200
    liveness.live_nodes.assert_called_once_with()
    balancer.pick.assert_called_once_with(user_id, ["n2"])
    upstream.check.assert_awaited_once_with(
        node_addr="http://node2", user_id=user_id, request_id=request_id, body=body
    )


def test_request_id_counter_advances_only_for_generated_ids(components):
    handler, _, _, upstream = components

    async def check():
        for request_id in ("0007", None, "0", None, None):
            headers = {"X-User-Id": "1"}
            if request_id is not None:
                headers["X-Request-Id"] = request_id
            assert (await handler.handle(make_request(headers))).status_code == 200

    asyncio.run(check())

    assert [call.kwargs["request_id"] for call in upstream.check.await_args_list] == [
        "0007", "1", "0", "2", "3",
    ]


def test_no_live_nodes_returns_503_without_upstream_call(components):
    handler, liveness, balancer, upstream = components
    liveness.live_nodes.return_value = []

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == 503
    balancer.pick.assert_called_once_with("1", [])
    upstream.check.assert_not_called()


@pytest.mark.parametrize("error_type", [UpstreamError, UpstreamPoolTimeoutError])
def test_upstream_failure_returns_503_after_one_attempt(components, error_type):
    handler, liveness, balancer, upstream = components
    liveness.live_nodes.return_value = ["n1", "n2"]
    upstream.check.side_effect = error_type("upstream failure")

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == 503
    balancer.pick.assert_called_once()
    upstream.check.assert_awaited_once()


def test_unexpected_error_propagates(components):
    handler, _, _, upstream = components
    upstream.check.side_effect = RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))


@pytest.mark.parametrize("status", [200, 307, 429, 500])
@pytest.mark.parametrize("content_type", [None, "application/octet-stream"])
def test_response_preserves_status_body_and_optional_content_type(components, status, content_type):
    handler, liveness, _, upstream = components
    liveness.live_nodes.return_value = ["n1", "n2"]
    body = b"\x00\xff upstream\n"
    headers = {"Connection": "close", "X-Upstream": "private"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    upstream.check.return_value = httpx.Response(status, content=body, headers=headers)

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == status
    assert response.body == body
    assert response.headers.get("Content-Type") == content_type
    assert "Connection" not in response.headers
    assert "X-Upstream" not in response.headers
    upstream.check.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [503, UpstreamTimeoutError("timeout"), UpstreamConnectionError("connection lost")],
)
def test_retryable_failure_uses_another_node(components, failure):
    handler, liveness, balancer, upstream = components
    liveness.live_nodes.return_value = ["n1", "n2"]
    first_result = httpx.Response(failure) if isinstance(failure, int) else failure
    upstream.check.side_effect = [first_result, httpx.Response(200, content=b"ok")]

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == 200
    assert response.body == b"ok"
    assert [c.kwargs["node_addr"] for c in upstream.check.await_args_list] == [
        "http://node1", "http://node2",
    ]
    assert balancer.pick.call_args_list == [call("1", ["n1", "n2"]), call("1", ["n2"])]
    assert liveness.live_nodes.call_count == 2


@pytest.mark.parametrize(("retry_limit", "attempts"), [(0, 1), (1, 2), (2, 3)])
def test_retry_limit_caps_http_attempts(components, attempts):
    handler, liveness, balancer, upstream = components
    liveness.live_nodes.return_value = ["n1", "n2", "n3", "n4"]
    upstream.check.return_value = httpx.Response(503, content=b"unavailable")

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == 503
    assert response.body == b""
    assert upstream.check.await_count == attempts
    assert balancer.pick.call_count == attempts
    assert liveness.live_nodes.call_count == attempts


@pytest.mark.parametrize("retry_limit", [5])
def test_retries_stop_when_all_unique_nodes_are_used(components):
    handler, liveness, balancer, upstream = components
    liveness.live_nodes.return_value = ["n1", "n2", "n3"]
    upstream.check.side_effect = UpstreamConnectionError("connection lost")

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == 503
    assert [c.kwargs["node_addr"] for c in upstream.check.await_args_list] == [
        "http://node1", "http://node3", "http://node2",
    ]
    assert balancer.pick.call_args_list == [
        call("1", ["n1", "n2", "n3"]),
        call("1", ["n2", "n3"]),
        call("1", ["n2"]),
        call("1", []),
    ]


def test_retry_picks_newly_live_node_from_fresh_list(components):
    handler, liveness, balancer, upstream = components
    liveness.live_nodes.side_effect = [["n1", "n2"], ["n1", "n3"]]
    upstream.check.side_effect = [httpx.Response(503), httpx.Response(200)]

    response = asyncio.run(handler.handle(make_request({"X-User-Id": "1"})))

    assert response.status_code == 200
    assert balancer.pick.call_args_list == [call("1", ["n1", "n2"]), call("1", ["n3"])]
    assert upstream.check.await_args.kwargs["node_addr"] == "http://node3"


@pytest.mark.parametrize(("request_id", "first_id", "next_id"), [
    (None, "1", "2"),
    ("0007", "0007", "1"),
])
def test_retries_reuse_request_data_and_round_robin_continues(
    components, request_id, first_id, next_id
):
    handler, liveness, _, upstream = components
    liveness.live_nodes.return_value = ["n1", "n2"]
    upstream.check.side_effect = [
        httpx.Response(503), httpx.Response(200), httpx.Response(200), httpx.Response(200)
    ]
    headers = {"X-User-Id": "0042"}
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    body = b"\x00\xff original body"
    request = make_request(headers, body)
    request.body = AsyncMock(wraps=request.body)

    async def check():
        assert (await handler.handle(request)).status_code == 200
        for _ in range(2):
            assert (await handler.handle(make_request({"X-User-Id": "0042"}))).status_code == 200

    asyncio.run(check())

    request.body.assert_awaited_once_with()
    assert upstream.check.await_args_list == [
        call(node_addr="http://node1", user_id="0042", request_id=first_id, body=body),
        call(node_addr="http://node2", user_id="0042", request_id=first_id, body=body),
        call(node_addr="http://node1", user_id="0042", request_id=next_id, body=b""),
        call(
            node_addr="http://node2", user_id="0042",
            request_id=str(int(next_id) + 1), body=b"",
        ),
    ]


def test_fastapi_lifespan_and_routes(monkeypatch, tmp_path):
    config_path = tmp_path / "cluster.json"
    config_path.write_text(
        '{"n0":1,"nodes":{"n1":"http://node"},"t_req":2,"R_max":2}', encoding="utf-8"
    )
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setattr(app, "state", type(app.state)())
    requests = []
    generator_request_id = str(uuid4())
    headers_by_request = [
        {"X-User-Id": "0042"},
        {"X-User-Id": "demo-user", "X-Request-Id": generator_request_id},
        {"X-User-Id": "0042"},
    ]

    def respond(request):
        requests.append(request)
        return httpx.Response(429, content=b"quota", headers={"Content-Type": "text/plain"})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda: async_client(transport=httpx.MockTransport(respond))
    )

    async def check():
        async with app.router.lifespan_context(app):
            handler = app.state.client_handler
            assert isinstance(handler, ClientHandler)
            async with async_client(transport=httpx.ASGITransport(app=app), base_url="http://app") as client:
                health = await client.get("/health")
                assert health.status_code == 200
                assert health.json() == {"status": "ok"}
                for headers in headers_by_request:
                    response = await client.post("/v1/check", headers=headers, content=b"request")
                    assert response.status_code == 429
                    assert response.content == b"quota"
                    assert response.headers["Content-Type"] == "text/plain"
                assert app.state.client_handler is handler

    asyncio.run(check())

    assert [request.headers["X-Request-Id"] for request in requests] == [
        "1", generator_request_id, "2",
    ]
    assert [request.headers["X-User-Id"] for request in requests] == ["0042", "demo-user", "0042"]
    assert all(request.content == b"request" for request in requests)
