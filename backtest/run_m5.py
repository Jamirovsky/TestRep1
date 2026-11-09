"""Robustness check: same EA rules on 60 days of 5-minute futures bars (InpProxyTF = M5).

Twice the sessions of the 1-minute set, at coarser resolution. Runs EA defaults and any
configurations passed as JSON on the command line, each against the random-event null.

    python run_m5.py '{"require_key_level": false, "rev_mode": "aggressive"}'
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from multiprocessing import get_context

import numpy as np
import pandas as pd

from fetch_data import DATA as DATADIR
from ofi_engine import INSTRUMENTS, Params, Sim, prepare, proxy_events, random_events, summarise

FUTURES = ["NQ", "ES", "GC", "CL"]
PREP = {}


def load(sym):
    df = pd.read_csv(DATADIR / f"{sym}_F_5m.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


def _null(args):
    sym, prm, seed = args
    P, ev = PREP[sym]
    tr = Sim(P, random_events(P, ev, np.random.default_rng(seed)), prm, INSTRUMENTS[sym]).run()
    return float(sum(t.r for t in tr))


def evaluate(label, prm, pool, n_null=200):
    rows = []
    pooled = []
    for sym in FUTURES:
        P = prepare(load(sym), prm, bar_seconds=300)
        ev = proxy_events(P, prm)
        PREP[sym] = (P, ev)
    for sym in FUTURES:
        P, ev = PREP[sym]
        sim = Sim(P, ev, prm, INSTRUMENTS[sym])
        tr = sim.run()
        pooled += tr
        s = summarise(tr, sim.bars_in_market, sym)
        null = np.array(pool.map(_null, [(sym, prm, sd) for sd in range(1, n_null + 1)]))
        s["sessions"] = len(set(int(x) for x in P["sess_id"][P["in_sess"]]))
        s["null_total_r_mean"] = float(null.mean())
        s["pct_vs_null"] = float((null < s["total_r"]).mean())
        rows.append(s)
    s = summarise(pooled, 0, "POOLED")
    rows.append(s)
    df = pd.DataFrame(rows)
    print(f"\n== {label}")
    print(df[["label", "n", "mean_r", "total_r", "win", "pf", "sqn", "mean_ex_top5"] +
             [c for c in ("sessions", "null_total_r_mean", "pct_vs_null") if c in df]].round(3).to_string(index=False))
    return df


if __name__ == "__main__":
    pool = get_context("fork").Pool(4)
    out = []
    base = Params()
    out.append(evaluate("EA defaults (M5 proxy)", base, pool).assign(config="defaults"))
    for arg in sys.argv[1:]:
        kw = json.loads(arg)
        prm = replace(base, **kw)
        out.append(evaluate(f"config {kw}", prm, pool).assign(config=json.dumps(kw)))
    pool.close()
    pd.concat(out).to_csv("out/m5_robustness.csv", index=False)
