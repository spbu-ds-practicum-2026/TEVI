from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque

from .clock import clock_ns, wall_ms
from .config import NodeConfig
from .handler import NodeHandler
from .transport import Transport
from .services.membership.gossip import GossipService
from .services.membership.membership_table import MembershipTable
from .services.rate_limiter.quota_calculator import QuotaCalculator
from .services.rate_limiter.rate_limiter import RateLimiter
from .services.rate_limiter.window_store import WindowStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")

admission_log = logging.getLogger("admission")
admission_log.propagate = False
_adm_handler = logging.StreamHandler()
_adm_handler.setFormatter(logging.Formatter("%(message)s"))
admission_log.addHandler(_adm_handler)
admission_log.setLevel(logging.INFO)

def build_limiter(cfg: NodeConfig):
    window_ns = cfg.window_ns
    store = WindowStore(
        window_ns=window_ns,
        idle_ttl_ns=window_ns,
        windows=defaultdict(deque),
    )
    quota_calculator = QuotaCalculator(limit=cfg.L, n_0=cfg.n0)
    limiter = RateLimiter(store=store, quota_calculator=quota_calculator, clock_ns=clock_ns)
    log.info("лимитер Егора: L=%d, n_0=%d, q=%d, окно %.1fс",
             cfg.L, cfg.n0, cfg.L // cfg.n0, cfg.T_s)
    return limiter, store


async def _ticker(table: MembershipTable, interval_s: float) -> None:
    while True:
        table.sweep()
        await asyncio.sleep(interval_s)


async def _evictor(store, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        removed = store.evict_idle(clock_ns())
        if removed:
            log.debug("evict_idle: удалено %d простаивающих окон", removed)


def _make_gossip_route(gossip: GossipService):
    async def route(raw: bytes, headers: dict):
        try:
            payload = json.loads(raw)
        except ValueError:
            return 400, {"error": "invalid json"}
        return await gossip.on_gossip(payload)
    return route


async def main() -> None:
    cfg = NodeConfig.load()      # M4: общий config/cluster.json через CONFIG_PATH, NODE_ID из env

    table = MembershipTable(
        self_id=cfg.self_id,
        nodes=cfg.nodes,
        clock_ns=clock_ns,
        wall_ms=wall_ms,
        t_start_s=cfg.t_start_s,
        pause_gap_s=cfg.pause_gap_s,
    )
    table.init_from_config()

    limiter, store = build_limiter(cfg)

    transport = Transport(host=cfg.host, port=cfg.port,
                          default_timeout_s=cfg.gossip_timeout_s)
    gossip = GossipService(
        table, transport,
        self_id=cfg.self_id,
        nodes=cfg.nodes,
        distributor_addr=cfg.distributor_addr,
        g_s=cfg.g_s, f=cfg.f,
        gossip_timeout_s=cfg.gossip_timeout_s,
        t_reprobe_s=cfg.T_reprobe_s,
    )
    handler = NodeHandler(
        table, limiter, transport,
        self_id=cfg.self_id,
        target_addr=cfg.target_addr,
        handle_timeout_s=cfg.t_handle_s,
    )

    transport.register("/internal/gossip", _make_gossip_route(gossip))
    transport.register("/internal/check", handler.handle)
    # Этап 2 /internal/ping, /internal/ping-req + table.on_self_suspect = detector.refute

    log.info("узел %s запущен: узлов=%d, L=%d, T=%.1fс, T_start=%.1fс",
             cfg.self_id, cfg.n0, cfg.L, cfg.T_s, cfg.t_start_s)

    server = asyncio.create_task(transport.start())
    background = [
        asyncio.create_task(gossip.run()),
        asyncio.create_task(_ticker(table, cfg.sweep_interval_s)),
    ]
    if store is not None:
        background.append(
            asyncio.create_task(_evictor(store, max(1.0, cfg.T_s / 2)))
        )
    try:
        await server          # uvicorn сам ловит SIGTERM (docker stop)
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await transport.aclose()


if __name__ == "__main__":
    asyncio.run(main())
