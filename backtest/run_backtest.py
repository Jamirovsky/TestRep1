"""Backtest + optimisation of OrderFlowIcebergEA with research controls.

Usage:
    python run_backtest.py baseline        # EA defaults + random-event control
    python run_backtest.py optimise        # in-sample grid, max-statistic null, out-of-sample
    python run_backtest.py all

Controls, per the trading-brain lab rules:
  * random-event null (same events per session and zone heights, random times)
  * long/short split and instrument drift (benchmark)
  * R per bar in market, distribution (p90, max, mean without the best 5%)
  * per-instrument breakdown alongside every pooled number
  * max-statistic bar for the grid search (best-of-grid on random events)
  * in-sample / out-of-sample split by session
"""
from __future__ import annotations

import itertools
import json
import math
import sys
import time
from dataclasses import asdict, replace
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

from fetch_data import yahoo_1m
from ofi_engine import INSTRUMENTS, Params, Sim, prepare, proxy_events, random_events, summarise
from tick_events import bars_from_trades, detect_events, events_to_bars, load_trades

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
FUTURES = ["NQ", "ES", "GC", "CL"]
IS_FRACTION = 0.6
N_NULL = 200            # random-event seeds for a single configuration
N_MAXSTAT = 20          # random-event seeds for the max-statistic null of the grid search

# BTC thresholds (contracts are BTC); chosen so event rates bracket the futures proxy rate
BTC_THRESHOLDS = [(50, 100), (100, 200), (200, 400)]
BTC_DEFAULT = (100, 200)

# ------------------------------------------------------------------ data (module globals
# so forked workers share them without pickling)
DATA: dict = {}


def load_all():
    if DATA:
        return
    cache = Path(__file__).resolve().parent / "data" / "prepared.pkl"
    if cache.exists():
        import pickle
        DATA.update(pickle.loads(cache.read_bytes()))
        return
    base = Params()
    for sym in FUTURES:
        P = prepare(yahoo_1m(f"{sym}=F"), base, bar_seconds=60)
        DATA[sym] = dict(P=P, events={m: proxy_events(P, replace(base, proxy_vol_mult=m)) for m in (2.5, 3.0, 4.0)})
    tr = load_trades()
    b1 = bars_from_trades(tr, "1min")
    b10 = bars_from_trades(tr, "10s")
    P = prepare(b10, base, bar_seconds=10)
    evs = {}
    for ice, sr in BTC_THRESHOLDS:
        ev = detect_events(tr, INSTRUMENTS["BTC"].tick, replace(base, min_iceberg=ice, min_stoprun=sr), b1)
        evs[(ice, sr)] = events_to_bars(ev, P["index"], 10)
    DATA["BTC"] = dict(P=P, events=evs)
    del tr
    import pickle
    cache.write_bytes(pickle.dumps(dict(DATA)))


def split_sessions(P):
    sess = sorted(set(int(s) for s in P["sess_id"][P["in_sess"]]))
    k = int(round(len(sess) * IS_FRACTION))
    return set(sess[:k]), set(sess[k:])


def run_one(sym: str, prm: Params, event_key, seed: int | None = None):
    d = DATA[sym]
    P = d["P"]
    ev = d["events"][event_key]
    if seed is not None:
        ev = random_events(P, ev, np.random.default_rng(seed))
    sim = Sim(P, ev, prm, INSTRUMENTS[sym], seed=seed or 0)
    tr = sim.run()
    return tr, sim.bars_in_market


def trades_in(sym, trades, sessions):
    sid = DATA[sym]["P"]["sess_id"]
    return [t for t in trades if int(sid[t.entry_bar]) in sessions]


def default_key(sym):
    return BTC_DEFAULT if sym == "BTC" else 3.0


def drift(sym):
    """Benchmark: mean session open->close move in units of ATR, and its long-only R analogue."""
    P = DATA[sym]["P"]
    rows = []
    for s in sorted(set(int(x) for x in P["sess_id"][P["in_sess"]])):
        idx = np.flatnonzero((P["sess_id"] == s) & P["in_sess"])
        a = np.nanmean(P["atr"][idx])
        rows.append((P["close"][idx[-1]] - P["open"][idx[0]]) / a if a > 0 else np.nan)
    return float(np.nanmean(rows)), len(rows)


# ------------------------------------------------------------------ baseline


def _null_worker(args):
    sym, prm, key, seed = args
    tr, bim = run_one(sym, prm, key, seed)
    r = np.array([t.r for t in tr])
    return sym, seed, len(r), float(r.sum()), float(r.mean()) if len(r) else float("nan")


def baseline():
    load_all()
    prm = Params()
    rows, out = [], {}
    pool = get_context("fork").Pool(4)
    for sym in FUTURES + ["BTC"]:
        key = default_key(sym)
        tr, bim = run_one(sym, prm, key)
        s = summarise(tr, bim, sym)
        s["long_n"] = sum(t.dir > 0 for t in tr)
        s["long_r"] = float(sum(t.r for t in tr if t.dir > 0))
        s["short_r"] = float(sum(t.r for t in tr if t.dir < 0))
        s["drift_atr_per_session"], s["sessions"] = drift(sym)
        s["events"] = len(DATA[sym]["events"][key])
        nulls = pool.map(_null_worker, [(sym, prm, key, sd) for sd in range(1, N_NULL + 1)])
        tot = np.array([x[3] for x in nulls])
        s["null_total_r_mean"] = float(tot.mean())
        s["null_total_r_p95"] = float(np.percentile(tot, 95))
        s["pct_vs_null"] = float((tot < s["total_r"]).mean())
        rows.append(s)
        out[sym] = [asdict(t) for t in tr]
        print(fmt_row(s), flush=True)
    pool.close()
    # pooled futures
    allr = [t for sym in FUTURES for t in map(lambda d: d, out[sym])]
    pooled = np.array([t["r"] for t in allr])
    print(f"POOLED futures: n={len(pooled)} meanR={pooled.mean():.3f} totalR={pooled.sum():.2f}")
    pd.DataFrame(rows).to_csv(OUT / "baseline_summary.csv", index=False)
    (OUT / "baseline_trades.json").write_text(json.dumps(out, default=float))
    return rows


