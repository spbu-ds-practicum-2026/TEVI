import pytest

from app.models.gossip import NodeEntry, NodeStatus
from app.services.node_registry import NodeRegistry


def make_table(*node_ids: str) -> list[NodeEntry]:
    return [
        NodeEntry(
            node_id=node_id, addr=f"{node_id}:8080", status=NodeStatus.ALIVE,
            incarnation=0, ready=True,
        )
        for node_id in node_ids
    ]


def test_empty_registry():
    registry = NodeRegistry()

    assert registry.latest("n1") is None
    assert registry.all_fresh(now=10.0, t_view=2.0) == {}


def test_put_and_latest_for_one_sender():
    registry = NodeRegistry()
    table = make_table("n1")
    registry.put("n1", table, ts=10.0)

    assert registry.latest("n1") == (table, 10.0)


def test_latest_returns_table_and_receipt_time_for_each_sender():
    registry = NodeRegistry()
    first = make_table("n1", "n2")
    second = make_table("n2", "n1")
    registry.put("n1", first, ts=10.0)
    registry.put("n2", second, ts=11.0)

    assert registry.latest("n1") == (first, 10.0)
    assert registry.latest("n2") == (second, 11.0)
    assert registry.latest("n3") is None


@pytest.mark.parametrize("new_ts", [11.0, 9.0])
def test_put_replaces_table_and_receipt_time(new_ts):
    registry = NodeRegistry()
    old = make_table("n1", "n2")
    new = make_table("n1", "n3")
    registry.put("n1", old, ts=10.0)
    registry.put("n1", new, ts=new_ts)

    assert registry.latest("n1") == (new, new_ts)


def test_all_fresh_returns_every_table_when_all_are_fresh():
    registry = NodeRegistry()
    first = make_table("n1", "n2")
    second = make_table("n2", "n1")
    registry.put("n1", first, ts=9.0)
    registry.put("n2", second, ts=9.5)

    assert registry.all_fresh(now=10.0, t_view=2.0) == {"n1": first, "n2": second}


def test_all_fresh_includes_boundary_and_keeps_stale_tables_in_registry():
    registry = NodeRegistry()
    fresh = make_table("n1")
    boundary = make_table("n2")
    stale = make_table("n3")
    registry.put("n1", fresh, ts=9.0)
    registry.put("n2", boundary, ts=8.0)
    registry.put("n3", stale, ts=7.75)

    assert registry.all_fresh(now=10.0, t_view=2.0) == {"n1": fresh, "n2": boundary}
    assert registry.all_fresh(now=12.0, t_view=2.0) == {}
    assert registry.latest("n1") == (fresh, 9.0)
    assert registry.latest("n2") == (boundary, 8.0)
    assert registry.latest("n3") == (stale, 7.75)


def test_receiving_a_new_table_makes_sender_fresh_again():
    registry = NodeRegistry()
    registry.put("n1", make_table("n1", "n2"), ts=8.0)
    assert registry.all_fresh(now=11.0, t_view=2.0) == {}

    new = make_table("n1", "n3")
    registry.put("n1", new, ts=11.25)

    assert registry.all_fresh(now=11.5, t_view=2.0) == {"n1": new}


def test_reads_share_original_table_but_all_fresh_returns_a_new_dict():
    registry = NodeRegistry()
    table = make_table("n1")
    registry.put("n1", table, ts=10.0)

    latest = registry.latest("n1")
    assert latest is not None
    assert latest[0] is table
    fresh = registry.all_fresh(now=10.0, t_view=0.0)
    assert fresh["n1"] is table
    fresh.clear()

    assert registry.all_fresh(now=10.0, t_view=0.0) == {"n1": table}
