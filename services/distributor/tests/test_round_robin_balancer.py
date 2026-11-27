from app.services.round_robin_balancer import RoundRobinBalancer


def test_first_pick_is_lexicographically_smallest():
    balancer = RoundRobinBalancer()

    assert balancer.pick("alice", ["n2", "n10", "n3"]) == "n10"


def test_picks_cycle_through_nodes():
    balancer = RoundRobinBalancer()
    nodes = ["n3", "n1", "n2"]

    assert [balancer.pick("alice", nodes) for _ in range(5)] == [
        "n1", "n2", "n3", "n1", "n2"
    ]


def test_users_have_independent_counters():
    balancer = RoundRobinBalancer()
    nodes = ["n1", "n2"]

    assert balancer.pick("alice", nodes) == "n1"
    assert balancer.pick("bob", nodes) == "n1"
    assert balancer.pick("alice", nodes) == "n2"
    assert balancer.pick("bob", nodes) == "n2"


def test_empty_node_list_returns_none():
    balancer = RoundRobinBalancer()

    assert balancer.pick("alice", []) is None


def test_empty_node_list_preserves_counter():
    balancer = RoundRobinBalancer()
    nodes = ["n1", "n2"]

    assert balancer.pick("alice", nodes) == "n1"
    assert balancer.pick("alice", []) is None
    assert balancer.pick("alice", nodes) == "n2"


def test_single_node_is_always_picked():
    balancer = RoundRobinBalancer()

    assert balancer.pick("alice", ["n1"]) == "n1"
    assert balancer.pick("alice", ["n1"]) == "n1"


def test_input_order_does_not_change_picks():
    balancer = RoundRobinBalancer()

    assert balancer.pick("alice", ["n3", "n2", "n1"]) == "n1"
    assert balancer.pick("alice", ["n2", "n1", "n3"]) == "n2"
    assert balancer.pick("alice", ["n1", "n3", "n2"]) == "n3"


def test_pick_uses_current_node_count():
    balancer = RoundRobinBalancer()

    assert balancer.pick("alice", ["n1", "n2", "n3"]) == "n1"
    assert balancer.pick("alice", ["n1", "n2", "n3"]) == "n2"
    assert balancer.pick("alice", ["n2", "n3"]) == "n2"
    assert balancer.pick("alice", ["n1", "n2", "n3", "n4"]) == "n4"


def test_pick_does_not_mutate_node_list():
    balancer = RoundRobinBalancer()
    nodes = ["n2", "n1"]

    balancer.pick("alice", nodes)

    assert nodes == ["n2", "n1"]
