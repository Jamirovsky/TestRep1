#!/usr/bin/env python3
"""Package the validated parameters into config/<SYM>_final.json and an EA.

Which parameter set ships?  The one from the FIT-ONCE HOLDOUT of
run_optimize.py: fitted on 2019-2024, then traded Jan 2025 - Oct 2026 without
any re-selection.  That makes the 2025-2026 numbers a genuine out-of-sample
measurement of the exact defaults compiled into the EA -- something neither
the last walk-forward fold (validated on only 120 days) nor a refit on all
data can offer.

    python3 scripts/finalize_metals.py XAGUSD:momentum:ScalperXAG XPTUSD:momentum:ScalperXPT \
                                       XPDUSD:bands:ScalperXPD
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt, dataset
from scalping.engine import ExecConfig
from scalping.strategy import StrategyParams


def main() -> int:
    for spec in sys.argv[1:]:
        sym, mode, name = spec.split(":")
        wf = json.loads((ROOT / "config" / f"{sym}_{mode}_wf.json").read_text())
        v = wf["validation"]
        hp = v["holdout_params"]
        s = StrategyParams(**{f.name: hp["strategy"][f.name] for f in fields(StrategyParams)})
        e = ExecConfig(**{f.name: hp["execution"][f.name] for f in fields(ExecConfig)})

        ds = dataset.load(sym, start="2019-01-02", end="2026-10-31")
        prep = bt.prepare(ds.bars, sym)
        _, tr, _ = bt.run(prep, s, e)
        tr["year"] = pd.DatetimeIndex(tr["entry_time"]).year
        by_year = []
        for y, g in tr.groupby("year"):
            wins, losses = g.r[g.r > 0].sum(), -g.r[g.r <= 0].sum()
            by_year.append({"year": int(y), "trades": len(g), "win_rate": round((g.r > 0).mean(), 3),
                            "profit_factor": round(wins / losses, 2) if losses > 0 else None,
                            "total_r": round(g.r.sum(), 2),
                            "sample": "fit" if y < 2025 else "HOLDOUT"})
        ho, oos = v["holdout"], v["oos"]
        notes = [
            f"{sym} {mode.upper()} on M{s.tf_minutes}, session {s.session} (UTC)",
            f"fit 2019-2024, frozen test 2025-01..2026-10 (real OANDA M1):",
            f"  {ho['n_trades']} trades  WR {ho['win_rate']*100:.1f}%  PF {ho['profit_factor']:.2f}"
            f"  {ho['expectancy_r']:+.3f}R  t={ho['t_stat']:.2f}",
            f"walk-forward 2021-2026 (17 refits, stitched OOS):",
            f"  {oos['n_trades']} trades  WR {oos['win_rate']*100:.1f}%  PF {oos['profit_factor']:.2f}"
            f"  {oos['expectancy_r']:+.3f}R  t={oos['t_stat']:.2f}",
            ("LOSES with statistical significance (t < -2) - do not trade these defaults"
             if min(ho["t_stat"], oos["t_stat"]) < -2.0 else
             "NOT statistically significant - not an established edge"),
            "see docs/RESULTS_METALS.md",
        ]
        out = {
            "symbol": sym, "mode": mode, "ea": name,
            "data": wf["data"],
            "strategy": hp["strategy"], "execution": hp["execution"],
            "notes": notes,
            "validation": {
                "selection": "fit-once on 2019-01-02..2025-01-01, frozen thereafter",
                "holdout_2025_2026": ho,
                "holdout_cost_curve": v["holdout_cost_curve"],
                "walk_forward_oos": oos,
                "walk_forward_efficiency": v["walk_forward_efficiency"],
                "bootstrap_p_value_wf": v["bootstrap_p_value"],
                "by_year": by_year,
            },
        }
        cfg_path = ROOT / "config" / f"{sym}_final.json"
        cfg_path.write_text(json.dumps(out, indent=2, default=str))
        print(f"{sym}: wrote {cfg_path.relative_to(ROOT)}")
        for r in by_year:
            print("   ", r)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_ea.py"), str(cfg_path),
                        "--name", name], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
