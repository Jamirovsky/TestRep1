#!/usr/bin/env python3
"""Stage 2: walk-forward optimisation, and the only performance claim we make.

Fits parameters on a rolling training window, measures them on the untouched
window that follows, and stitches every out-of-sample segment into one equity
curve.  The target check (trades / profit factor / win rate) is evaluated on
that stitched curve, never on the fitted windows.

    python3 scripts/run_optimize.py --symbol EURUSD --mode breakout
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt
from scalping import dataset, metrics as M, optimize as O, report as R, spaces
from scalping.strategy import StrategyParams


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--mode", required=True, choices=spaces.ALL_MODES)
    ap.add_argument("--start", default="2019-01-02")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--folds", type=int, default=0, help="cap on folds; 0 = every window that fits")
    ap.add_argument("--train-days", type=int, default=730,
                    help="a 365d window yields too few trades to fit 15 parameters on")
    ap.add_argument("--test-days", type=int, default=120)
    ap.add_argument("--step-days", type=int, default=None, help="window advance; default = test-days (contiguous)")
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--risk", type=float, default=0.005)
    ap.add_argument("--max-hold", type=float, default=120.0)
    ap.add_argument("--min-trades", type=int, default=100,
                    help="target check, applied to the stitched out-of-sample result")
    ap.add_argument("--fit-min-pf", type=float, default=1.22,
                    help="HARD in-sample profit-factor gate; above --min-pf to leave "
                         "room for out-of-sample decay")
    ap.add_argument("--fit-min-wr", type=float, default=0.52,
                    help="HARD in-sample win-rate gate; above --min-wr for the same reason")
    ap.add_argument("--fit-trades-per-year", type=int, default=200,
                    help="trade floor the SEARCH must clear, per year of training window; "
                         "higher means each fitted config rests on more observations")
    ap.add_argument("--min-pf", type=float, default=1.2)
    ap.add_argument("--min-wr", type=float, default=0.50)
    ap.add_argument("--holdout-fit-days", type=int, default=730,
                    help="fit ONCE on this many days, then trade everything after it "
                         "with those parameters frozen; 0 to skip")
    ap.add_argument("--label", default="", help="suffix for report/config filenames")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    symbol, mode = args.symbol.upper(), args.mode
    ds = dataset.load(symbol, start=args.start, end=args.end)
    print(ds.banner(), flush=True)

    prep = bt.prepare(ds.bars, symbol)
    base_s = StrategyParams(mode=mode)
    # a small positive breakeven offset means a partial-then-breakeven exit
    # books as a win rather than a scratch, which is what lifts the win rate
    base_e = bt.exec_config_from(prep.inst, risk_pct=args.risk, be_offset_r=0.10)
    space = spaces.space_for(mode, symbol)
    # The search is held to a higher trade floor than the final target check:
    # a configuration fitted on 150 trades is fitted on noise, whatever its
    # in-sample expectancy looks like.
    targets = O.Targets(
        min_trades=args.fit_trades_per_year, min_pf=args.min_pf, min_wr=args.min_wr,
        max_avg_hold_bars=args.max_hold,
        hard_min_pf=args.fit_min_pf, hard_min_wr=args.fit_min_wr,
    )

    n_windows = len(O.make_folds(prep.exec_bars.index, args.folds,
                                 args.train_days, args.test_days, args.step_days))
    print(f"\nwalk-forward: {n_windows} folds, train {args.train_days}d / "
          f"test {args.test_days}d, {args.iters} configs per fold, "
          f"search trade floor {args.fit_trades_per_year}/yr, "
          f"hard gates PF>={args.fit_min_pf} WR>={args.fit_min_wr*100:.0f}%", flush=True)
    t0 = time.time()
    wf = O.walk_forward(
        prep, space, base_s, base_e, targets,
        n_folds=args.folds, train_days=args.train_days, test_days=args.test_days,
        step_days=args.step_days,
        n_iter=args.iters, seed=args.seed, workers=args.workers, verbose=True,
    )
    print(f"\n{wf.summary()}\n[{time.time() - t0:.0f}s]", flush=True)

    if not wf.folds:
        print("no usable folds - widen the date range or relax the targets")
        print(f"  hard gates were PF>={args.fit_min_pf} WR>={args.fit_min_wr*100:.0f}% "
              f"with {args.fit_trades_per_year} trades/yr; nothing cleared them")
        return 1

    # ---- fit-once holdout: the strictest test available ----------------
    # Walk-forward re-selects parameters every fold, which is realistic but
    # still makes 15 selection decisions on the data.  This fits ONE parameter
    # set on the first window and then leaves it alone for years.
    hold_m, hold_tr = None, pd.DataFrame()
    if args.holdout_fit_days:
        fit_end = prep.exec_bars.index[0].normalize() + pd.Timedelta(days=args.holdout_fit_days)
        fit_prep = prep.slice(None, str(fit_end.date()))
        hold_prep = prep.slice(str(fit_end.date()), None)
        if len(fit_prep.exec_bars) > 5000 and len(hold_prep.exec_bars) > 5000:
            ht = replace(targets, trade_scale=args.holdout_fit_days / 365.0)
            hc = O.parallel_search(fit_prep, space, base_s, base_e, ht,
                                   n_iter=args.iters, seed=args.seed + 99,
                                   workers=args.workers)
            hv = [c for c in hc if np.isfinite(c.score)]
            if hv:
                hr = O.robust_select(fit_prep, hv, base_s, base_e, ht, top_k=25)
                s_h, e_h = O.build((hr or hv)[0].values, base_s, base_e)
                hold_m, hold_tr, _ = bt.run(hold_prep, s_h, e_h)
                print(f"\nfit-once holdout: fitted on "
                      f"{fit_prep.exec_bars.index[0]:%Y-%m-%d}..{fit_end:%Y-%m-%d}, "
                      f"traded {hold_prep.exec_bars.index[0]:%Y-%m-%d}.."
                      f"{hold_prep.exec_bars.index[-1]:%Y-%m-%d} with parameters frozen")
                print("  ", hold_m.summary(), flush=True)

    # Parameters to actually deploy: the most recent fold's, since they were
    # fitted on the regime closest to now.
    deploy = wf.folds[-1].best_values
    s_dep, e_dep = O.build(deploy, base_s, base_e)

    # Stability of the deployed set, measured on its own training window.
    last = wf.folds[-1]
    train_prep = prep.slice(str(last.train_start.date()), str(last.train_end.date()))
    stab = O.stability(train_prep, deploy, space, base_s, base_e, targets)

    full_m, full_tr, _ = bt.run(prep, s_dep, e_dep)
    oos = wf.oos_metrics
    pval = M.bootstrap_pvalue(wf.oos_trades["r"].to_numpy()) if len(wf.oos_trades) else 1.0

    # ---- artefacts ----------------------------------------------------
    outdir = ROOT / "reports"
    outdir.mkdir(exist_ok=True)
    tag = f"{symbol}_{mode}" + (f"_{args.label}" if args.label else "")

    R.equity_plot(
        wf.oos_trades, outdir / f"{tag}_oos_equity.png",
        f"{symbol} {mode} - stitched out-of-sample equity "
        f"({'SYNTHETIC' if ds.is_synthetic else 'real'} data)",
    )
    if hold_m is not None and len(hold_tr):
        R.equity_plot(
            hold_tr, outdir / f"{tag}_holdout_equity.png",
            f"{symbol} {mode} - fit-once holdout (parameters frozen after the fit window)",
        )
    R.fold_plot(wf.folds, outdir / f"{tag}_folds.png",
                f"{symbol} {mode} - in-sample vs out-of-sample expectancy per fold")
    if len(wf.oos_trades):
        wf.oos_trades.to_csv(outdir / f"{tag}_oos_trades.csv", index=False)

    cfgdir = ROOT / "config"
    cfgdir.mkdir(exist_ok=True)
    (cfgdir / f"{tag}.json").write_text(json.dumps({
        "symbol": symbol,
        "mode": mode,
        "data": {"synthetic": ds.is_synthetic, "source": ds.source,
                 "start": str(ds.bars.index[0]), "end": str(ds.bars.index[-1])},
        "strategy": asdict(s_dep),
        "execution": asdict(e_dep),
        "validation": {
            "oos": oos.to_dict(),
            "holdout": hold_m.to_dict() if hold_m is not None else None,
            "full_sample": full_m.to_dict(),
            "walk_forward_efficiency": wf.efficiency,
            "bootstrap_p_value": pval,
            "stability": stab,
            "folds": [
                {"train": [str(f.train_start), str(f.train_end)],
                 "test": [str(f.test_start), str(f.test_end)],
                 "is": f.train_metrics.to_dict(),
                 "oos": f.test_metrics.to_dict()}
                for f in wf.folds
            ],
        },
    }, indent=2, default=str))

    md = [
        f"# {symbol} - {mode} - walk-forward result",
        "",
        f"- data: **{'SYNTHETIC (engine validation only)' if ds.is_synthetic else 'real'}** - {ds.source}",
        f"- span: {ds.bars.index[0]:%Y-%m-%d} to {ds.bars.index[-1]:%Y-%m-%d}",
        f"- folds: {len(wf.folds)} x (train {args.train_days}d / test {args.test_days}d), "
        f"contiguous out-of-sample coverage {len(wf.folds) * args.test_days} days",
        f"- configurations evaluated: {args.iters * len(wf.folds):,}",
        "",
        "## Targets, measured on out-of-sample data only",
        "",
        R.targets_table(oos, args.min_trades, args.min_pf, args.min_wr),
        "",
        "## Metrics",
        "",
        R.metrics_table(
            {"Walk-forward OOS": oos,
             **({"Fit-once holdout": hold_m} if hold_m is not None else {}),
             "Full sample (deployed params)": full_m}
        ),
        "",
        f"- walk-forward efficiency (OOS / IS expectancy): **{wf.efficiency:.2f}**",
        f"- bootstrap p-value for mean R > 0 (OOS): **{pval:.4f}**",
        f"- neighbourhood stability: {stab['n']} neighbours, "
        f"median score {stab['median']:.2f}, {stab['frac_positive']*100:.0f}% positive",
        "",
        "## Per-fold",
        "",
        "```",
        wf.summary(),
        "```",
        "",
        "## Deployed parameters",
        "",
        R.params_block(s_dep, e_dep),
        "",
        "## Out-of-sample breakdown",
        "",
        R.breakdown_tables(wf.oos_trades) if len(wf.oos_trades) else "_no trades_",
        "",
        f"![oos equity]({tag}_oos_equity.png)",
        "",
        f"![folds]({tag}_folds.png)",
        "",
        *((f"![fit-once holdout]({tag}_holdout_equity.png)",)
          if hold_m is not None and len(hold_tr) else ()),
    ]
    (outdir / f"{tag}_walkforward.md").write_text("\n".join(md))

    print("\n--- OUT-OF-SAMPLE (the number that counts) ---")
    print(oos.summary())
    print(f"targets: trades>={args.min_trades} PF>={args.min_pf} WR>={args.min_wr*100:.0f}%  -> "
          f"{'PASS' if oos.passes(args.min_trades, args.min_pf, args.min_wr) else 'FAIL'}")
    if hold_m is not None:
        print("fit-once holdout:", hold_m.summary(),
              "->", "PASS" if hold_m.passes(args.min_trades, args.min_pf, args.min_wr) else "FAIL")
    print(f"\nwrote reports/{tag}_walkforward.md and config/{tag}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
