"""GossipService периодический обмен таблицей узлов и приём gossip

ДЕМО версия работает без FailureDetector
статусы ставит только детектор, поэтому в демо все узлы остаются живыми
reprobe_run и push_self заглушки этапа 2

MembershipTable (что зовём)
table.snapshot()        -> список записей (dict или dataclass)
table.merge(list[dict]) -> None
table.alive_ids()       -> list[node_id] без себя
table.apply_hints(is_in_active: bool, continuously_live: bool) -> None
table.on_distributor_unreachable() -> None
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

from ...transport import Transport, TransportError

log = logging.getLogger(__name__)

GOSSIP_PATH = "/internal/gossip"
_STATUSES = {"alive", "suspect", "dead"}


def _status_str(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    name = getattr(value, "name", None)
    return name.lower() if name else str(value).lower()


def _to_wire(entry: Any) -> dict:
    '''запись таблицы -> wire-формат, локальных времён здесь нет намеренно'''
    get = entry.get if isinstance(entry, dict) else lambda k, d=None: getattr(entry, k, d)
    return {
        "node_id": get("node_id"),
        "addr": get("addr", ""),
        "status": _status_str(get("status")),
        "incarnation": int(get("incarnation", 0)),
        "ready": bool(get("ready", False)),
    }


def _normalize(raw: Any) -> list[dict]:
    '''входящий table -> список валидных dict, мусор молча отбрасываем'''
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        node_id = item.get("node_id")
        status = _status_str(item.get("status", ""))
        if not isinstance(node_id, str) or status not in _STATUSES:
            continue
        try:
            incarnation = int(item.get("incarnation", 0))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "node_id": node_id,
                "addr": item.get("addr", ""),
                "status": status,
                "incarnation": incarnation,
                "ready": bool(item.get("ready", False)),
            }
        )
    return out


class GossipService:
    def __init__(
        self,
        table,
        transport: Transport,
        *,
        self_id: str,
        nodes: dict[str, str],          # node_id -> addr, из конфига (статический состав)
        distributor_addr: Optional[str] = None,
        g_s: float = 0.5,               # период рассылки
        f: int = 2,                     # число случайных адресатов узлов
        gossip_timeout_s: float = 0.5,
        t_reprobe_s: float = 5.0,       # понадобится на этапе 2
    ) -> None:
        self._table = table
        self._transport = transport
        self._self_id = self_id
        self._nodes = nodes
        self._distributor = distributor_addr
        self._g = g_s
        self._f = f
        self._timeout = gossip_timeout_s
        self._t_reprobe = t_reprobe_s
        self._reprobe_cursor = 0        # этап 2

    # --- приём вызывается транспортом на POST /internal/gossip ---

    async def on_gossip(self, payload: dict) -> dict:
        """принимаем от любого отправителя, включая тех, кого считаем мёртвыми,
        и в собственном карантине, гейт по ready стоит только на /internal/check"""
        remote = _normalize(payload.get("table"))
        if remote:
            self._table.merge(remote)
        else:
            log.debug("gossip from %s: пустая/невалидная таблица", payload.get("sender"))
        return {"table": self._snapshot()}

    # --- периодическая рассылка ---

    async def run(self) -> None:
        '''Бесконечный цикл раз в g работает и когда мы сами Suspect'''
        while True:
            try:
                await self._round()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("gossip round failed")
            await asyncio.sleep(self._g)

    async def _round(self) -> None:
        snapshot = self._snapshot()  # один снимок на раунд
        tasks = [
            self._send_to_node(node_id, snapshot)
            for node_id in self._pick_targets()
        ]
        if self._distributor:
            tasks.append(self._send_to_distributor(snapshot))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _pick_targets(self) -> list[str]:
        """f случайных Alive (без себя), адреса берём из конфига"""
        alive = [nid for nid in self._table.alive_ids() if nid in self._nodes]
        if not alive:
            return []
        return random.sample(alive, min(self._f, len(alive)))

    def _snapshot(self) -> list[dict]:
        return [_to_wire(entry) for entry in self._table.snapshot()]

    async def _send_to_node(self, node_id: str, snapshot: list[dict]) -> None:
        try:
            resp = await self._transport.post(
                self._nodes[node_id],
                GOSSIP_PATH,
                {"sender": self._self_id, "table": snapshot},
                timeout_s=self._timeout,
            )
        except TransportError as exc:
            # неудача gossip НЕ ставит Suspect это зона SWIM
            log.debug("gossip to %s failed: %s", node_id, exc)
            return
        remote = _normalize(resp.get("table"))
        if remote:
            self._table.merge(remote)

    async def _send_to_distributor(self, snapshot: list[dict]) -> None:
        try:
            resp = await self._transport.post(
                self._distributor,
                GOSSIP_PATH,
                {"sender": self._self_id, "table": snapshot},
                timeout_s=self._timeout,
            )
        except TransportError as exc:
            log.debug("distributor unreachable: %s", exc)
            self._table.on_distributor_unreachable()
            return

        # распределитель присылает table: [] только флаги маршрутизации
        if "is_in_active" not in resp or "continuously_live" not in resp:
            log.warning("distributor response without hints: %s", resp)
            return
        self._table.apply_hints(
            bool(resp["is_in_active"]), bool(resp["continuously_live"])
        )

    # --- этап 2 зависит от FailureDetector ---

    async def reprobe_run(self) -> None:
        """TODO(этап 2): раз в T_reprobe слать gossip одному dead из конфигурации
        (round robin курсором), сливать ответ неудача не даёт Suspect
        В демо dead статусов нет их ставит только детектор
        """
        raise NotImplementedError("reprobe появится вместе с detector.py (этап 2)")

    async def push_self(self) -> None:
        """TODO(этап 2) немедленная рассылка своей записи после опровержения,
        чтобы не ждать ближайшего раунда g зовётся из detector.refute
        """
        raise NotImplementedError("push_self появится вместе с detector.py (этап 2)")
