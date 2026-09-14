#!/usr/bin/env python3
"""Stage 1: which strategy mode is worth pursuing on each symbol?

Searches every mode in-sample, then re-scores the ten best on a slice of data
the search never saw.  Modes whose in-sample winners collapse out-of-sample are
dropped before any effort goes into walk-forward.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt
from scalping import dataset, optimize as O, spaces
from scalping.strategy import StrategyParams


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["EURUSD", "XAUUSD"])
    ap.add_argument("--modes", nargs="+", default=spaces.ALL_MODES)
    ap.add_argument("--is-start", default="2019-01-02")
    ap.add_argument("--is-end", default="2023-01-01")
    ap.add_argument("--oos-end", default="2025-12-31")
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--risk", type=float, default=0.005)
    ap.add_argument("--max-hold", type=float, default=120.0)
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--out", default="reports/explore.json")
    args = ap.parse_args()

    results = {}
    for symbol in args.symbols:
        ds = dataset.load(symbol, start=args.is_start, end=args.oos_end)
        print(ds.banner(), flush=True)
        prep_all = bt.prepare(ds.bars, symbol)
        is_prep = prep_all.slice(args.is_start, args.is_end)
        oos_prep = prep_all.slice(args.is_end, args.oos_end)
        print(f"  IS bars {len(is_prep.exec_bars):,}  OOS bars {len(oos_prep.exec_bars):,}", flush=True)

        base_e = bt.exec_config_from(prep_all.inst, risk_pct=args.risk)
        # IS window is multi-year, so pro-rate the per-year trade requirement
        years = max(1.0, (pd.Timestamp(args.is_end) - pd.Timestamp(args.is_start)).days / 365.0)
        targets = O.Targets(min_trades=args.min_trades, max_avg_hold_bars=args.max_hold,
                            trade_scale=years)
        results[symbol] = {}

        for mode in args.modes:
            base_s = StrategyParams(mode=mode)
            space = spaces.space_for(mode, symbol)
            t0 = time.time()
            cands = O.parallel_search(
                is_prep, space, base_s, base_e, targets,
                n_iter=args.iters, seed=hash(symbol + mode) % 10_000,
                workers=args.workers,
            )
            viable = [c for c in cands if c.score > -1e17]
            ranked = O.robust_select(is_prep, viable, base_s, base_e, targets, top_k=25)
            good = (ranked or viable)[:10]
            rows = []
            for c in good:
                s_p, e_p = O.build(c.values, base_s, base_e)
                m_oos, tr, _ = bt.run(oos_prep, s_p, e_p)
                rows.append({
                    "values": c.values,
                    "is": c.metrics.to_dict(),
                    "oos": m_oos.to_dict(),
                })
            results[symbol][mode] = rows
            dt = time.time() - t0
            if rows:
                b = rows[0]
                print(
                    f"  {mode:9s} [{dt:5.1f}s] IS trades {b['is']['n_trades']:4d} "
                    f"exp {b['is']['expectancy_r']:+.3f}R PF {b['is']['profit_factor']:.2f} "
                    f"WR {b['is']['win_rate']*100:.1f}% hold {b['is']['avg_bars_held']:.0f}m"
                    f"  ->  OOS trades {b['oos']['n_trades']:4d} "
                    f"exp {b['oos']['expectancy_r']:+.3f}R PF {b['oos']['profit_factor']:.2f} "
                    f"WR {b['oos']['win_rate']*100:.1f}%",
                    flush=True,
                )
                best_oos = max(rows, key=lambda r: r["oos"]["expectancy_r"])
                print(
                    f"             best-of-10 by OOS: trades {best_oos['oos']['n_trades']:4d} "
                    f"exp {best_oos['oos']['expectancy_r']:+.3f}R "
                    f"PF {best_oos['oos']['profit_factor']:.2f} "
                    f"WR {best_oos['oos']['win_rate']*100:.1f}%",
                    flush=True,
                )
            else:
                print(f"  {mode:9s} [{dt:5.1f}s] no viable candidate", flush=True)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
