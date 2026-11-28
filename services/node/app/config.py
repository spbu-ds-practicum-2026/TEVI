from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_ADDR_RE = re.compile(r"(?:https?://)?[\w.-]+:\d+")


@dataclass(frozen=True)
class NodeConfig:
    self_id: str
    nodes: dict[str, str]
    target_addr: str
    distributor_addr: str | None     
    L: int                           
    T_s: float
    T_grace_s: float
    t_handle_s: float
    g_s: float = 0.5
    f: int = 2
    gossip_timeout_s: float = 0.5
    sweep_interval_s: float = 0.2
    pause_gap_s: float = 1.0
    host: str = "0.0.0.0"
    port: int = 8080
    t_req_s: float | None = None
    # --- этап 2 (SWIM), в демо не используется ---
    p_s: float = 1.0
    t_ping_s: float = 0.5
    k: int = 2
    T_susp_s: float = 3.0
    T_reprobe_s: float = 5.0

    @property
    def n0(self) -> int:
        return len(self.nodes)

    @property
    def window_ns(self) -> int:
        return int(self.T_s * 1_000_000_000)

    @property
    def hold_ns(self) -> int:
        return int((self.T_s + self.T_grace_s) * 1_000_000_000)

    @property
    def t_start_s(self) -> float:
        return self.T_s + self.T_grace_s

    @classmethod
    def load(cls, path: str | None = None) -> "NodeConfig":
        path = path or os.environ.get("CONFIG_PATH", "config/cluster.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        raw_nodes = data.get("nodes")
        if isinstance(raw_nodes, list):   # формат списка объектов
            nodes = {str(i["node_id"]): str(i["addr"]) for i in raw_nodes}
        else:                             # формат словаря node_id -> addr
            nodes = {str(k): str(v) for k, v in (raw_nodes or {}).items()}

        cfg = cls(
            self_id=os.environ["NODE_ID"],
            nodes=nodes,
            target_addr=str(data.get("target_addr", "target:8080")),
            distributor_addr=data.get("distributor_addr") or None,
            L=int(data.get("L", 100)),
            T_s=float(data.get("T", 10.0)),
            T_grace_s=float(data.get("T_grace", 3.0)),
            t_handle_s=float(data.get("t_handle", 0.5)),
            g_s=float(data.get("g", 0.5)),
            f=int(data.get("f", 2)),
            gossip_timeout_s=float(data.get("gossip_timeout", 0.5)),
            sweep_interval_s=float(data.get("sweep_interval", 0.2)),
            pause_gap_s=float(data.get("pause_gap", 1.0)),
            host=str(data.get("host", "0.0.0.0")),
            port=int(data.get("port", 8080)),
            t_req_s=float(data["t_req"]) if data.get("t_req") is not None else None,
            p_s=float(data.get("p", 1.0)),
            t_ping_s=float(data.get("t_ping", 0.5)),
            k=int(data.get("k", 2)),
            T_susp_s=float(data.get("T_susp", 3.0)),
            T_reprobe_s=float(data.get("T_reprobe", 5.0)),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        """M4: проверки на старте по списку ревьюера (см. A4 в ТР)."""
        if self.n0 < 1:
            raise ValueError("список nodes в конфиге пуст")
        if self.self_id not in self.nodes:
            raise ValueError(f"NODE_ID={self.self_id} отсутствует в nodes")
        for node_id, addr in self.nodes.items():
            if not _ADDR_RE.fullmatch(addr):
                raise ValueError(f"некорректный адрес узла {node_id}: {addr!r}")
        if self.L < self.n0:
            raise ValueError(f"нарушено L >= n0: L={self.L}, n0={self.n0}")
        timers = {
            "T": self.T_s, "T_grace": self.T_grace_s, "t_handle": self.t_handle_s,
            "g": self.g_s, "gossip_timeout": self.gossip_timeout_s,
            "sweep_interval": self.sweep_interval_s, "pause_gap": self.pause_gap_s,
        }
        for name, value in timers.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"таймер {name} должен быть конечным и > 0, получено {value}")
        if self.t_req_s is not None and self.t_req_s <= self.t_handle_s:
            log.warning("бюджет таймаутов: t_req=%.2f <= t_handle=%.2f",
                        self.t_req_s, self.t_handle_s)
