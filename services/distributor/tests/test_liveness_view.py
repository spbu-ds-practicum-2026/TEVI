from app.config import Config
from app.services.liveness_view import LivenessView


def test_live_nodes_returns_all_configured_nodes():
    config = Config(
        n0=2,
        nodes={"n2": "http://node2:8080", "n1": "http://node1:8080"},
        t_req=2,
        r_max=0,
    )
    view = LivenessView(config)

    assert set(view.live_nodes()) == {"n1", "n2"}
    view.live_nodes().clear()
    assert set(view.live_nodes()) == {"n1", "n2"}
