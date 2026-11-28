import pytest

from app.services.membership.membership_table import MembershipTable, Status

SECOND = 1_000_000_000


@pytest.fixture
def cluster():
    now = [0]
    table = MembershipTable(
        self_id="n1",
        nodes={"n1": "node1:8080", "n2": "node2:8080"},
        clock_ns=lambda: now[0],
        wall_ms=lambda: 1234,
        t_start_s=2,
        pause_gap_s=3,
    )
    table.init_from_config()
    return table, now


def test_startup_quarantine_expires_at_deadline(cluster):
    table, now = cluster
    now[0] = 2 * SECOND - 1
    assert not table.self_ready()

    now[0] += 1
    assert table.self_ready()
    assert table.alive_ids() == ["n2"]


def test_event_loop_pause_restarts_quarantine_before_checking_readiness(cluster):
    table, now = cluster
    now[0] = 4 * SECOND
    assert not table.self_ready()

    now[0] = 6 * SECOND
    assert table.self_ready()


def test_repeated_distributor_hint_does_not_extend_quarantine(cluster):
    table, now = cluster
    table.apply_hints(is_in_active=False, continuously_live=True)
    now[0] = 2 * SECOND
    assert table.self_ready()

    table.apply_hints(is_in_active=True, continuously_live=True)
    assert not table.self_ready()

    now[0] = 3 * SECOND
    table.apply_hints(is_in_active=True, continuously_live=True)
    now[0] = 4 * SECOND
    assert table.self_ready()


def test_merge_uses_incarnation_then_status_and_preserves_death_timestamp(cluster):
    table, now = cluster
    dead = {"node_id": "n2", "status": "dead", "incarnation": 2, "ready": False}
    now[0] = 10
    table.merge([dead])

    now[0] = 20
    table.merge([dead, {**dead, "status": "alive"}, {**dead, "incarnation": 1}])
    peer = next(entry for entry in table.read_membership() if entry.node_id == "n2")
    assert peer.status == Status.DEAD
    assert peer.dead_since_ns == 10
    assert table.alive_ids() == []

    table.merge([{**dead, "status": "alive", "incarnation": 3, "ready": True}])
    peer = next(entry for entry in table.read_membership() if entry.node_id == "n2")
    assert peer.status == Status.ALIVE
    assert peer.dead_since_ns is None
    assert table.alive_ids() == ["n2"]


def test_merge_does_not_add_unknown_node_or_override_own_record(cluster):
    table, _ = cluster
    table.merge(
        [
            {"node_id": "n1", "status": "dead", "incarnation": 1235, "ready": True},
            {"node_id": "n3", "status": "alive", "incarnation": 1, "ready": True},
        ],
    )

    entries = {entry.node_id: entry for entry in table.snapshot()}
    assert set(entries) == {"n1", "n2"}
    assert entries["n1"].status == Status.ALIVE
    assert entries["n1"].incarnation == 1234
    assert not entries["n1"].ready
