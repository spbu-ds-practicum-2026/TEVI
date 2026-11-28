#!/bin/sh
set -eu

context=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
docker info >/dev/null

scratch=$(mktemp -d)
suffix=$(printf '%s' "${scratch##*.}" | tr '[:upper:]' '[:lower:]')
prefix="fdc-target-smoke-$suffix"
image="$prefix:local"
network="$prefix"
target="$prefix-target"
probe="$prefix-probe"

cleanup() {
    status=$?
    if [ "$status" -ne 0 ] && docker container inspect "$target" >/dev/null 2>&1; then
        docker logs "$target" >&2 || :
        docker inspect --format 'Container state (including healthcheck): {{json .State}}' "$target" >&2 || :
    fi
    docker rm -f "$probe" "$target" >/dev/null 2>&1 || :
    docker network rm "$network" >/dev/null 2>&1 || :
    docker image rm "$image" >/dev/null 2>&1 || :
    rmdir "$scratch"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

docker build -t "$image" "$context"
docker network create "$network" >/dev/null
docker run -d --name "$target" --network "$network" --network-alias target "$image" >/dev/null

deadline=$(( $(date +%s) + 30 ))
while :; do
    state=$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "$target")
    case "$state" in
        "running healthy") break ;;
        "running starting") ;;
        *) printf 'Unexpected target state: %s\n' "$state" >&2; exit 1 ;;
    esac
    if [ "$(date +%s)" -ge "$deadline" ]; then
        printf 'Target did not become healthy within 30 seconds\n' >&2
        exit 1
    fi
    sleep 1
done

docker run --rm -i --name "$probe" --network "$network" --entrypoint python "$image" - <<'PY'
import json
from http.client import HTTPConnection

conn = HTTPConnection("target", 8080, timeout=3)
try:
    conn.request("GET", "/health")
    response = conn.getresponse()
    body = response.read()
    if response.status != 200 or json.loads(body) != {"status": "ok"}:
        raise SystemExit(f"GET /health: HTTP {response.status}, body={body!r}")
    print("GET /health: HTTP 200, status=ok")

    conn.request(
        "POST",
        "/handle",
        body=b"\x00\xff\x80\n",
        headers={"X-Request-Id": "smoke-test", "Content-Type": "application/octet-stream"},
    )
    response = conn.getresponse()
    body = response.read()
    if response.status != 200 or body != b"":
        raise SystemExit(f"POST /handle: HTTP {response.status}, body={body!r}")
    print("POST /handle: HTTP 200, 0 bytes")
finally:
    conn.close()
PY
