#!/usr/bin/env python3
"""Loop stage 3 for a basket: rolling walk-forward of the best candidate cells.

A single validation window and a single holdout are thin evidence (two months
each for the stocks).  This re-fits each candidate cell on a rolling window,
trades the next window with the refitted parameters, and stitches every
out-of-sample piece together -- so every month after the first training
window is used out-of-sample once.

    python3 scripts/basket_walkforward.py --report reports/basket_stocks_loop2.json \
        --train-days 90 --test-days 30 --top 8
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt, basket as B, dataset, optimize as O, spaces
from scalping.strategy import StrategyParams


def mdict(m):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.to_dict().items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--train-days", type=int, required=True)
    ap.add_argument("--test-days", type=int, required=True)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--warmup-days", type=int, default=30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--trades-per-year", type=float, default=100.0)
    ap.add_argument("--target-pf", type=float, default=1.2)
    ap.add_argument("--target-wr", type=float, default=0.50)
    ap.add_argument("--fit-trades-per-year", type=int, default=150)
    ap.add_argument("--max-hold", type=float, default=240.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rep = json.loads(Path(args.report).read_text())
    basket, syms = rep["basket"], rep["symbols"]
    start, end = rep["windows"]["fit"][0], rep["windows"]["holdout"][1]
    preps = {s: bt.prepare(dataset.load(s, start=start, end=end).bars, s) for s in syms}
    full = B.Basket(preps)
    base_e = bt.exec_config_from(preps[syms[0]].inst, risk_pct=0.005, be_offset_r=0.10,
                                 force_exit_hour=19, force_exit_min=55)

    # candidate cells: best validation evidence first (expectancy x sqrt(n))
    val = {(r["variant"], r["tf"], r["mode"]): r["validation"] for r in rep["iterations"]}
    cells = []
    for c in rep["cells"]:
        v = val.get((c["variant"], c["tf"], c["mode"]))
        if v is None:
            continue
        cells.append((v["expectancy_r"] * np.sqrt(max(v["n_trades"], 1)), c))
    cells = [c for _, c in sorted(cells, key=lambda x: x[0], reverse=True)[: args.top]]

    idx0 = min(p.exec_bars.index[0] for p in preps.values()).normalize()
    idx1 = max(p.exec_bars.index[-1] for p in preps.values()).normalize()
    folds, k = [], 0
    while True:
        ts = idx0 + pd.Timedelta(days=k * args.test_days)
        te = ts + pd.Timedelta(days=args.train_days)
        ve = te + pd.Timedelta(days=args.test_days)
        if te >= idx1:
            break
        folds.append((ts, te, min(ve, idx1 + pd.Timedelta(days=1))))
        k += 1
        if ve > idx1:
            break
    print(f"{basket}: {len(folds)} folds, train {args.train_days}d / test {args.test_days}d, "
          f"{len(cells)} candidate cells", flush=True)

    out = {"basket": basket, "symbols": syms, "folds": [[str(a.date()), str(b.date()), str(c.date())]
           for a, b, c in folds], "candidates": []}
    t0 = time.time()
    for c in cells:
        base_s = StrategyParams(mode=c["mode"], tf_minutes=c["tf"])
        space = spaces.basket_space(c["mode"], basket, c["tf"], c["variant"])
        frames, fold_rows, last_values = [], [], c["values"]
        for ts, te, ve in folds:
            train = full.slice(str(ts.date()), str(te.date()))
            # warm-up: indicators (ATR rank needs 288 signal bars) run from
            # well before the test window; only entries inside it count
            warm = te - pd.Timedelta(days=args.warmup_days)
            test = full.slice(str(warm.date()), str(ve.date()))
            tt = O.Targets(min_trades=args.fit_trades_per_year, min_pf=args.target_pf,
                           min_wr=args.target_wr, max_avg_hold_bars=args.max_hold,
                           trade_scale=args.train_days / 365.0)
            best = B.refine(train, last_values, space, base_s, base_e, tt, rounds=1,
                            workers=args.workers)
            last_values = best[0]
            _, tr_te = B.evaluate(test, last_values, base_s, base_e)
            if len(tr_te):
                tr_te = tr_te[pd.DatetimeIndex(tr_te["entry_time"]) >= te].reset_index(drop=True)
            m_te = (O._stitch_metrics(tr_te, base_e.initial_equity, base_e.risk_pct)
                    if len(tr_te) else O.Metrics())
            fold_rows.append({"train": [str(ts.date()), str(te.date())], "test_end": str(ve.date()),
                              "is": mdict(best[1]), "oos": mdict(m_te), "values": last_values})
            if len(tr_te):
                frames.append(tr_te)
        trades = pd.concat(frames).sort_values("entry_time") if frames else pd.DataFrame()
        m = O._stitch_metrics(trades, base_e.initial_equity, base_e.risk_pct) if len(trades) else None
        oos_days = (folds[-1][2] - folds[0][1]).days
        need = int(round(args.trades_per_year * oos_days / 365.0))
        ok = bool(m and m.n_trades >= need and m.profit_factor >= args.target_pf
                  and m.win_rate >= args.target_wr)
        s_dep, e_dep = O.build(last_values, base_s, base_e)
        rec = {"variant": c["variant"], "tf": c["tf"], "mode": c["mode"],
               "oos": mdict(m) if m else None, "oos_days": oos_days, "trades_needed": need,
               "passes": ok, "folds": fold_rows,
               "per_symbol": B.per_symbol(trades).round(4).to_dict("records") if len(trades) else [],
               "deploy": {"values": last_values, "strategy": asdict(s_dep), "execution": asdict(e_dep)}}
        out["candidates"].append(rec)
        if m:
            print(f"  {c['variant']:9s} M{c['tf']:<2d} {c['mode']:9s} OOS {m.n_trades:4d}tr "
                  f"WR {m.win_rate*100:4.1f}% PF {m.profit_factor:.2f} {m.expectancy_r:+.3f}R "
                  f"t {m.t_stat:.2f} (need {need}tr) -> {'PASS' if ok else 'fail'} [{time.time()-t0:.0f}s]",
                  flush=True)
        if len(trades):
            trades.to_csv(ROOT / "reports" / f"basket_{basket}_wf_{c['variant']}_M{c['tf']}_{c['mode']}.csv",
                          index=False)
    passing = [r for r in out["candidates"] if r["passes"]]
    pool = passing or [r for r in out["candidates"] if r["oos"]]
    best = max(pool, key=lambda r: r["oos"]["t_stat"])
    out["chosen"] = {k: best[k] for k in ("variant", "tf", "mode", "passes")}
    out["final"] = {"strategy": best["deploy"]["strategy"], "execution": best["deploy"]["execution"],
                    "values": best["deploy"]["values"], "walk_forward_oos": best["oos"],
                    "per_symbol": best["per_symbol"]}
    path = Path(args.out or ROOT / "reports" / f"basket_{basket}_wf.json")
    path.write_text(json.dumps(out, indent=1, default=str))
    print(f"chosen: {out['chosen']}  -> wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
