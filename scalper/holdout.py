"""Forward test on the untouched holdout window + cost stress tests.

    python -m scalper.holdout

Candidates are pre-registered: P1 = best plateau set from optimize_full, P2 = best
learned-memory set, plus two reference configurations found during exploration.
"""
from __future__ import annotations
import json, os
import numpy as np

from .backtest import Market, COSTS, DEFAULTS, run_period, metrics, score
from .data import load_1m

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDOUT = ("2026-08-01", "2026-11-19")
DEV = ("2024-11-15", "2026-08-01")
STRESS = {"base": {}, "spread50": {"spread": 50.0}, "spread75_slip15": {"spread": 75.0, "slip": 15.0}}


def ref(tf, n, thr, sl, tp, mh, mom_days, mem):
    p = dict(DEFAULTS)
    p.update(fam_mask=1, tf=tf, imp_n=n, imp_thr=thr, sl_k=sl, tp_k=tp, max_hold=mh, atr_n=14,
             trend_filter=1 if mom_days else 0, mom_n=(mom_days or 7) * 1440 // tf,
             be_trig=0.0, trail_k=0.0, risk=0.02, min_stop_spread=2.0, dd_cut=1.0, mem_k=0.0)
    if mem:
        p.update(bucket=3, mem_warm=5, mem_thr=0.0, mem_alpha=0.1)
    else:
        p.update(bucket=0, mem_warm=0, mem_thr=-1e9)
    return p


def candidates():
    full = json.load(open(os.path.join(ROOT, "results", "full_v7.json")))["ranked"]
    p1 = full[0]["params"]
    p2 = next(r["params"] for r in full if r["params"]["bucket"] == 3)
    prev = os.path.join(ROOT, "config", "round1_capital_com.json")
    out = {"P1_plateau": p1, "P2_memory": p2,
           "REF_B_15m_mom7": ref(15, 3, 2.2, 2.5, 5.0, 48, 7, 0),
           "REF_C_15m_mom7_mem": ref(15, 3, 2.2, 2.5, 5.0, 48, 7, 1)}
    if os.path.exists(prev):   # sleeve A of the first research round (Capital.com / BTCUSDT)
        out["REF_R1_A"] = json.load(open(prev))["sleeves"][0]["params"]
    return out


def main():
    m = Market(load_1m())
    eq0 = COSTS["equity0"]
    out = {}
    for name, p in candidates().items():
        out[name] = {"params": p}
        for period_name, per in (("dev", DEV), ("holdout", HOLDOUT)):
            for sname, cost in STRESS.items():
                if period_name == "dev" and sname != "base":
                    continue
                tr, deq, mem, i0 = run_period(m, p, *per, cost=cost)
                mt = metrics(tr, deq, eq0)
                mt["score"] = score(mt, min_trades_per_month=4)
                out[name][f"{period_name}_{sname}"] = mt
                if sname == "base":
                    np.save(os.path.join(ROOT, "results", f"{name}_{period_name}_equity.npy"), deq)
                    np.save(os.path.join(ROOT, "results", f"{name}_{period_name}_trades.npy"), tr)
                print(f"{name:20s} {period_name:7s} {sname:16s} n={mt['trades']:4d} PF {mt['pf']:.2f} "
                      f"SR {mt['sharpe']:5.2f} ret {mt['ret_pct']:+6.1f}% DD {mt['max_dd_pct']:5.1f}% "
                      f"win {mt['win_rate']:.0f}% final {mt['final'] / 1.16:.2f} EUR")
    # two-sleeve ensembles of the pre-registered candidates
    from .backtest import run_ensemble
    cands = candidates()
    for combo in (("P1_plateau", "P2_memory"), ("P1_plateau", "REF_C_15m_mom7_mem")):
        if not all(c in cands for c in combo):
            continue
        name = "+".join(combo)
        out[name] = {"params": [cands[c] for c in combo]}
        for period_name, per in (("dev", DEV), ("holdout", HOLDOUT)):
            for sname, cost in STRESS.items():
                if period_name == "dev" and sname != "base":
                    continue
                tr, deq, _ = run_ensemble(m, [cands[c] for c in combo], *per, cost=cost)
                mt = metrics(tr, deq, eq0)
                mt["score"] = score(mt, min_trades_per_month=4)
                out[name][f"{period_name}_{sname}"] = mt
                print(f"{name:20s} {period_name:7s} {sname:16s} n={mt['trades']:4d} PF {mt['pf']:.2f} "
                      f"SR {mt['sharpe']:5.2f} ret {mt['ret_pct']:+6.1f}% DD {mt['max_dd_pct']:5.1f}% "
                      f"win {mt['win_rate']:.0f}% final {mt['final'] / 1.16:.2f} EUR")
    out["_meta"] = {"data": os.environ.get("AMS_DATA", "bitstamp"), "costs": COSTS}
    with open(os.path.join(ROOT, "results", "holdout.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)


if __name__ == "__main__":
    main()
