import asyncio
import json
import logging
from unittest.mock import AsyncMock

import httpx

from app.config import NodeConfig
from app.handler import NodeHandler
from app.main import build_limiter
from app.services.membership.membership_table import MembershipTable
from app.transport import Transport, TransportError

CHECK = "/internal/check"
TARGET = "target:8080"
HEADERS = {
    "X-User-Id": "42",
    "X-Request-Id": "r1",
    "Content-Type": "application/octet-stream",
}
BODY = b"\x00\xffdemo"


def test_internal_check_quarantine_admission_and_quota(caplog):
    async def scenario():
        nodes = {"n1": "node1:8080", "n2": "node2:8080"}
        config = NodeConfig(
            self_id="n1", nodes=nodes, target_addr=TARGET, distributor_addr=None,
            L=2, T_s=10, T_grace_s=3, t_handle_s=0.5,
        )
        now = [0]
        table = MembershipTable(
            self_id=config.self_id, nodes=config.nodes, clock_ns=lambda: now[0],
            t_start_s=config.t_start_s, pause_gap_s=20,
        )
        table.init_from_config()
        limiter, _ = build_limiter(config)
        limiter.clock_ns = lambda: now[0]
        transport = Transport()
        transport.post_raw = AsyncMock(return_value=(200, b"\x00ok", "application/octet-stream"))
        handler = NodeHandler(
            table, limiter, transport, self_id=config.self_id, target_addr=config.target_addr,
        )
        transport.register(CHECK, handler.handle)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=transport._app), base_url="http://node",
        ) as client:
            missing_user = await client.post(CHECK, content=BODY)
            assert missing_user.status_code == 400
            in_quarantine = await client.post(CHECK, content=BODY, headers=HEADERS)
            assert in_quarantine.status_code == 503
            transport.post_raw.assert_not_awaited()

            now[0] = config.hold_ns
            accepted = await client.post(CHECK, content=BODY, headers=HEADERS)
            assert accepted.status_code == 200
            assert accepted.content == b"\x00ok"
            assert accepted.headers["content-type"] == "application/octet-stream"

            denied = await client.post(CHECK, content=BODY, headers={**HEADERS, "X-Request-Id": "r2"})
            assert denied.status_code == 429
            transport.post_raw.assert_awaited_once_with(
                TARGET, "/handle", BODY, timeout_s=0.5,
                headers={"X-Request-Id": "r1", "Content-Type": "application/octet-stream"},
            )

        return now[0]

    with caplog.at_level(logging.INFO, logger="admission"):
        decision_time = asyncio.run(scenario())

    entries = [json.loads(record.getMessage()) for record in caplog.records if record.name == "admission"]
    assert entries == [
        {"event": "admission", "ts": decision_time, "request_id": "r1", "user_id": "42",
         "node_id": "n1", "n": 2, "q": 1},
    ]


def test_target_error_returns_502_and_admission_still_spends_quota():
    async def scenario():
        nodes = {"n1": "node1:8080"}
        config = NodeConfig(
            self_id="n1", nodes=nodes, target_addr=TARGET, distributor_addr=None,
            L=1, T_s=10, T_grace_s=3, t_handle_s=0.5,
        )
        limiter, _ = build_limiter(config)
        limiter.clock_ns = lambda: 0
        table = MembershipTable(self_id="n1", nodes=nodes, clock_ns=lambda: 0, t_start_s=0)
        table.init_from_config()
        transport = Transport()
        transport.post_raw = AsyncMock(side_effect=TransportError(TARGET, "/handle", "offline"))
        handler = NodeHandler(table, limiter, transport, self_id="n1", target_addr=TARGET)

        status, _ = await handler.handle(BODY, {"x-user-id": "42"})
        assert status == 502
        status, _ = await handler.handle(BODY, {"x-user-id": "42"})
        assert status == 429
        assert transport.post_raw.await_count == 1

    asyncio.run(scenario())
