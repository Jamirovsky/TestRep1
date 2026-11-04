#!/usr/bin/env python3
"""Loop-optimise ONE shared parameter set for a basket EA (stocks or indices).

Three windows, never mixed:

    FIT        the search sees only this
    VALIDATION the loop's stopping rule looks at this (and only this)
    HOLDOUT    touched once, at the very end, by the final parameter set

Loop: for every timeframe x family cell, random search + coordinate refinement
on FIT, robust re-ranking (worst third of FIT, then breadth across symbols).
The cells are then tried in order of their FIT robustness; each one's
validation result is checked against the targets (trades / PF / WR).  The
first cell that passes stops the loop; if none passes, the best validation
result is kept.  Every iteration is logged to the JSON report, so the number
of validation looks is on record.

    python3 scripts/optimize_basket.py --basket stocks
    python3 scripts/optimize_basket.py --basket indices
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

from scalping import backtest as bt, basket as B, dataset, optimize as O, spaces
from scalping.instruments import INDICES5, STOCKS7
from scalping.strategy import StrategyParams

WINDOWS = {
    "stocks": ("2026-02-02", "2026-06-01", "2026-08-01", "2026-09-26"),
    "indices": ("2021-01-04", "2025-01-01", "2026-01-01", "2026-10-31"),
}


def mdict(m):
    d = m.to_dict()
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def passes(m, t):
    return m.n_trades >= t["trades"] and m.profit_factor >= t["pf"] and m.win_rate >= t["wr"]


def passes_d(d, t):
    return d["n_trades"] >= t["trades"] and d["profit_factor"] >= t["pf"] and d["win_rate"] >= t["wr"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basket", choices=["stocks", "indices"], required=True)
    ap.add_argument("--tfs", nargs="+", type=int, default=[1, 5, 15, 30])
    ap.add_argument("--modes", nargs="+", default=["momentum", "breakout", "fade", "bands"])
    ap.add_argument("--variants", nargs="+", default=["base", "selective"])
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--risk", type=float, default=0.005)
    ap.add_argument("--max-hold", type=float, default=240.0)
    ap.add_argument("--fit-trades-per-year", type=int, default=150)
    ap.add_argument("--target-trades", type=int, default=100)
    ap.add_argument("--target-pf", type=float, default=1.2)
    ap.add_argument("--target-wr", type=float, default=0.50)
    ap.add_argument("--target-trades-per-year", type=float, default=0.0,
                    help="if > 0, the trade target is this rate pro-rated to each window "
                         "(instead of --target-trades on the holdout)")
    ap.add_argument("--reuse", default=None,
                    help="skip stage 1 and take the fitted cells from this earlier report")
    ap.add_argument("--fit-min-pf", type=float, default=0.0, help="hard gate in the FIT search")
    ap.add_argument("--fit-min-wr", type=float, default=0.0, help="hard gate in the FIT search")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    syms = STOCKS7 if args.basket == "stocks" else INDICES5
    fs, fe, ve, he = WINDOWS[args.basket]
    preps = {}
    for s in syms:
        ds = dataset.load(s, start=fs, end=he)
        print(ds.banner(), flush=True)
        preps[s] = bt.prepare(ds.bars, s)
    full = B.Basket(preps)
    fit, val, hold = full.slice(fs, fe), full.slice(fe, ve), full.slice(ve, he)
    tgt = {"trades": args.target_trades, "pf": args.target_pf, "wr": args.target_wr}
    # the trade target is stated for the HOLDOUT; validation is pro-rated
    hold_days = hold.span_days()
    if args.target_trades_per_year > 0:
        tgt["trades"] = int(round(args.target_trades_per_year * hold_days / 365.0))
        val_tgt = dict(tgt, trades=int(round(args.target_trades_per_year * val.span_days() / 365.0)))
    else:
        val_tgt = dict(tgt, trades=int(round(tgt["trades"] * val.span_days() / max(hold_days, 1))))

    base_e = bt.exec_config_from(preps[syms[0]].inst, risk_pct=args.risk, be_offset_r=0.10,
                                 force_exit_hour=19, force_exit_min=55)
    years = fit.span_days() / 365.0
    targets = O.Targets(min_trades=args.fit_trades_per_year, min_pf=args.target_pf,
                        min_wr=args.target_wr, max_avg_hold_bars=args.max_hold, trade_scale=years,
                        hard_min_pf=args.fit_min_pf, hard_min_wr=args.fit_min_wr)
    out_path = Path(args.out or ROOT / "reports" / f"basket_{args.basket}.json")
    log = {"basket": args.basket, "symbols": syms, "windows": {"fit": [fs, fe], "validation": [fe, ve],
           "holdout": [ve, he]}, "targets": tgt, "validation_targets": val_tgt, "cells": [],
           "iterations": []}

    # ---- stage 1: every cell, fitted on FIT only --------------------------
    t0 = time.time()
    if args.reuse:
        log["cells"] = json.loads(Path(args.reuse).read_text())["cells"]
        log["reused_cells_from"] = args.reuse
    for variant in ([] if args.reuse else args.variants):
        for tf in args.tfs:
            for mode in args.modes:
                base_s = StrategyParams(mode=mode, tf_minutes=tf)
                space = spaces.basket_space(mode, args.basket, tf, variant)
                res = B.search(fit, space, base_s, base_e, targets, n_iter=args.iters,
                               seed=hash((variant, tf, mode)) % 10_000, workers=args.workers)
                viable = [r for r in res if np.isfinite(r[2])]
                if not viable:
                    print(f"  {variant:9s} M{tf:<2d} {mode:9s} no viable config", flush=True)
                    continue
                best = B.refine(fit, viable[0][0], space, base_s, base_e, targets, rounds=1,
                                workers=args.workers)
                ranked = B.robust_rank(fit, [best] + viable, base_s, base_e, targets, top_k=15)
                key, v, m, sc, frac, subs = ranked[0]
                cell = {"variant": variant, "tf": tf, "mode": mode, "values": v,
                        "fit": mdict(m), "fit_score": sc, "robust_worst": key[0],
                        "symbol_breadth": frac}
                log["cells"].append(cell)
                print(f"  {variant:9s} M{tf:<2d} {mode:9s} FIT {m.n_trades:5d}tr "
                      f"{m.expectancy_r:+.3f}R PF {m.profit_factor:.2f} WR {m.win_rate*100:4.1f}% "
                      f"worst-third {key[0]:+.1f} breadth {frac:.2f} [{time.time()-t0:.0f}s]", flush=True)
                out_path.write_text(json.dumps(log, indent=1, default=str))

    # ---- stage 2: the loop, cells in order of FIT robustness --------------
    order = sorted(log["cells"], key=lambda c: (c["robust_worst"], c["symbol_breadth"]), reverse=True)
    chosen, best_val = None, None
    for it, c in enumerate(order, 1):
        base_s = StrategyParams(mode=c["mode"], tf_minutes=c["tf"])
        m_val, tr_val = B.evaluate(val, c["values"], base_s, base_e)
        ok = passes(m_val, val_tgt)
        rec = {"iteration": it, "variant": c["variant"], "tf": c["tf"], "mode": c["mode"],
               "validation": mdict(m_val), "passes_validation": ok}
        log["iterations"].append(rec)
        print(f"  loop {it:2d}: {c['variant']:9s} M{c['tf']:<2d} {c['mode']:9s} VAL "
              f"{m_val.n_trades:4d}tr PF {m_val.profit_factor:.2f} WR {m_val.win_rate*100:4.1f}% "
              f"{m_val.expectancy_r:+.3f}R -> {'PASS' if ok else 'fail'}", flush=True)
        if best_val is None or m_val.expectancy_r * np.sqrt(max(m_val.n_trades, 1)) > best_val[0]:
            best_val = (m_val.expectancy_r * np.sqrt(max(m_val.n_trades, 1)), c)
        if ok:
            chosen = c
            break
    if chosen is None:
        chosen = best_val[1]
    log["chosen"] = {k: chosen[k] for k in ("variant", "tf", "mode", "values")}
    log["chosen_passed_validation"] = any(r["passes_validation"] for r in log["iterations"])

    # ---- stage 3: final parameters = chosen cell refitted on FIT+VALIDATION,
    # ---- then ONE look at the holdout ------------------------------------
    base_s = StrategyParams(mode=chosen["mode"], tf_minutes=chosen["tf"])
    space = spaces.basket_space(chosen["mode"], args.basket, chosen["tf"], chosen["variant"])
    fv = full.slice(fs, ve)
    tfv = replace(targets, trade_scale=fv.span_days() / 365.0)
    final = B.refine(fv, chosen["values"], space, base_s, base_e, tfv, rounds=2, workers=args.workers)
    final_values = final[0]
    s_f, e_f = O.build(final_values, base_s, base_e)
    rows = {}
    for name, b in (("fit", fit), ("validation", val), ("fit+validation", fv), ("holdout", hold)):
        m, tr = b.run(s_f, e_f)
        rows[name] = {"pooled": mdict(m),
                      "per_symbol": B.per_symbol(tr).round(4).to_dict("records") if len(tr) else []}
        if name == "holdout" and len(tr):
            tr.to_csv(ROOT / "reports" / f"basket_{args.basket}_holdout_trades.csv", index=False)
    # cost sensitivity on the holdout
    curve = []
    for k in (0.0, 0.5, 1.0, 1.5, 2.0):
        preps_k = {}
        for sname, p in hold.preps.items():
            preps_k[sname] = bt.Prepared(symbol=p.symbol, inst=p.inst, exec_bars=p.exec_bars,
                                         spread_points=p.spread_points * k, sig_cache=p.sig_cache,
                                         dir_cache=p.dir_cache, cost_scale=p.cost_scale * k
                                         if p.cost_scale is not None else None)
        bk = B.Basket(preps_k)
        e_k = replace(e_f)
        # commission is per instrument; scale it through the instruments' exec costs
        frames = []
        for sname, p in bk.preps.items():
            ek = replace(e_k, **{**B.exec_costs(p.inst),
                                  "commission_per_lot_rt": p.inst.commission_per_lot_rt * k})
            _, tr, _ = bt.run(p, s_f, ek)
            if len(tr):
                frames.append(tr)
        trs = pd.concat(frames).sort_values("entry_time") if frames else pd.DataFrame()
        mk = O._stitch_metrics(trs, e_f.initial_equity, e_f.risk_pct) if len(trs) else None
        curve.append({"cost_multiple": k, **({"trades": mk.n_trades, "pf": round(mk.profit_factor, 3),
                      "wr": round(mk.win_rate, 4), "exp_r": round(mk.expectancy_r, 4)} if mk else {})})
    log["final"] = {"values": final_values, "strategy": asdict(s_f), "execution": asdict(e_f),
                    "results": rows, "holdout_cost_curve": curve,
                    "holdout_passes_targets": passes_d(rows["holdout"]["pooled"], tgt)}
    out_path.write_text(json.dumps(log, indent=1, default=str))
    for name, r in rows.items():
        p = r["pooled"]
        print(f"FINAL {name:15s} {p['n_trades']:5d}tr WR {p['win_rate']*100:4.1f}% PF {p['profit_factor']:.2f} "
              f"{p['expectancy_r']:+.3f}R t {p['t_stat']:.2f} DD {p['max_dd_pct']:.1f}%", flush=True)
    print("holdout cost curve:", curve)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
