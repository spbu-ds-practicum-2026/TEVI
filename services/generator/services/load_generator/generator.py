import argparse
import asyncio
import json
from time import monotonic_ns
from uuid import uuid4

import anyio
import httpx


async def send_request(client: httpx.AsyncClient, url: str, user_id: str) -> dict:
    request_id = str(uuid4())
    headers = {
        "X-User-Id": user_id,
        "X-Request-Id": request_id,
    }

    started_ns = monotonic_ns()
    response = await client.post(url, headers=headers, json={"message": "demo"})
    latency_ms = (monotonic_ns() - started_ns) / 1_000_000

    return {
        "ts": started_ns,
        "request_id": request_id,
        "user_id": user_id,
        "status": response.status_code,
        "latency_ms": round(latency_ms, 3),
        "node_id": None,
    }


async def run(url: str, count: int, interval: float, user_id: str) -> list[int]:
    statuses = []

    async with (
        await anyio.open_file("requests.jsonl", "a", encoding="utf-8") as log, httpx.AsyncClient(timeout=5.0, trust_env=False) as client):
        for i in range(1, count + 1):
            result = await send_request(client, url, user_id)
            status = result["status"]

            await log.write(json.dumps(result) + "\n")
            statuses.append(status)
            print(f"Запрос {i}: статус {status}, задержка {result['latency_ms']:.1f} мс")

            if i < count:
                await asyncio.sleep(interval)

    return statuses


async def main() -> int:
    parser = argparse.ArgumentParser(description="Генератор запросов для TEVI")
    parser.add_argument("url", help="Полный адрес для отправки запросов")
    parser.add_argument("--count", type=int, default=5, help="Число запросов")
    parser.add_argument("--interval", type=float, default=1.0, help="Пауза в секундах")
    parser.add_argument("--user-id", default="demo-user", help="Идентификатор пользователя")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count должен быть не меньше 1")
    if args.interval < 0:
        parser.error("--interval должен быть не меньше 0")

    try:
        statuses = await run(args.url, args.count, args.interval, args.user_id)
    except (httpx.RequestError, httpx.InvalidURL) as error:
        print(f"Не удалось отправить запрос: {error}")
        return 1

    ok_count = statuses.count(200)
    limited_count = statuses.count(429)
    other_count = len(statuses) - ok_count - limited_count

    print(f"\nВсего ответов: {len(statuses)}")
    print(f"Пропущено (200): {ok_count}")
    print(f"Отклонено по лимиту (429): {limited_count}")
    print(f"Другие статусы: {other_count}")
    return 0 if other_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))