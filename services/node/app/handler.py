from __future__ import annotations

import json
import logging
from typing import Any, Optional, Protocol

from .transport import Transport, TransportError

log = logging.getLogger(__name__)
admission_log = logging.getLogger("admission")


class LimitDecision(Protocol):
    allowed: bool
    n: int
    q: int
    admitted_at_ns: Optional[int]


class Limiter(Protocol):

    def allow(self, user_id: str) -> LimitDecision: ...


class NodeHandler:
    def __init__(self, table, limiter: Limiter, transport: Transport, *,
                 self_id: str, target_addr: str,
                 handle_timeout_s: float = 0.5) -> None:
        self._table = table
        self._limiter = limiter
        self._transport = transport
        self._self_id = self_id
        self._target = target_addr
        self._t_handle = handle_timeout_s

    async def handle(self, raw: bytes, headers: dict):
        user_id = headers.get("x-user-id")
        if not user_id:
            return 400, {"error": "missing X-User-Id"}
        request_id = headers.get("x-request-id", "")

        if not self._table.self_ready():
            return 503, {"error": "node in quarantine"}

        decision = self._limiter.allow(user_id)
        if not decision.allowed:
            return 429, {"error": "quota exhausted"}
        admission_log.info(json.dumps({
            "event": "admission",
            "ts": decision.admitted_at_ns,
            "request_id": request_id,
            "user_id": user_id,
            "node_id": self._self_id,
            "n": decision.n,
            "q": decision.q,
        }, ensure_ascii=False))

        fwd_headers = {"X-Request-Id": request_id}
        req_ctype = headers.get("content-type")
        if req_ctype is not None:
            fwd_headers["Content-Type"] = req_ctype

        try:
            status, body, ctype = await self._transport.post_raw(
                self._target, "/handle", raw,
                timeout_s=self._t_handle,
                headers=fwd_headers,
            )
        except TransportError as exc:
            log.warning("target %s failed: %s", self._target, exc)
            return 502, {"error": "target unavailable"}

        return status, body, ctype
