"""Единый источник времени узла.

ЕГОР: твои WindowStore и QuotaCalculator должны брать время отсюда же.
Если clock_ns будет разным, арифметика T_hold по нашему dead_since_ns поедет.
ВИТАЛИЙ: отметки в журнале допусков — те же монотонные ns, что и у тебя в ts.
"""
from __future__ import annotations

import time


def clock_ns() -> int:
    return time.monotonic_ns()


def wall_ms() -> int:
    return int(time.time() * 1000)