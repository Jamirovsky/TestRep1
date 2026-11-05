#!/usr/bin/env python3
"""XBRUSD top 3: choose on 2019-2024 only, then ONE look at 2025-01 -> 2026-10.

Selection never sees the holdout: candidates from the xbr_loop rounds are
ranked by year-by-year consistency on 2019-2024 (years positive, worst year,
score), one per family so the three are genuinely different strategies.
Then each is traded once on the untouched holdout, with a cost-sensitivity
curve, and turned into an MT5 EA + .set.

    python3 scripts/xbr_final.py reports/xbr_loop_r3.json [reports/xbr_loop_r4.json ...]
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt, dataset, optimize as O
from scalping.strategy import StrategyParams

SYM = "XBRUSD"
TGT = {"wr": 0.57, "pf": 1.01, "dd": 20.0, "trades": 100}


def ok(m) -> bool:
    return (m["n_trades"] >= TGT["trades"] and m["win_rate"] >= TGT["wr"]
            and m["profit_factor"] >= TGT["pf"] and m["max_dd_pct"] <= TGT["dd"])


def mdict(m):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.to_dict().items()}


def main() -> int:
    exclude = set()
    args = []
    for a in sys.argv[1:]:
        if a.startswith("--exclude="):
            exclude |= set(a.split("=", 1)[1].split(","))
        else:
            args.append(a)
    cands = []
    for rp in args:
        d = json.loads(Path(rp).read_text())
        for cell in d["cells"]:
            for t in cell["top"]:
                cands.append({"round": d["round"], "variant": cell["variant"], "tf": cell["tf"],
                              "mode": cell["mode"], **t})
    cands.sort(key=lambda c: (c["years_positive"], c["worst_year_r"], c["score"]), reverse=True)
    top, seen = [], set(exclude)
    for c in cands:
        fam = c["mode"] + ("_fade" if c["values"].get("s.orb_fade") else "")
        if fam in seen:
            continue
        seen.add(fam)
        top.append(c)
        if len(top) == 3:
            break

    ds = dataset.load(SYM, start="2019-01-02", end="2026-10-31")
    prep = bt.prepare(ds.bars, SYM)
    fit, hold = prep.slice(None, "2025-01-01"), prep.slice("2025-01-01", None)
    out = {"targets": TGT, "rounds": args, "n_candidates": len(cands), "top": []}
    for i, c in enumerate(top, 1):
        base_s = StrategyParams(mode=c["mode"], tf_minutes=c["tf"])
        base_e = bt.exec_config_from(prep.inst, risk_pct=0.005, be_offset_r=0.10)
        s_p, e_p = O.build(c["values"], base_s, base_e)
        m_fit, _, _ = bt.run(fit, s_p, e_p)
        m_h, tr_h, _ = bt.run(hold, s_p, e_p)
        _, tr_all, _ = bt.run(prep, s_p, e_p)
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
        tr_all["year"] = pd.DatetimeIndex(tr_all["entry_time"]).year
        by_year = []
        for y, g in tr_all.groupby("year"):
            w, l = g.r[g.r > 0].sum(), -g.r[g.r <= 0].sum()
            by_year.append({"year": int(y), "trades": len(g), "wr": round(float((g.r > 0).mean()), 3),
                            "pf": round(float(w / l), 2) if l > 0 else None,
                            "total_r": round(float(g.r.sum()), 2),
                            "sample": "HOLDOUT" if y >= 2025 else "fit"})
        mf, mh = mdict(m_fit), mdict(m_h)
        name = f"ScalperXBR_T{i}"
        tr_all.to_csv(ROOT / "reports" / f"xbr_top{i}_trades.csv", index=False)
        rec = {"rank": i, "ea": name, "round": c["round"], "variant": c["variant"], "mode": c["mode"],
               "tf": c["tf"], "fit_2019_2024": mf, "years_positive": c["years_positive"],
               "holdout_2025_2026": mh, "holdout_meets_targets": ok(mh), "fit_meets_targets": ok(mf),
               "holdout_cost_curve": curve, "by_year": by_year,
               "strategy": asdict(s_p), "execution": asdict(e_p)}
        out["top"].append(rec)
        notes = [
            f"XBRUSD {c['mode'].upper()}{' (fade)' if s_p.orb_fade else ''} on M{c['tf']}, "
            f"session {s_p.session} (UTC) - rank {i} of the top 3",
            f"fit 2019-2024: {mf['n_trades']} tr  WR {mf['win_rate']*100:.1f}%  PF {mf['profit_factor']:.2f}"
            f"  DD {mf['max_dd_pct']:.1f}%  ({c['years_positive']}/6 years positive)",
            f"HOLDOUT 2025-01..2026-10 (one look): {mh['n_trades']} tr  WR {mh['win_rate']*100:.1f}%"
            f"  PF {mh['profit_factor']:.2f}  DD {mh['max_dd_pct']:.1f}%  t={mh['t_stat']:.2f}",
            "targets WR>=57% PF>=1.01 DD<=20% trades>=100: "
            + ("MET on the holdout" if ok(mh) else "NOT all met on the holdout"),
            "see docs/RESULTS_XBRUSD.md",
        ]
        (ROOT / "config" / f"XBRUSD_top{i}.json").write_text(json.dumps(
            {"symbol": SYM, "mode": c["mode"], "strategy": asdict(s_p), "execution": asdict(e_p),
             "notes": notes}, indent=2, default=str))
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_ea.py"),
                        str(ROOT / "config" / f"XBRUSD_top{i}.json"), "--name", name], check=True)
        print(f"TOP{i} {c['round']} {c['variant']} M{c['tf']} {c['mode']}"
              f"{'(fade)' if s_p.orb_fade else ''} | FIT {mf['n_trades']}tr WR {mf['win_rate']*100:.1f}% "
              f"PF {mf['profit_factor']:.2f} DD {mf['max_dd_pct']:.1f}% yrs+ {c['years_positive']}/6 | HOLDOUT "
              f"{mh['n_trades']}tr WR {mh['win_rate']*100:.1f}% PF {mh['profit_factor']:.2f} "
              f"DD {mh['max_dd_pct']:.1f}% t {mh['t_stat']:.2f} -> {'PASS' if ok(mh) else 'fail'}", flush=True)
    (ROOT / "reports" / "xbr_top3.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
