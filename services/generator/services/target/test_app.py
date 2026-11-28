import asyncio

import httpx
import pytest

from app import app


async def request(method: str, path: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://target"
    ) as client:
        return await client.request(method, path, **kwargs)


def test_health():
    response = asyncio.run(request("GET", "/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"", {}),
        (b'{"example": true}', {"Content-Type": "application/json"}),
        (b"\x00\xff\x80\n", {}),
        (
            b"\x00\xff\x80\n",
            {
                "X-Request-Id": "e85ecfc7-510d-480d-a539-e73567e01132",
                "Content-Type": "application/octet-stream",
            },
        ),
    ],
    ids=["empty", "json", "binary-without-headers", "node-request"],
)
def test_handle_accepts_raw_body_and_returns_empty_response(body, headers):
    response = asyncio.run(request("POST", "/handle", content=body, headers=headers))

    assert response.status_code == 200
    assert response.content == b""
