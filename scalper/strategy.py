"""Live decision logic that re-uses the exact backtest engine.

`decide()` answers: "the 15-minute bar that just closed - should sleeve X open a
trade at the next minute, and with what stop / target?"  It replays the engine
over the recent history so the memory (shadow-trade expectancies) is identical to
what the backtest would have at that moment, then applies the same gate and
sizing rules.  tests/test_live_consistency.py checks it against the backtest.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass
import numpy as np
import pandas as pd

from . import engine
from .backtest import Market, cost_array, exe_vec, signals, COSTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=None):
    path = path or os.path.join(ROOT, "config", "final_strategy.json")
    return json.load(open(path))


@dataclass
class Decision:
    sleeve: str
    direction: int          # +1 buy, -1 sell
    stop_distance: float    # USD per BTC from the entry fill
    target_distance: float
    size: float             # BTC, already rounded to the broker step
    max_hold_minutes: int
    cell: int
    memory_expectancy: float
    signal_time: pd.Timestamp


def replay_memory(m: Market, p, i_start: int, i_end: int, sigs=None, cost=None):
    """Run the engine on 1m bars [i_start, i_end) and return (memory, trades)."""
    sigs = sigs or signals(m, p)
    sig_idx, D, bucket, a = sigs
    sel = (sig_idx >= i_start) & (sig_idx < i_end - 1) & (D != 0).any(axis=1)
    tr, deq, mem = engine.run(m.o1[i_start:i_end], m.h1[i_start:i_end], m.l1[i_start:i_end],
                              m.c1[i_start:i_end], m.mod[i_start:i_end], m.day[i_start:i_end],
                              sig_idx[sel] - i_start, D[sel], bucket[sel], a[sel], int(p["tf"]),
                              exe_vec(p), cost_array(cost), np.zeros((engine.NCELL, 2)))
    return mem, tr


def decide(df1m: pd.DataFrame, sleeve: dict, equity_usd: float, cost=None, replay_days=60,
           replay_start=None, m: Market = None, sigs=None):
    """Decision for the bar that closes at the LAST row of df1m (mid prices, 1m bars).

    Returns a Decision or None.  `equity_usd` is the equity allocated to this sleeve.
    """
    p = sleeve["params"]
    m = m or Market(df1m)
    sigs = sigs or signals(m, p)
    sig_idx, D, bucket, a = sigs
    last = len(m.c1) - 1
    k = np.searchsorted(sig_idx, last)
    if k >= len(sig_idx) or sig_idx[k] != last:
        return None                       # no TF bar closed on this minute
    if not (D[k] != 0).any():
        return None
    c = {**COSTS, **(cost or {})}
    stop_d = p["sl_k"] * a[k]
    if stop_d < p["min_stop_spread"] * c["spread"]:
        return None
    i0 = replay_start if replay_start is not None else max(0, last + 1 - replay_days * 1440)
    mem, _ = replay_memory(m, p, i0, last + 1, sigs=sigs, cost=cost)
    best_f, best_s = -1, -1e18
    for f in range(engine.NFAM):
        dr = int(D[k, f])
        if dr == 0:
            continue
        cl = engine.cell_of(f, dr, int(bucket[k]))
        if mem[cl, 1] >= p["mem_warm"] and mem[cl, 0] > p["mem_thr"] and mem[cl, 0] > best_s:
            best_f, best_s = f, mem[cl, 0]
    if best_f < 0:
        return None
    dr = int(D[k, best_f])
    px = m.c1[last] + dr * c["spread"] / 2       # proxy for next open; broker fill decides
    r = p["risk"] * min(2.0, max(0.25, 1.0 + p["mem_k"] * best_s))
    sz = equity_usd * r / (stop_d + c["slip"])
    sz = min(sz, equity_usd * c["leverage"] * c["margin_use"] / px)
    sz = np.floor(sz / c["size_step"] + 1e-9) * c["size_step"]
    if sz < c["min_size"] - 1e-12:      # same minimum-lot rule as the engine
        mn = c["min_size"]
        if (mn * (stop_d + c["slip"]) <= c.get("minlot_risk_cap", 0.0) * equity_usd
                and mn * px <= equity_usd * c["leverage"] * c["margin_use"]):
            sz = mn
    if sz < c["min_size"] - 1e-12:
        return None
    cl = engine.cell_of(best_f, dr, int(bucket[k]))
    return Decision(sleeve.get("id", "sleeve"), dr, float(stop_d), float(p["tp_k"] * a[k]), float(round(sz, 6)),
                    int(p["max_hold"] * p["tf"]), int(cl), float(best_s if np.isfinite(best_s) else 0.0),
                    m.df1.index[last])


def memory_table(mem):
    """Human readable view of the memory (non-empty cells)."""
    rows = []
    for f in range(engine.NFAM):
        for b in range(engine.NBUCKET):
            for d in (-1, 1):
                cl = engine.cell_of(f, d, b)
                if mem[cl, 1] > 0:
                    rows.append({"family": engine.FAMILY_NAMES[f], "bucket": b,
                                 "dir": "long" if d > 0 else "short",
                                 "ew_R": round(float(mem[cl, 0]), 3), "n": int(mem[cl, 1])})
    return rows
