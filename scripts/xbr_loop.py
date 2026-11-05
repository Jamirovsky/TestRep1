#!/usr/bin/env python3
"""XBRUSD optimisation loop, protocol v2: fit on 2019-2024, rank by year-by-year consistency.

Rounds 1-2 fitted on 2019-2022 and validated on 2023-2024; every configuration
that cleared the targets in the fit window collapsed in validation (PF ~0.5).
Brent changed regime (COVID 2020, war spike 2022, calm 2023-24), so a single
validation block mostly measures which regime the fit window happened to hold.

v2 fits on all six years 2019-2024 under hard gates on the targets and ranks
candidates by CONSISTENCY: how many of the six calendar years are profitable,
then the worst year, then the overall score.  2025-01 -> 2026-10 is never
loaded here; scripts/xbr_final.py takes the single look at it.

    python3 scripts/xbr_loop.py --round r3 --tfs 5 15 30 --variants base tight
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt, dataset, optimize as O, spaces
from scalping.strategy import StrategyParams

SYM = "XBRUSD"
EXIT_KEYS = ("s.sl_atr", "s.tp_r", "s.min_sl_bp", "e.max_bars", "e.be_trigger_r", "e.trail_start_r",
             "e.partial_r", "e.cooldown_bars", "e.max_trades_per_day")
EXIT_SPACE = {
    "s.sl_atr": [1.0, 1.5, 2.0, 3.0, 4.0],
    "s.tp_r": [0.3, 0.4, 0.5, 0.6, 0.8, 1.0],
    "s.min_sl_bp": [15, 25, 40, 60],
    "e.max_bars": [30, 60, 120, 240],
    "e.be_trigger_r": [0.0, 0.3, 0.5],
    "e.trail_start_r": [0.0, 0.8],
    "e.partial_r": [0.0, 0.25, 0.4],
}


def yearly(trades: pd.DataFrame):
    rows = []
    if not len(trades):
        return rows
    y = pd.DatetimeIndex(trades["entry_time"]).year
    for yr, g in trades.groupby(y):
        w, l = g.r[g.r > 0].sum(), -g.r[g.r <= 0].sum()
        rows.append({"year": int(yr), "n": len(g), "wr": round(float((g.r > 0).mean()), 3),
                     "pf": round(float(w / l), 3) if l > 0 else 9.99, "r": round(float(g.r.sum()), 2)})
    return rows


def mdict(m):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.to_dict().items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--tfs", nargs="+", type=int, default=[5, 15, 30])
    ap.add_argument("--modes", nargs="+", default=spaces.OIL_MODES)
    ap.add_argument("--variants", nargs="+", default=["base", "tight"])
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--gate-wr", type=float, default=0.57)
    ap.add_argument("--gate-pf", type=float, default=1.02)
    ap.add_argument("--gate-dd", type=float, default=20.0)
    ap.add_argument("--trades-per-year", type=int, default=40)
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--two-stage", action="store_true",
                    help="stage A: best raw-edge entries (no gates); stage B: exits searched under the gates")
    ap.add_argument("--entries", type=int, default=8)
    ap.add_argument("--soft", action="store_true",
                    help="no hard gates: target-penalised score + hill-climbing from the best seeds")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--exit-iters", type=int, default=200)
    args = ap.parse_args()

    ds = dataset.load(SYM, start="2019-01-02", end="2025-01-01")    # holdout never loaded
    prep = bt.prepare(ds.bars, SYM)
    years = 6.0
    out_path = ROOT / "reports" / f"xbr_loop_{args.round}.json"
    out = {"round": args.round, "fit": ["2019-01-02", "2025-01-01"],
           "gates": {"wr": args.gate_wr, "pf": args.gate_pf, "dd": args.gate_dd,
                     "trades_per_year": args.trades_per_year}, "cells": []}
    t0 = time.time()
    for variant in args.variants:
        for tf in args.tfs:
            for mode in args.modes:
                base_s = StrategyParams(mode=mode, tf_minutes=tf)
                base_e = bt.exec_config_from(prep.inst, risk_pct=0.005, be_offset_r=0.10)
                space = spaces.space_for(mode, SYM, tf, variant)
                tg = O.Targets(min_trades=args.trades_per_year, min_pf=1.01, min_wr=0.57,
                               max_avg_hold_bars=240, trade_scale=years,
                               hard_min_wr=args.gate_wr, hard_min_pf=args.gate_pf,
                               hard_max_dd=args.gate_dd)
                if args.two_stage:
                    # A: entries with the best raw edge, exits left free, no gates
                    ta = O.Targets(min_trades=args.trades_per_year, min_pf=0.0, min_wr=0.0,
                                   max_avg_hold_bars=240, trade_scale=years)
                    ca = O.parallel_search(prep, space, base_s, base_e, ta, n_iter=args.iters,
                                           seed=hash((args.round, "A", variant, tf, mode)) % 10_000,
                                           workers=args.workers)
                    entries, sigs = [], set()
                    for c in ca:
                        if not np.isfinite(c.score) or c.metrics.expectancy_r < -0.03:
                            continue
                        sig = bt.direction_key(O.build(c.values, base_s, base_e)[0])
                        if sig in sigs:
                            continue
                        sigs.add(sig)
                        entries.append(c.values)
                        if len(entries) >= args.entries:
                            break
                    # B: for each entry, search the exits under the hard gates
                    cands = []
                    exit_keys = [k for k in space if k in EXIT_KEYS]
                    for j, ev in enumerate(entries):
                        sub = {k: ([ev[k]] if (k in ev and k not in EXIT_KEYS) else v)
                               for k, v in space.items()}
                        for k in EXIT_KEYS:
                            if k in EXIT_SPACE:
                                sub[k] = EXIT_SPACE[k]
                        cands += O.parallel_search(prep, sub, base_s, base_e, tg, n_iter=args.exit_iters,
                                                   seed=j + 1, workers=args.workers)
                    cands.sort(key=lambda c: c.score if np.isfinite(c.score) else -1e18, reverse=True)
                else:
                    cands = O.parallel_search(prep, space, base_s, base_e, tg, n_iter=args.iters,
                                              seed=hash((args.round, variant, tf, mode)) % 10_000,
                                              workers=args.workers)
                if args.soft:
                    tg = replace(tg, hard_min_wr=0.0, hard_min_pf=0.0, hard_max_dd=0.0)
                    cands = O.parallel_search(prep, space, base_s, base_e, tg, n_iter=args.iters,
                                              seed=hash((args.round, variant, tf, mode)) % 10_000,
                                              workers=args.workers)
                    seeds, sigs = [], set()
                    for c in cands:
                        if not np.isfinite(c.score):
                            continue
                        sig = bt.direction_key(O.build(c.values, base_s, base_e)[0])
                        if sig not in sigs:
                            sigs.add(sig)
                            seeds.append(c.values)
                        if len(seeds) >= args.seeds:
                            break
                    for sv in seeds:
                        cands += O.refine(prep, sv, space, base_s, base_e, tg, rounds=2)
                    cands.sort(key=lambda c: c.score if np.isfinite(c.score) else -1e18, reverse=True)
                viable = [c for c in cands if np.isfinite(c.score)]
                if viable and not args.soft:
                    hist = O.refine(prep, viable[0].values, space, base_s, base_e, tg, rounds=1)
                    viable = sorted([c for c in hist + viable if np.isfinite(c.score)],
                                    key=lambda c: c.score, reverse=True)
                seen, ranked = set(), []
                for c in viable[:25]:
                    key = tuple(sorted(c.values.items()))
                    if key in seen:
                        continue
                    seen.add(key)
                    s_p, e_p = O.build(c.values, base_s, base_e)
                    _, tr, _ = bt.run(prep, s_p, e_p)
                    yr = yearly(tr)
                    n_pos = sum(1 for y in yr if y["r"] > 0)
                    worst = min((y["r"] for y in yr), default=-99.0)
                    fm = c.metrics
                    meets = bool(fm.n_trades >= 6 * args.trades_per_year and fm.win_rate >= 0.57
                                 and fm.profit_factor >= 1.01)
                    ranked.append({"values": c.values, "score": c.score, "fit": mdict(c.metrics),
                                   "years": yr, "years_positive": n_pos, "worst_year_r": worst,
                                   "meets_targets_fit": meets})
                ranked.sort(key=lambda r: (r["meets_targets_fit"], r["years_positive"], r["worst_year_r"],
                                           r["score"]), reverse=True)
                cell = {"variant": variant, "tf": tf, "mode": mode, "n_viable": len(viable),
                        "best_raw_exp": max((c.metrics.expectancy_r for c in cands
                                             if c.metrics.n_trades > 50), default=None),
                        "top": ranked[: args.keep]}
                out["cells"].append(cell)
                if ranked:
                    b = ranked[0]
                    f = b["fit"]
                    print(f"  {variant:6s} M{tf:<2d} {mode:9s} viable {len(viable):3d} | FIT19-24 "
                          f"{f['n_trades']:4d}tr WR {f['win_rate']*100:4.1f}% PF {f['profit_factor']:.2f} "
                          f"DD {f['max_dd_pct']:4.1f}% {f['expectancy_r']:+.3f}R | years+ "
                          f"{b['years_positive']}/{len(b['years'])} worst {b['worst_year_r']:+.1f}R "
                          f"[{time.time()-t0:.0f}s]", flush=True)
                else:
                    print(f"  {variant:6s} M{tf:<2d} {mode:9s} no viable config "
                          f"(best raw exp {cell['best_raw_exp']}) [{time.time()-t0:.0f}s]", flush=True)
                out_path.write_text(json.dumps(out, indent=1, default=str))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
