import json

import pytest

from app.config import NodeConfig


@pytest.mark.parametrize(
    "nodes",
    [
        {"n1": "node1:8080", "n2": "http://node2:8080"},
        [
            {"node_id": "n1", "addr": "node1:8080"},
            {"node_id": "n2", "addr": "http://node2:8080"},
        ],
    ],
    ids=["mapping", "list"],
)
def test_loads_cluster_config_and_converts_seconds(tmp_path, monkeypatch, nodes):
    path = tmp_path / "cluster.json"
    path.write_text(
        json.dumps({"nodes": nodes, "T": 1.5, "T_grace": 0.25, "L": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_PATH", str(path))
    monkeypatch.setenv("NODE_ID", "n1")

    config = NodeConfig.load()

    assert config.self_id == "n1"
    assert config.n0 == 2
    assert config.nodes == {"n1": "node1:8080", "n2": "http://node2:8080"}
    assert config.window_ns == 1_500_000_000
    assert config.hold_ns == 1_750_000_000
    assert config.t_start_s == 1.75


@pytest.mark.parametrize(
    ("options", "error"),
    [
        ({"nodes": {}}, "nodes"),
        ({"nodes": {"n2": "node2:8080"}}, "NODE_ID"),
        ({"nodes": {"n1": "node1"}}, "адрес"),
        ({"L": 1}, "L >= n0"),
        ({"T": 0}, "таймер T"),
        ({"T_grace": -1}, "таймер T_grace"),
        ({"g": "inf"}, "таймер g"),
    ],
)
def test_rejects_invalid_cluster_config(tmp_path, monkeypatch, options, error):
    path = tmp_path / "cluster.json"
    data = {"nodes": {"n1": "node1:8080", "n2": "node2:8080"}, "L": 10}
    data.update(options)
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("NODE_ID", "n1")

    with pytest.raises(ValueError, match=error):
        NodeConfig.load(str(path))
