import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.clients import gossip_receiver
from app.main import app
from app.models.gossip import GossipRequest
from app.services.upstream_client import UpstreamClient


@pytest.fixture
def open_client(monkeypatch, tmp_path):
    config_path = tmp_path / "cluster.json"
    config_path.write_text(
        '{"n0":2,"nodes":{"n1":"http://node1","n2":"http://node2"},"t_req":2,"R_max":0}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setattr(app, "state", type(app.state)())

    @asynccontextmanager
    async def client():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://distributor"
            ) as http_client:
                yield http_client

    return client


@pytest.fixture
def clock(monkeypatch):
    monotonic = Mock(return_value=10.25)
    monkeypatch.setattr(gossip_receiver, "time", SimpleNamespace(monotonic=monotonic))
    return monotonic


def gossip_message(sender="n1", node_ids=("n1", "n2"), incarnation=0):
    return {
        "sender": sender,
        "table": [
            {
                "node_id": node_id,
                "addr": f"{node_id}:8080",
                "status": "alive",
                "incarnation": incarnation,
                "ready": True,
            }
            for node_id in node_ids
        ],
    }


def test_valid_gossip_returns_flags_and_stores_table(open_client, clock):
    message = gossip_message()

    async def check():
        async with open_client() as client:
            response = await client.post("/internal/gossip", json=message)
            assert response.status_code == 200
            assert response.json() == {
                "table": [],
                "is_in_active": True,
                "continuously_live": True,
            }
            assert app.state.node_registry.latest("n1") == (
                GossipRequest.model_validate(message).table, 10.25
            )
            assert app.state.node_registry.latest("n2") is None

    asyncio.run(check())
    clock.assert_called_once_with()


@pytest.mark.parametrize(
    "message",
    [
        {"table": gossip_message()["table"]},
        {**gossip_message(), "sender": 1},
        gossip_message(node_ids=("n1", "n1")),
        gossip_message(node_ids=("n2",)),
    ],
    ids=["missing-field", "wrong-type", "duplicate-node", "missing-sender-entry"],
)
def test_structural_gossip_errors_return_422(open_client, clock, message):
    async def check():
        async with open_client() as client:
            response = await client.post("/internal/gossip", json=message)
            assert response.status_code == 422
            assert app.state.node_registry.all_fresh(now=10.25, t_view=2.0) == {}

    asyncio.run(check())
    clock.assert_not_called()


def test_malformed_gossip_json_returns_422(open_client, clock):
    async def check():
        async with open_client() as client:
            response = await client.post(
                "/internal/gossip", content=b"{", headers={"Content-Type": "application/json"}
            )
            assert response.status_code == 422
            assert app.state.node_registry.all_fresh(now=10.25, t_view=2.0) == {}

    asyncio.run(check())
    clock.assert_not_called()


@pytest.mark.parametrize(
    ("message", "expected_detail"),
    [
        (gossip_message(node_ids=("n1",)), "missing=['n2'], unknown=[]"),
        (gossip_message(node_ids=("n1", "n2", "n9")), "missing=[], unknown=['n9']"),
        (gossip_message("n9", ("n1", "n2", "n9")), "missing=[], unknown=['n9']"),
    ],
    ids=["missing-node", "unknown-node", "unknown-sender"],
)
def test_contextual_gossip_errors_return_400(open_client, clock, message, expected_detail):
    async def check():
        async with open_client() as client:
            response = await client.post("/internal/gossip", json=message)
            assert response.status_code == 400
            assert response.json() == {
                "detail": (
                    f"Gossip table from sender {message['sender']!r} "
                    f"does not match cluster membership ({expected_detail})"
                )
            }
            assert app.state.node_registry.all_fresh(now=10.25, t_view=2.0) == {}

    asyncio.run(check())
    clock.assert_not_called()


def test_rejected_gossip_preserves_table_until_next_valid_request(open_client, clock):
    first = gossip_message(incarnation=1)
    second = gossip_message(incarnation=2)

    async def check():
        async with open_client() as client:
            registry = app.state.node_registry
            response = await client.post("/internal/gossip", json=first)
            assert response.status_code == 200
            original = (GossipRequest.model_validate(first).table, 10.25)
            assert registry.latest("n1") == original

            clock.return_value = 12.5
            response = await client.post("/internal/gossip", json=gossip_message(node_ids=("n1",)))
            assert response.status_code == 400
            assert registry.latest("n1") == original

            response = await client.post("/internal/gossip", json={"sender": "n1"})
            assert response.status_code == 422
            assert registry.latest("n1") == original

            response = await client.post("/internal/gossip", json=second)
            assert response.status_code == 200
            assert registry.latest("n1") == (GossipRequest.model_validate(second).table, 12.5)

    asyncio.run(check())
    assert clock.call_count == 2


def test_gossip_from_two_senders_is_stored_independently(open_client, clock):
    first = gossip_message("n1", incarnation=1)
    second = gossip_message("n2", incarnation=2)
    clock.side_effect = [10.25, 12.5]

    async def check():
        async with open_client() as client:
            assert (await client.post("/internal/gossip", json=first)).status_code == 200
            assert (await client.post("/internal/gossip", json=second)).status_code == 200
            registry = app.state.node_registry
            assert registry.latest("n1") == (GossipRequest.model_validate(first).table, 10.25)
            assert registry.latest("n2") == (GossipRequest.model_validate(second).table, 12.5)

    asyncio.run(check())


def test_health_and_check_work_before_first_gossip(open_client, monkeypatch):
    upstream_check = AsyncMock(
        return_value=httpx.Response(200, content=b"ok", headers={"Content-Type": "text/plain"})
    )
    monkeypatch.setattr(UpstreamClient, "check", upstream_check)

    async def check():
        async with open_client() as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}

            response = await client.post(
                "/v1/check", headers={"X-User-Id": "demo-user"}, content=b"payload"
            )
            assert response.status_code == 200
            assert response.content == b"ok"

    asyncio.run(check())
    upstream_check.assert_awaited_once_with(
        node_addr="http://node1", user_id="demo-user", request_id="1", body=b"payload"
    )
