#!/usr/bin/env python3
"""Stage 1 for the metals: pick the signal timeframe (M1..M30) and strategy family.

For every symbol x timeframe x family:

1. random search on the FIT window (default 2019-2022),
2. re-rank the best 25 by their WORST third of that window (robust_select),
3. score the robust winner on the untouched VALIDATION window (2023-2024).

The timeframe/family per symbol is chosen on the validation window; 2025-2026
is not touched here at all and stays available as a final frozen holdout for
scripts/run_optimize.py.

    python3 scripts/explore_metals.py --symbols XAGUSD XPTUSD XPDUSD --iters 400
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt
from scalping import dataset, optimize as O, spaces
from scalping.strategy import StrategyParams


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["XAGUSD", "XPTUSD", "XPDUSD", "XAUUSD"])
    ap.add_argument("--modes", nargs="+", default=["fade", "bands", "momentum", "breakout"])
    ap.add_argument("--tfs", nargs="+", type=int, default=[1, 5, 15, 30])
    ap.add_argument("--fit-start", default="2019-01-02")
    ap.add_argument("--fit-end", default="2023-01-01")
    ap.add_argument("--val-end", default="2025-01-01")
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-hold", type=float, default=240.0)
    ap.add_argument("--trades-per-year", type=int, default=60)
    ap.add_argument("--variant", default="base", choices=["base", "selective"])
    ap.add_argument("--out", default="reports/metals_explore.json")
    args = ap.parse_args()

    out_path = ROOT / args.out
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    for symbol in args.symbols:
        ds = dataset.load(symbol, start=args.fit_start, end=args.val_end)
        print(ds.banner(), flush=True)
        prep_all = bt.prepare(ds.bars, symbol)
        fit = prep_all.slice(args.fit_start, args.fit_end)
        val = prep_all.slice(args.fit_end, args.val_end)
        base_e = bt.exec_config_from(prep_all.inst, risk_pct=0.005, be_offset_r=0.10)
        years = (pd.Timestamp(args.fit_end) - pd.Timestamp(args.fit_start)).days / 365.0
        targets = O.Targets(min_trades=args.trades_per_year, max_avg_hold_bars=args.max_hold,
                            trade_scale=years)
        results.setdefault(symbol, {})
        for tf in args.tfs:
            for mode in args.modes:
                key = f"M{tf}_{mode}"
                t0 = time.time()
                base_s = StrategyParams(mode=mode, tf_minutes=tf)
                space = spaces.space_for(mode, symbol, tf, args.variant)
                cands = O.parallel_search(fit, space, base_s, base_e, targets, n_iter=args.iters,
                                          seed=hash(key) % 10_000, workers=args.workers)
                viable = [c for c in cands if np.isfinite(c.score)]
                ranked = O.robust_select(fit, viable, base_s, base_e, targets, top_k=25)
                rows = []
                for c in (ranked or viable)[:5]:
                    s_p, e_p = O.build(c.values, base_s, base_e)
                    m_val, _, _ = bt.run(val, s_p, e_p)
                    rows.append({"values": c.values, "robust_worst": c.robust_worst,
                                 "fit": c.metrics.to_dict(), "val": m_val.to_dict()})
                results[symbol][key] = {
                    "n_viable": len(viable),
                    "best_fit_score": viable[0].score if viable else None,
                    "rows": rows,
                }
                dt = time.time() - t0
                if rows:
                    b = rows[0]
                    f, v = b["fit"], b["val"]
                    print(f"  {key:14s} [{dt:5.0f}s] viable {len(viable):3d} | FIT {f['n_trades']:4d}tr "
                          f"{f['expectancy_r']:+.3f}R PF {f['profit_factor']:.2f} WR {f['win_rate']*100:4.1f}% "
                          f"hold {f['avg_bars_held']:.0f}m | VAL {v['n_trades']:4d}tr "
                          f"{v['expectancy_r']:+.3f}R PF {v['profit_factor']:.2f} WR {v['win_rate']*100:4.1f}%",
                          flush=True)
                else:
                    best = max((c.metrics.expectancy_r for c in cands if c.metrics.n_trades > 30), default=float('nan'))
                    print(f"  {key:14s} [{dt:5.0f}s] no viable candidate (best raw exp {best:+.3f}R)", flush=True)
                out_path.write_text(json.dumps(results, indent=1, default=str))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
