import pytest

from app.config import Config
from app.services.liveness_view import LivenessView


@pytest.fixture
def config():
    return Config(
        n0=2,
        nodes={"n2": "http://node2:8080", "n1": "http://node1:8080"},
        t_req=2,
        r_max=0,
    )


def test_live_nodes_returns_all_configured_nodes(config):
    view = LivenessView(config)

    assert set(view.live_nodes()) == {"n1", "n2"}
    view.live_nodes().clear()
    assert set(view.live_nodes()) == {"n1", "n2"}


def test_is_in_active_returns_true_for_every_configured_node(config):
    view = LivenessView(config)

    for node_id in config.nodes:
        assert view.is_in_active(node_id) is True


def test_continuously_live_returns_true_for_every_configured_node(config):
    view = LivenessView(config)

    for node_id in config.nodes:
        assert view.continuously_live(node_id) is True
