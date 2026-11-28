import asyncio
from unittest.mock import AsyncMock, Mock

from app.services.membership.gossip import GossipService
from app.services.membership.membership_table import MembershipTable
from app.transport import TransportError

NODES = {"n1": "node1:8080", "n2": "node2:8080", "n3": "node3:8080"}
PEER = {
    "node_id": "n2",
    "addr": NODES["n2"],
    "status": "dead",
    "incarnation": 2,
    "ready": False,
}


def test_incoming_gossip_merges_valid_entries_and_excludes_local_timestamps():
    table = MembershipTable(self_id="n1", nodes=NODES, clock_ns=lambda: 10)
    table.init_from_config()
    gossip = GossipService(table, Mock(), self_id="n1", nodes=NODES)

    result = asyncio.run(
        gossip.on_gossip(
            {
                "sender": "n2",
                "table": [
                    {**PEER, "dead_since_ns": 81},
                    {"node_id": "n3", "status": "alive", "incarnation": "invalid"},
                    {"node_id": "n3", "status": "unknown", "incarnation": 99},
                ],
            },
        ),
    )

    wire = {entry["node_id"]: entry for entry in result["table"]}
    assert wire["n2"] == PEER
    assert wire["n3"]["incarnation"] == 0
    assert wire["n1"]["ready"] is False
    assert {"quarantine_until_ns", "dead_since_ns"}.isdisjoint(wire["n1"])
    view = {entry.node_id: entry for entry in table.read_membership()}
    assert view["n2"].dead_since_ns == 10


def test_gossip_round_merges_peer_reply_and_applies_distributor_hints():
    table = Mock(spec=MembershipTable)
    table.snapshot.return_value = []
    table.alive_ids.return_value = ["n2", "missing"]
    async def reply(addr, path, payload, *, timeout_s):
        if addr == NODES["n2"]:
            return {"table": [PEER]}
        return {"table": [], "is_in_active": True, "continuously_live": False}

    transport = Mock()
    transport.post = AsyncMock(side_effect=reply)
    gossip = GossipService(
        table, transport, self_id="n1", nodes=NODES, distributor_addr="dist:8080",
        f=1, gossip_timeout_s=0.25,
    )

    asyncio.run(gossip._round())

    assert transport.post.await_count == 2
    for addr in (NODES["n2"], "dist:8080"):
        transport.post.assert_any_await(
            addr, "/internal/gossip", {"sender": "n1", "table": []}, timeout_s=0.25,
        )
    table.merge.assert_called_once_with([PEER])
    table.apply_hints.assert_called_once_with(True, False)


def test_failed_gossip_notifies_table_only_for_distributor():
    table = Mock(spec=MembershipTable)
    table.snapshot.return_value = []
    table.alive_ids.return_value = ["n2"]
    transport = Mock()
    transport.post = AsyncMock(
        side_effect=TransportError("unreachable:8080", "/internal/gossip", "offline"),
    )
    gossip = GossipService(
        table, transport, self_id="n1", nodes=NODES, distributor_addr="dist:8080",
    )

    asyncio.run(gossip._round())

    assert transport.post.await_count == 2
    table.on_distributor_unreachable.assert_called_once_with()
    table.merge.assert_not_called()
    table.apply_hints.assert_not_called()
    table.mark_suspect.assert_not_called()