def fmt_row(s):
    keys = ["label", "n", "mean_r", "total_r", "win", "pf", "sqn", "p90", "max", "mean_ex_top5",
            "r_per_bar", "null_total_r_mean", "null_total_r_p95", "pct_vs_null"]
    return " ".join(f"{k}={s[k]:.3f}" if isinstance(s.get(k), float) else f"{k}={s.get(k)}" for k in keys if k in s)


# ------------------------------------------------------------------ optimisation

TARGETS = [("next_level", 3.0), ("r", 2.0), ("r", 3.0), ("trail", 3.0)]


def grid(asset: str):
    keys = [2.5, 3.0, 4.0] if asset == "futures" else BTC_THRESHOLDS
    for key, kl, (tm, tr_), stop, rev in itertools.product(
            keys, [True, False], TARGETS, [0.75, 1.15], ["none", "aggressive", "bib"]):
        yield key, Params(require_key_level=kl, target_mode=tm, target_r=tr_, stop_atr=stop, rev_mode=rev, rev_ext=2)


def describe(key, prm):
    return (f"events={key} key_level={prm.require_key_level} target={prm.target_mode}"
            f"{'' if prm.target_mode in ('trail', 'next_level') else prm.target_r} stop_atr={prm.stop_atr} rev={prm.rev_mode}")


def score(trades):
    r = np.array([t.r for t in trades])
    if len(r) < 20:
        return -np.inf, len(r), float(r.sum()) if len(r) else 0.0
    sd = r.std(ddof=1)
    return (r.mean() / sd * math.sqrt(len(r)) if sd > 0 else -np.inf), len(r), float(r.sum())


def _grid_worker(args):
    asset, gi, key, prm, seed = args
    syms = FUTURES if asset == "futures" else ["BTC"]
    is_tr, oos_tr, per = [], [], {}
    for sym in syms:
        tr, _ = run_one(sym, prm, key, seed)
        IS, OOS = split_sessions(DATA[sym]["P"])
        a, b = trades_in(sym, tr, IS), trades_in(sym, tr, OOS)
        is_tr += a
        oos_tr += b
        per[sym] = (len(a), float(sum(t.r for t in a)), len(b), float(sum(t.r for t in b)))
    s_is = score(is_tr)
    s_oos = score(oos_tr)
    return gi, seed, s_is, s_oos, per


def optimise(asset: str):
    load_all()
    configs = list(grid(asset))
    pool = get_context("fork").Pool(4)
    t0 = time.time()
    real = pool.map(_grid_worker, [(asset, gi, k, p, None) for gi, (k, p) in enumerate(configs)])
    print(f"[{asset}] grid of {len(configs)} done in {time.time() - t0:.0f}s", flush=True)
    real.sort(key=lambda x: x[2][0], reverse=True)
    best_gi = real[0][0]
    # max-statistic null: best in-sample score of the whole grid on random events
    t0 = time.time()
    seeds = list(range(1001, 1001 + N_MAXSTAT))
    null = pool.map(_grid_worker, [(asset, gi, k, p, sd) for sd in seeds for gi, (k, p) in enumerate(configs)])
    pool.close()
    best_null = {}
    for gi, sd, s_is, _, _ in null:
        best_null[sd] = max(best_null.get(sd, -np.inf), s_is[0])
    bn = np.array(sorted(best_null.values()))
    print(f"[{asset}] max-stat null ({N_MAXSTAT} seeds x {len(configs)}) in {time.time() - t0:.0f}s", flush=True)
    rows = []
    for gi, _, s_is, s_oos, per in real:
        k, p = configs[gi]
        rows.append(dict(config=describe(k, p), is_sqn=s_is[0], is_n=s_is[1], is_total_r=s_is[2],
                         oos_sqn=s_oos[0], oos_n=s_oos[1], oos_total_r=s_oos[2],
                         per_instrument=json.dumps(per)))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"grid_{asset}.csv", index=False)
    best = rows[0]
    res = dict(asset=asset, n_configs=len(configs), best=best,
               best_is_sqn_pct_vs_maxstat_null=float((bn < best["is_sqn"]).mean()),
               maxstat_null_p50=float(np.median(bn)), maxstat_null_p95=float(np.percentile(bn, 95)),
               default=[r for r in rows if r["config"] == describe(*default_cfg(asset))][0])
    (OUT / f"optimise_{asset}.json").write_text(json.dumps(res, indent=2, default=float))
    print(json.dumps(res, indent=2, default=float), flush=True)
    return res, configs[best_gi]


def default_cfg(asset):
    key = BTC_DEFAULT if asset == "btc" else 3.0
    return key, Params()


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("baseline", "all"):
        baseline()
    if what in ("optimise", "all"):
        optimise("futures")
        optimise("btc")
