import asyncio
import json
from pathlib import Path

import pytest

from app.config import Config
from app.main import app
from app.services.liveness_view import LivenessView
from app.services.round_robin_balancer import RoundRobinBalancer


@pytest.fixture
def config_data():
    return {
        "n0": 1,
        "nodes": {"n1": "https://node1:8080"},
        "t_req": 1.5,
        "R_max": 1,
    }


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "cluster.json"


def test_load_cluster_config():
    path = Path(__file__).resolve().parents[2] / "config" / "cluster.json"
    raw = json.loads(path.read_bytes())
    config = Config.from_file(path)

    assert config.model_dump(by_alias=True) == {
        "n0": raw["n0"],
        "nodes": raw["nodes"],
        "t_req": raw["t_req"],
        "R_max": raw["R_max"],
    }
    assert isinstance(config.t_req, float)
    assert config.r_max == raw["R_max"]


def test_load_from_env(monkeypatch, config_path, config_data):
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))

    assert Config.from_env().model_dump(by_alias=True) == config_data


@pytest.mark.parametrize("field", ["n0", "nodes", "t_req", "R_max"])
def test_required_fields(config_path, config_data, field):
    del config_data[field]
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{field}\n  Field required"):
        Config.from_file(config_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("n0", 0),
        ("n0", -1),
        ("n0", 1.0),
        ("n0", "1"),
        ("n0", True),
        ("nodes", {}),
        ("nodes", []),
        ("nodes", {"": "http://node1:8080"}),
        ("nodes", {"   ": "http://node1:8080"}),
        ("nodes", {"n1": 8080}),
        ("nodes", {"n1": "node1:8080"}),
        ("nodes", {"n1": "/node1"}),
        ("nodes", {"n1": "ftp://node1:8080"}),
        ("nodes", {"n1": "http://"}),
        ("nodes", {"n1": "http:///node1"}),
        ("nodes", {"n1": "http:/node1"}),
        ("nodes", {"n1": "http://node 1:8080"}),
        ("nodes", {"n1": "http://node1:99999"}),
        ("t_req", 0),
        ("t_req", -1),
        ("t_req", "2"),
        ("t_req", True),
        ("t_req", float("nan")),
        ("t_req", float("inf")),
        ("t_req", float("-inf")),
        ("R_max", -1),
        ("R_max", 1.5),
        ("R_max", 2.0),
        ("R_max", "2"),
        ("R_max", True),
    ],
)
def test_invalid_field(config_path, config_data, field, value):
    config_data[field] = value
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"\b{field}\b"):
        Config.from_file(config_path)


@pytest.mark.parametrize("r_max", [0, 3])
def test_retry_limit_accepts_non_negative_integers(config_path, config_data, r_max):
    config_data["R_max"] = r_max
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    assert Config.from_file(config_path).r_max == r_max


def test_node_count_mismatch(config_path, config_data):
    config_data["n0"] = 2
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    with pytest.raises(ValueError, match="n0 must equal the number of entries in nodes"):
        Config.from_file(config_path)


def test_invalid_json(config_path):
    config_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON") as error:
        Config.from_file(config_path)
    assert str(config_path) in str(error.value)


def test_missing_file(monkeypatch, config_path):
    monkeypatch.setenv("CONFIG_PATH", str(config_path))

    with pytest.raises(FileNotFoundError) as error:
        Config.from_env()
    assert error.value.filename == str(config_path)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_config_path(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CONFIG_PATH", raising=False)
    else:
        monkeypatch.setenv("CONFIG_PATH", value)

    with pytest.raises(RuntimeError, match="CONFIG_PATH"):
        Config.from_env()


def test_lifespan_initializes_components(monkeypatch, config_path, config_data):
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setattr(app, "state", type(app.state)())

    async def check_startup():
        async with app.router.lifespan_context(app):
            assert app.state.config.model_dump(by_alias=True) == config_data
            assert isinstance(app.state.liveness_view, LivenessView)
            assert isinstance(app.state.balancer, RoundRobinBalancer)
            nodes = app.state.liveness_view.live_nodes()
            assert nodes == list(config_data["nodes"])
            assert app.state.balancer.pick("alice", nodes) == "n1"

    asyncio.run(check_startup())


def test_lifespan_rejects_invalid_config(monkeypatch, config_path):
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))

    async def check_startup():
        async with app.router.lifespan_context(app):
            pytest.fail("Startup succeeded with invalid configuration")

    with pytest.raises(ValueError, match="Invalid cluster configuration"):
        asyncio.run(check_startup())
