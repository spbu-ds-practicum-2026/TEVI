import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.clients import gossip_receiver
from app.clients.gossip_receiver import GossipReceiver
from app.config import Config
from app.models.gossip import GossipRequest, GossipResponse, NodeEntry, NodeStatus
from app.services.liveness_view import LivenessView
from app.services.node_registry import NodeRegistry


@pytest.fixture
def components(monkeypatch):
    config = Config(
        n0=2, nodes={"n1": "http://node1", "n2": "http://node2"}, t_req=2, r_max=0
    )
    registry = NodeRegistry()
    liveness_view = LivenessView(config)
    clock = Mock(return_value=10.25)
    monkeypatch.setattr(gossip_receiver, "time", SimpleNamespace(monotonic=clock))
    return GossipReceiver(config, registry, liveness_view), registry, liveness_view, clock


def make_gossip_request(
    *node_ids: str, incarnation: int = 0, sender: str = "n2"
) -> GossipRequest:
    return GossipRequest(
        sender=sender,
        table=[
            NodeEntry(
                node_id=node_id,
                addr=f"{node_id}:8080",
                status=NodeStatus.ALIVE,
                incarnation=incarnation,
                ready=True,
            )
            for node_id in node_ids
        ],
    )


def test_handle_stores_table_and_receipt_time_under_sender(components, caplog):
    receiver, registry, _, clock = components
    request = make_gossip_request("n1", "n2")

    with caplog.at_level(logging.DEBUG, logger=gossip_receiver.__name__):
        response = receiver.handle(request)

    clock.assert_called_once_with()
    stored = registry.latest("n2")
    assert stored is not None
    assert stored[0] is request.table
    assert stored[1] == 10.25
    assert registry.latest("n1") is None
    assert response == GossipResponse(table=[], is_in_active=True, continuously_live=True)
    assert not caplog.records


def test_handle_replaces_table_and_receipt_time(components):
    receiver, registry, _, clock = components
    first = make_gossip_request("n1", "n2")
    second = make_gossip_request("n2", "n1", incarnation=1)
    clock.side_effect = [10.25, 12.5]

    receiver.handle(first)
    receiver.handle(second)

    assert registry.latest("n2") == (second.table, 12.5)


def test_handle_stores_new_table_before_querying_liveness_for_n1(components, monkeypatch):
    receiver, registry, liveness_view, clock = components
    first = make_gossip_request("n1", "n2", sender="n1")
    second = make_gossip_request("n2", "n1", incarnation=1, sender="n1")
    receiver.handle(first)
    clock.return_value = 12.5

    def check_registry(node_id):
        assert node_id == "n1"
        assert registry.latest(node_id) == (second.table, 12.5)
        return True

    active = Mock(side_effect=check_registry)
    continuous = Mock(side_effect=check_registry)
    monkeypatch.setattr(liveness_view, "is_in_active", active)
    monkeypatch.setattr(liveness_view, "continuously_live", continuous)

    receiver.handle(second)

    active.assert_called_once_with("n1")
    continuous.assert_called_once_with("n1")
    assert registry.latest("n2") is None


@pytest.mark.parametrize("is_in_active", [False, True])
@pytest.mark.parametrize("continuously_live", [False, True])
def test_handle_returns_liveness_flags(components, monkeypatch, is_in_active, continuously_live):
    receiver, _, liveness_view, _ = components
    active = Mock(return_value=is_in_active)
    continuous = Mock(return_value=continuously_live)
    monkeypatch.setattr(liveness_view, "is_in_active", active)
    monkeypatch.setattr(liveness_view, "continuously_live", continuous)

    response = receiver.handle(make_gossip_request("n1", "n2"))

    active.assert_called_once_with("n2")
    continuous.assert_called_once_with("n2")
    assert response == GossipResponse(
        table=[], is_in_active=is_in_active, continuously_live=continuously_live
    )


@pytest.mark.parametrize("has_previous_table", [False, True], ids=["empty-registry", "with-table"])
def test_invalid_context_logs_error_and_keeps_registry_intact(
    components, monkeypatch, caplog, has_previous_table
):
    receiver, registry, liveness_view, clock = components
    if has_previous_table:
        receiver.handle(make_gossip_request("n1", "n2"))
    previous = registry.latest("n2")
    clock.reset_mock()
    active = Mock()
    continuous = Mock()
    monkeypatch.setattr(liveness_view, "is_in_active", active)
    monkeypatch.setattr(liveness_view, "continuously_live", continuous)

    with pytest.raises(HTTPException) as error:
        receiver.handle(make_gossip_request("n2", "n9"))

    assert error.value.status_code == 400
    assert error.value.detail == (
        "Gossip table from sender 'n2' does not match cluster membership "
        "(missing=['n1'], unknown=['n9'])"
    )
    assert caplog.record_tuples == [
        (gossip_receiver.__name__, logging.ERROR, error.value.detail)
    ]
    assert registry.latest("n2") == previous
    clock.assert_not_called()
    active.assert_not_called()
    continuous.assert_not_called()


def test_value_error_from_liveness_is_not_translated(components, monkeypatch):
    receiver, _, liveness_view, _ = components
    error = ValueError("liveness error")
    monkeypatch.setattr(liveness_view, "is_in_active", Mock(side_effect=error))

    with pytest.raises(ValueError) as caught:
        receiver.handle(make_gossip_request("n1", "n2"))

    assert caught.value is error
