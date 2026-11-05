#!/usr/bin/env python3
"""XBRUSD: pick the top-3 strategies and take ONE look at the untouched holdout.

Inputs are explore_metals.py reports (fit 2019-2022, validation 2023-2024).

1. Every robust candidate (top rows of every timeframe x family cell, every
   round) whose VALIDATION result meets the targets is eligible.
2. Ranked by validation evidence (expectancy x sqrt(trades)); at most one per
   family, so the top 3 are genuinely different strategies.
3. Each is refined by coordinate descent on 2019-2024 (fit + validation) under
   the same hard gates, then traded ONCE on 2025-01 -> 2026-10.

    python3 scripts/xbr_select.py reports/xbr_explore_r1.json reports/xbr_explore_r2.json
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt, dataset, optimize as O, spaces
from scalping.strategy import StrategyParams

SYM = "XBRUSD"
TGT = {"wr": 0.57, "pf": 1.01, "dd": 20.0, "trades": 100}
FIT_END, HOLD_START, END = "2025-01-01", "2025-01-01", "2026-10-31"


def ok(m: dict) -> bool:
    return (m["n_trades"] >= TGT["trades"] and m["win_rate"] >= TGT["wr"]
            and m["profit_factor"] >= TGT["pf"] and m["max_dd_pct"] <= TGT["dd"])


def main() -> int:
    reports = sys.argv[1:]
    cands = []
    for rp in reports:
        d = json.loads(Path(rp).read_text())[SYM]
        variant = "tight" if "r2" in rp or "tight" in rp else "base"
        for key, cell in d.items():
            tf, mode = int(key.split("_")[0][1:]), key.split("_", 1)[1]
            for rank, row in enumerate(cell["rows"]):
                v = row["val"]
                cands.append({"report": rp, "variant": variant, "tf": tf, "mode": mode, "rank": rank,
                              "values": row["values"], "fit": row["fit"], "val": v,
                              "passes_val": ok(v),
                              "evidence": v["expectancy_r"] * np.sqrt(max(v["n_trades"], 1))})
    passing = sorted([c for c in cands if c["passes_val"]], key=lambda c: c["evidence"], reverse=True)
    print(f"{len(cands)} candidates, {len(passing)} pass the validation targets")
    top, seen = [], set()
    for c in passing:
        if c["mode"] in seen:
            continue
        top.append(c)
        seen.add(c["mode"])
        if len(top) == 3:
            break
    if len(top) < 3:                              # fill with the best remaining by evidence
        rest = sorted([c for c in cands if c not in top and c["val"]["n_trades"] >= 60],
                      key=lambda c: (c["passes_val"], c["evidence"]), reverse=True)
        for c in rest:
            if c["mode"] not in seen:
                top.append(c)
                seen.add(c["mode"])
            if len(top) == 3:
                break

    ds = dataset.load(SYM, start="2019-01-02", end=END)
    prep = bt.prepare(ds.bars, SYM)
    fitp, hold = prep.slice(None, FIT_END), prep.slice(HOLD_START, None)
    out = {"targets": TGT, "n_candidates": len(cands), "n_pass_validation": len(passing), "top": []}
    for i, c in enumerate(top, 1):
        base_s = StrategyParams(mode=c["mode"], tf_minutes=c["tf"])
        base_e = bt.exec_config_from(prep.inst, risk_pct=0.005, be_offset_r=0.10)
        space = spaces.space_for(c["mode"], SYM, c["tf"], c["variant"])
        tt = O.Targets(min_trades=60, min_pf=TGT["pf"], min_wr=TGT["wr"], max_avg_hold_bars=240,
                       trade_scale=6.0, hard_min_wr=TGT["wr"], hard_min_pf=1.05, hard_max_dd=TGT["dd"])
        hist = O.refine(fitp, c["values"], space, base_s, base_e, tt, rounds=2)
        best = hist[0] if np.isfinite(hist[0].score) else None
        values = best.values if best else c["values"]
        s_p, e_p = O.build(values, base_s, base_e)
        m_fit, _, _ = bt.run(fitp, s_p, e_p)
        m_h, tr_h, _ = bt.run(hold, s_p, e_p)
        # cost sensitivity on the holdout
        curve = []
        for k in (0.0, 0.5, 1.0, 1.5, 2.0):
            e2 = replace(e_p, slippage_points_entry=prep.inst.slippage_points_entry * k,
                         slippage_points_stop=prep.inst.slippage_points_stop * k)
            p2 = bt.Prepared(symbol=SYM, inst=prep.inst, exec_bars=hold.exec_bars,
                             spread_points=hold.spread_points * k, sig_cache=hold.sig_cache,
                             dir_cache=hold.dir_cache, cost_scale=hold.cost_scale)
            mk, _, _ = bt.run(p2, s_p, e2)
            curve.append({"cost_multiple": k, "trades": mk.n_trades, "wr": round(mk.win_rate, 4),
                          "pf": round(mk.profit_factor, 3), "exp_r": round(mk.expectancy_r, 4),
                          "dd": round(mk.max_dd_pct, 2)})
        # by year with the final parameters
        _, tr_all, _ = bt.run(prep, s_p, e_p)
        tr_all["year"] = pd.DatetimeIndex(tr_all["entry_time"]).year
        by_year = []
        for y, g in tr_all.groupby("year"):
            w, l = g.r[g.r > 0].sum(), -g.r[g.r <= 0].sum()
            by_year.append({"year": int(y), "trades": len(g), "wr": round((g.r > 0).mean(), 3),
                            "pf": round(w / l, 2) if l > 0 else None, "total_r": round(g.r.sum(), 2),
                            "sample": "holdout" if y >= 2025 else "fit"})
        name = f"ScalperXBR_T{i}"
        tr_h.to_csv(ROOT / "reports" / f"xbr_top{i}_holdout_trades.csv", index=False)
        tr_all.to_csv(ROOT / "reports" / f"xbr_top{i}_all_trades.csv", index=False)
        md = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m_h.to_dict().items()}
        mf = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m_fit.to_dict().items()}
        rec = {"rank": i, "ea": name, "mode": c["mode"], "tf": c["tf"], "variant": c["variant"],
               "passes_validation": c["passes_val"], "validation_2023_2024": c["val"],
               "fit_2019_2024_final": mf, "holdout_2025_2026": md, "holdout_passes": ok(md),
               "holdout_cost_curve": curve, "by_year": by_year,
               "strategy": asdict(s_p), "execution": asdict(e_p)}
        out["top"].append(rec)
        notes = [
            f"XBRUSD {c['mode'].upper()} on M{c['tf']}, session {s_p.session} (UTC) - rank {i} of the top 3",
            f"validation 2023-2024: {c['val']['n_trades']} tr  WR {c['val']['win_rate']*100:.1f}%  "
            f"PF {c['val']['profit_factor']:.2f}  DD {c['val']['max_dd_pct']:.1f}%",
            f"HOLDOUT 2025-01..2026-10 (one look): {md['n_trades']} tr  WR {md['win_rate']*100:.1f}%  "
            f"PF {md['profit_factor']:.2f}  DD {md['max_dd_pct']:.1f}%  t={md['t_stat']:.2f}",
            "targets: WR>=57%  PF>=1.01  DD<=20%  trades>=100  -> "
            + ("MET on the holdout" if ok(md) else "NOT all met on the holdout"),
            "see docs/RESULTS_XBRUSD.md",
        ]
        cfg = {"symbol": SYM, "mode": c["mode"], "strategy": asdict(s_p), "execution": asdict(e_p),
               "notes": notes}
        (ROOT / "config" / f"XBRUSD_top{i}.json").write_text(json.dumps(cfg, indent=2, default=str))
        print(f"TOP{i} {c['variant']} M{c['tf']} {c['mode']}: VAL {c['val']['n_trades']}tr "
              f"WR {c['val']['win_rate']*100:.1f}% PF {c['val']['profit_factor']:.2f} | FIT19-24 "
              f"{m_fit.n_trades}tr WR {m_fit.win_rate*100:.1f}% PF {m_fit.profit_factor:.2f} DD {m_fit.max_dd_pct:.1f}% "
              f"| HOLDOUT {m_h.n_trades}tr WR {m_h.win_rate*100:.1f}% PF {m_h.profit_factor:.2f} "
              f"DD {m_h.max_dd_pct:.1f}% t {m_h.t_stat:.2f} -> {'PASS' if ok(md) else 'fail'}", flush=True)
    (ROOT / "reports" / "xbr_top3.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
