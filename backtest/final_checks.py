"""Final checks on the configurations the optimisation pointed to.

1. 5-minute set, sessions BEFORE the 1-minute data starts (2026-08-31 .. 2026-10-09):
   never seen by the optimiser -> a genuine holdout (at coarser resolution).
2. 1-minute set, out-of-sample sessions: is the OOS gain more than random events give
   in the same sessions (pooled across instruments, same seed per instrument)?
"""
from __future__ import annotations

import json
from dataclasses import replace
from multiprocessing import get_context

import numpy as np
import pandas as pd

import run_backtest as RB
from ofi_engine import INSTRUMENTS, Params, Sim, prepare, proxy_events, random_events, summarise
from run_m5 import load

FUTURES = ["NQ", "ES", "GC", "CL"]
HOLDOUT_END = 20261010          # sessions strictly before the 1-minute data window
CONFIGS = {
    "EA defaults": {},
    "vol_mult=4": {"proxy_vol_mult": 4.0},
    "vol_mult=4 + trail": {"proxy_vol_mult": 4.0, "target_mode": "trail"},
}
N_NULL = 200
PREP = {}


def _null_m5(args):
    name, seed = args
    prm = replace(Params(), **CONFIGS[name])
    tot = {}
    for sym in FUTURES:
        P, ev = PREP[(name, sym)]
        tr = Sim(P, random_events(P, ev, np.random.default_rng(seed)), prm, INSTRUMENTS[sym]).run()
        tot[sym] = sum(t.r for t in tr if P["sess_id"][t.entry_bar] < HOLDOUT_END)
    return tot


def holdout_m5():
    rows = []
    for name, kw in CONFIGS.items():
        prm = replace(Params(), **kw)
        for sym in FUTURES:
            P = prepare(load(sym), prm, bar_seconds=300)
            PREP[(name, sym)] = (P, proxy_events(P, prm))
    pool = get_context("fork").Pool(4)
    for name, kw in CONFIGS.items():
        prm = replace(Params(), **kw)
        real, per = [], {}
        for sym in FUTURES:
            P, ev = PREP[(name, sym)]
            tr = [t for t in Sim(P, ev, prm, INSTRUMENTS[sym]).run() if P["sess_id"][t.entry_bar] < HOLDOUT_END]
            real += tr
            per[sym] = round(sum(t.r for t in tr), 2)
        nulls = pool.map(_null_m5, [(name, sd) for sd in range(1, N_NULL + 1)])
        pooled_null = np.array([sum(d.values()) for d in nulls])
        s = summarise(real, 0, name)
        sessions = len({int(x) for x in PREP[(name, 'NQ')][0]["sess_id"] if 0 < x < HOLDOUT_END})
        rows.append(dict(check="M5 holdout (unseen sessions)", config=name, sessions=sessions, n=s["n"],
                         mean_r=s["mean_r"], total_r=s["total_r"], sqn=s["sqn"], mean_ex_top5=s["mean_ex_top5"],
                         per_instrument=json.dumps(per), null_mean=float(pooled_null.mean()),
                         pct_vs_null=float((pooled_null < s["total_r"]).mean())))
        print(rows[-1], flush=True)
    pool.close()
    return rows


def _null_oos(args):
    name, seed = args
    prm = replace(Params(), **CONFIGS[name])
    key = prm.proxy_vol_mult
    tot = 0.0
    for sym in FUTURES:
        tr, _ = RB.run_one(sym, prm, key, seed)
        _, OOS = RB.split_sessions(RB.DATA[sym]["P"])
        tot += sum(t.r for t in RB.trades_in(sym, tr, OOS))
    return tot


def oos_1m():
    RB.load_all()
    rows = []
    pool = get_context("fork").Pool(4)
    for name, kw in CONFIGS.items():
        prm = replace(Params(), **kw)
        real = []
        for sym in FUTURES:
            tr, _ = RB.run_one(sym, prm, prm.proxy_vol_mult)
            _, OOS = RB.split_sessions(RB.DATA[sym]["P"])
            real += RB.trades_in(sym, tr, OOS)
        null = np.array(pool.map(_null_oos, [(name, sd) for sd in range(1, N_NULL + 1)]))
        s = summarise(real, 0, name)
        rows.append(dict(check="M1 out-of-sample", config=name, n=s["n"], mean_r=s["mean_r"],
                         total_r=s["total_r"], sqn=s["sqn"], mean_ex_top5=s["mean_ex_top5"],
                         null_mean=float(null.mean()), pct_vs_null=float((null < s["total_r"]).mean())))
        print(rows[-1], flush=True)
    pool.close()
    return rows


if __name__ == "__main__":
    rows = holdout_m5() + oos_1m()
    pd.DataFrame(rows).to_csv(RB.OUT / "final_checks.csv", index=False)
    (RB.OUT / "final_checks.json").write_text(json.dumps(rows, indent=2, default=float))
