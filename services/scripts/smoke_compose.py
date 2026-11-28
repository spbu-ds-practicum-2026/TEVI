"""Build, exercise and remove a temporary Compose project."""

import json
import subprocess
import sys
from collections import Counter
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "generator/services/load_generator"

# Run inside node1 so the probe uses the same DNS and network as the nodes.
CHECK_CLUSTER = r"""
import json
import sys
import time
from http.client import HTTPConnection
from pathlib import Path

config = json.loads(Path("/app/config/cluster.json").read_text())
nodes = [f"node{i}" for i in range(1, config["n0"] + 1)]
user_id = sys.argv[1]

def request(host, method, path, body=None, headers=None):
    connection = HTTPConnection(host, 8080, timeout=3)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()

for service in ["distributor", *nodes, "target"]:
    status, body = request(service, "GET", "/health")
    assert status == 200 and json.loads(body) == {"status": "ok"}, (service, status, body)
print("All six processes report /health = 200", flush=True)

table = [
    {"node_id": node_id, "addr": addr, "status": "alive", "incarnation": 0, "ready": False}
    for node_id, addr in config["nodes"].items()
]
status, body = request(
    "node2", "POST", "/internal/gossip",
    json.dumps({"sender": "n1", "table": table}),
    {"Content-Type": "application/json"},
)
assert status == 200, (status, body)
assert {entry["node_id"] for entry in json.loads(body)["table"]} == set(config["nodes"])
print("Node-to-node gossip accepted", flush=True)

pending = set(nodes)
deadline = time.monotonic() + config["T"] + config["T_grace"] + 10
while pending:
    for node in sorted(pending):
        status, body = request(
            node, "POST", "/internal/check", b"",
            {"X-User-Id": user_id, "X-Request-Id": f"ready-{node}"},
        )
        if status == 200:
            assert body == b"", (node, body)
            pending.remove(node)
        else:
            assert status == 503, (node, status, body)
    if pending:
        assert time.monotonic() < deadline, f"Nodes still in quarantine: {sorted(pending)}"
        time.sleep(0.25)
print("All four nodes accept traffic after quarantine", flush=True)
"""


def check(user_id: str) -> tuple[int, bytes]:
    connection = HTTPConnection("127.0.0.1", 8080, timeout=10)
    try:
        connection.request(
            "POST",
            "/v1/check",
            b"\x00\xff\x80\n",
            {
                "X-User-Id": user_id,
                "X-Request-Id": str(uuid4()),
                "Content-Type": "application/octet-stream",
            },
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def main() -> None:
    project = f"fdc-smoke-{uuid4().hex[:8]}"

    def compose(*args, check=True, **kwargs):
        return subprocess.run(
            ["docker", "compose", "-p", project, *args], cwd=ROOT, check=check, **kwargs
        )

    config = json.loads((ROOT / "config/cluster.json").read_text(encoding="utf-8"))
    nodes = [f"node{i}" for i in range(1, config["n0"] + 1)]
    services = {"distributor", "target", *nodes}
    configured = compose("config", "--services", capture_output=True, text=True).stdout
    assert set(configured.splitlines()) == services
    try:
        compose("up", "--build", "-d", "--wait", "--wait-timeout", "45", timeout=300)
        compose(
            "exec", "-T", "node1", "python", "-", f"{project}-ready",
            input=CHECK_CLUSTER, text=True, timeout=config["T"] + config["T_grace"] + 30,
        )

        assert check(f"{project}-binary") == (200, b"")
        print("Published /v1/check: binary request returned HTTP 200 with an empty body", flush=True)

        logs = compose("logs", "--no-color", "distributor", capture_output=True, text=True)
        gossip_ok = 'POST /internal/gossip HTTP/1.1" 200 OK'
        assert gossip_ok in logs.stdout, logs.stdout
        print("Distributor accepted gossip sent by nodes", flush=True)

        load_user = f"{project}-load"
        count = config["L"] + config["n0"]
        with TemporaryDirectory(prefix="fdc-load-") as temp:
            generator = subprocess.run(
                [sys.executable, str(GENERATOR / "generator.py"), "http://127.0.0.1:8080/v1/check",
                 "--count", str(count), "--interval", "0", "--user-id", load_user],
                cwd=temp, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
            )
            assert generator.returncode == 0, generator.stdout
            records = (Path(temp) / "requests.jsonl").read_text(encoding="utf-8").splitlines()
            statuses = Counter(json.loads(record)["status"] for record in records)
            assert len(records) == count and set(statuses) == {200, 429}, statuses
            print(f"Sequential load: {statuses[200]} HTTP 200, {statuses[429]} HTTP 429",
                  flush=True)

        logs = compose("logs", "--no-color", "--no-log-prefix", *nodes,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        checker = subprocess.run(
            [sys.executable, str(GENERATOR / "checker.py"), "-"],
            cwd=ROOT, input=logs.stdout, text=True, capture_output=True, timeout=30,
        )
        assert checker.returncode == 0 and f"{load_user}:" in checker.stdout, (
            checker.stdout, checker.stderr,
        )
        print(checker.stdout.rstrip(), flush=True)

        compose("stop", "target", timeout=30)
        status, body = check(f"{project}-no-target")
        assert status == 502 and json.loads(body) == {"error": "target unavailable"}, (status, body)
        compose("stop", *nodes, timeout=30)
        assert check(f"{project}-no-nodes") == (503, b"")
        print("Unavailable target -> HTTP 502; all nodes stopped -> HTTP 503", flush=True)
    except Exception:
        compose("logs", "--no-color", "--tail", "40", timeout=20, check=False)
        raise
    finally:
        compose("down", "--timeout", "10", "--rmi", "local", timeout=45)
        remaining = compose("ps", "-aq", capture_output=True, text=True).stdout
        assert not remaining.strip(), remaining
        print("Compose project stopped and its containers removed", flush=True)


if __name__ == "__main__":
    main()
