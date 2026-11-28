"""membership_table.py локальное представление узла о составе кластера. ДЕМО.

все методы синхронные (без await) в однопоточном asyncio операции атомарны
dead_since_ns / quarantine_until_ns по сети не передаются
своя запись по ready и статусу из чужих таблиц не перезаписывается OR по ready применяется только к чужим записям
dead_since_ns ставится при переходе в Dead и при Dead с большей инкарнацией, повтор той же записи его не сдвигает
T_start перезапускается только по переходу состояния, не по повтору флага
_check_pause вызывается ДО проверки истечения карантина

mark_suspect / mark_dead / refute_self заглушки
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Callable, Optional

log = logging.getLogger(__name__)


class Status(IntEnum):
    ALIVE = 0
    SUSPECT = 1
    DEAD = 2


_STATUS_BY_NAME = {s.name.lower(): s for s in Status}


@dataclass
class NodeEntry:
    node_id: str
    addr: str
    status: Status
    incarnation: int
    ready: bool
    dead_since_ns: Optional[int] = None        # локальное, в snapshot не попадает
    quarantine_until_ns: Optional[int] = None  # осмысленно только для своей записи


@dataclass(frozen=True)
class MembershipView:
    node_id: str
    status: Status
    dead_since_ns: Optional[int]


class MembershipTable:
    def __init__(
        self,
        *,
        self_id: str,
        nodes: dict[str, str],                 # node_id -> addr, статический состав
        clock_ns: Optional[Callable[[], int]] = None,
        wall_ms: Optional[Callable[[], int]] = None,
        t_start_s: float = 13.0,               # T + T_grace
        pause_gap_s: float = 1.0,              # порог детекта паузы
    ) -> None:
        if self_id not in nodes:
            raise ValueError(f"self_id={self_id} отсутствует в конфиге узлов")
        self._self_id = self_id
        self._nodes = dict(nodes)
        self._clock_ns = clock_ns or time.monotonic_ns
        self._wall_ms = wall_ms or (lambda: int(time.time() * 1000))
        self._t_start_ns = int(t_start_s * 1_000_000_000)
        self._pause_gap_ns = int(pause_gap_s * 1_000_000_000)

        self._entries: dict[str, NodeEntry] = {}
        self._prev_in_active: Optional[bool] = None
        self._prev_cont_live: Optional[bool] = None
        self._prev_distributor_ok: Optional[bool] = None
        self._last_tick_ns = self._clock_ns()

        # хук к детектору
        self.on_self_suspect: Optional[Callable[[int], None]] = None

    # --- инициализация ---

    def init_from_config(self) -> None:
        now = self._clock_ns()
        self._entries = {}
        for node_id, addr in self._nodes.items():
            if node_id == self._self_id:
                self._entries[node_id] = NodeEntry(
                    node_id=node_id,
                    addr=addr,
                    status=Status.ALIVE,
                    incarnation=self._wall_ms(),
                    ready=False,
                    quarantine_until_ns=now + self._t_start_ns,
                )
            else:
                self._entries[node_id] = NodeEntry(
                    node_id=node_id, addr=addr, status=Status.ALIVE,
                    incarnation=0, ready=True,
                )
        self._prev_in_active = None
        self._prev_cont_live = None
        self._prev_distributor_ok = None
        self._last_tick_ns = now
        log.info("таблица инициализирована: self=%s, узлов=%d, карантин %.1fс",
                 self._self_id, len(self._entries), self._t_start_ns / 1e9)

    # --- слияние, единственный вход чужих данных ---

    def merge(self, remote: list[dict]) -> None:
        """remote — уже нормализованные словари из gossip._normalize."""
        now = self._clock_ns()
        for item in remote:
            node_id = item.get("node_id")
            entry = self._entries.get(node_id)
            if entry is None:
                continue  # состав статический, авторитет конфиг

            status = _STATUS_BY_NAME.get(str(item.get("status", "")).lower())
            if status is None:
                continue
            try:
                inc = int(item.get("incarnation", 0))
            except (TypeError, ValueError):
                continue
            ready = bool(item.get("ready", False))

            if node_id == self._self_id:
                if status in (Status.SUSPECT, Status.DEAD) and inc >= entry.incarnation:
                    if self.on_self_suspect is not None:
                        self.on_self_suspect(inc)
                    else:
                        log.debug("слух о себе %s inc=%d: детектора нет, игнор",
                                  status.name, inc)
                continue

            remote_key = (inc, status)
            local_key = (entry.incarnation, entry.status)

            if remote_key > local_key:
                entry.incarnation = inc
                entry.status = status
                entry.ready = ready
                if status == Status.DEAD:
                    # переход в Dead либо Dead с большей инкарнацией
                    # повтор той же записи сюда не попадает
                    entry.dead_since_ns = now
                else:
                    entry.dead_since_ns = None
            elif remote_key == local_key:
                entry.ready = entry.ready or ready
            # remote_key < local_key — устаревшее, игнорируем

    # --- карантин и пауза ---

    def _start_quarantine(self, now_ns: int, reason: str) -> None:
        me = self._entries[self._self_id]
        me.ready = False
        me.quarantine_until_ns = now_ns + self._t_start_ns
        log.info("карантин T_start запущен заново: %s", reason)

    def _check_pause(self, now_ns: int) -> None:
        gap = now_ns - self._last_tick_ns
        self._last_tick_ns = now_ns
        if gap > self._pause_gap_ns:
            self._start_quarantine(now_ns, f"разрыв тиков {gap / 1e9:.2f}с (пауза?)")

    def _refresh_ready(self, now_ns: int) -> None:
        me = self._entries[self._self_id]
        if (not me.ready
                and me.quarantine_until_ns is not None
                and now_ns >= me.quarantine_until_ns):
            me.ready = True
            me.quarantine_until_ns = None
            log.info("карантин истёк, ready=True")

    def sweep(self, now_ns: Optional[int] = None) -> None:
        now = self._clock_ns() if now_ns is None else now_ns
        self._check_pause(now)
        self._refresh_ready(now)

    def self_ready(self) -> bool:
        now = self._clock_ns()
        self._check_pause(now)
        self._refresh_ready(now)
        return self._entries[self._self_id].ready

    # --- hints распределителя только по переходам (edge-triggered) ---

    def apply_hints(self, is_in_active: bool, continuously_live: bool) -> None:
        now = self._clock_ns()
        prev_active = self._prev_in_active
        prev_cont = self._prev_cont_live
        self._prev_in_active = is_in_active
        self._prev_cont_live = continuously_live
        self._prev_distributor_ok = True

        entered_active = prev_active is False and is_in_active
        lost_continuity = prev_cont is True and not continuously_live
        if entered_active:
            self._start_quarantine(now, "вход в активную часть")
        elif lost_continuity:
            self._start_quarantine(now, "выпал из списка живых")
        # первый ответ (prev=None) и повтор того же флага — no-op
        # иначе карантин перезапускался бы вечно и узел не стал бы ready

    def on_distributor_unreachable(self) -> None:
        was_ok = self._prev_distributor_ok
        self._prev_distributor_ok = False
        if was_ok is True:
            self._start_quarantine(self._clock_ns(), "распределитель недоступен")
        # повторные неудачи карантин не продлевают

    # --- снимки наружу ---

    def snapshot(self) -> list[NodeEntry]:
        now = self._clock_ns()
        self._check_pause(now)
        self._refresh_ready(now)
        return [replace(e) for e in self._entries.values()]

    def read_membership(self) -> tuple[MembershipView, ...]:
        return tuple(
            MembershipView(e.node_id, e.status, e.dead_since_ns)
            for e in self._entries.values()
        )

    def alive_ids(self) -> list[str]:
        return [nid for nid, e in self._entries.items()
                if e.status == Status.ALIVE and nid != self._self_id]

    # --- этап 2: зовёт только FailureDetector ---

    def mark_suspect(self, node_id: str) -> None:
        raise NotImplementedError("этап 2: локальное решение SWIM")

    def mark_dead(self, node_id: str) -> None:
        raise NotImplementedError("этап 2: локальное решение SWIM")

    def refute_self(self, observed_inc: int) -> bool:
        raise NotImplementedError("этап 2: опровержение через детектор")