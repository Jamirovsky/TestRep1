#!/usr/bin/env python3
"""Brent-WTI spread mean reversion (XBRUSD vs XTIUSD), the one researched idea with an edge.

Signal: s = ln(Brent) - ln(WTI) on closed bars; z = (s - mean_N) / std_N over a
rolling window.  |z| >= k  ->  bet on reversion: z > 0 sells Brent / buys WTI,
z < 0 buys Brent / sells WTI, equal USD notional per leg.  Exit when |z| <= z_exit,
when |z| >= z_stop (spread stop), or after max_hold bars.  Entries only on bars
that open inside the entry window; fills at the NEXT bar's open on both legs.

Costs per round trip: Brent 7 bp + WTI 7 bp (spread + slippage), plus CFD
financing of 1.5 bp per leg per rollover night (21:00 UTC, x3 on Wednesday).

Selection uses 2019-2024 only; 2025-01 -> 2026-10 is reported separately.

    python3 scripts/xbr_spread.py
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import dataset

COST_RT_BP = 7.0 + 7.0
SWAP_BP_NIGHT = 1.5 * 2
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
TGT = {"wr": 0.57, "pf": 1.01, "dd": 20.0, "trades": 100}


def load(tf: int):
    b = dataset.load("XBRUSD", start="2019-01-02", end="2026-10-31").bars
    w = dataset.load("XTIUSD", start="2019-01-02", end="2026-10-31").bars
    agg = {"open": "first", "close": "last"}
    rb = b.resample(f"{tf}min").agg(agg)
    rw = w.resample(f"{tf}min").agg(agg)
    df = pd.concat([rb.add_prefix("b_"), rw.add_prefix("w_")], axis=1, sort=True).dropna()
    return df[(df.b_close > 5) & (df.w_close > 5) & (df.b_open > 5) & (df.w_open > 5)]


def nights(t0, t1):
    """Rollovers (21:00 UTC) crossed between t0 and t1, Wednesday counting triple."""
    n = 0
    d = t0.normalize() + pd.Timedelta(hours=21)
    if d <= t0:
        d += pd.Timedelta(days=1)
    while d <= t1:
        if d.dayofweek < 5:
            n += 3 if d.dayofweek == 2 else 1
        d += pd.Timedelta(days=1)
    return n


def run(df, tf, lookback_days, k, z_exit, z_stop, max_hold_h, hours=(0, 24)):
    n = int(lookback_days * 24 * 60 / tf)
    s = np.log(df.b_close) - np.log(df.w_close)
    z = ((s - s.rolling(n).mean()) / s.rolling(n).std()).to_numpy()
    bo, wo = df.b_open.to_numpy(), df.w_open.to_numpy()
    idx = df.index
    hr = idx.hour
    maxb = int(max_hold_h * 60 / tf)
    rows, i, N = [], n, len(df)
    while i < N - 2:
        if np.isfinite(z[i]) and abs(z[i]) >= k and hours[0] <= hr[i] < hours[1]:
            d = -np.sign(z[i])                      # +1 = long Brent / short WTI
            e = i + 1                               # fill at next bar open
            j = e
            reason = "time"
            while j < N - 1 and j - e < maxb:
                if abs(z[j]) <= z_exit:
                    reason = "target"
                    break
                if abs(z[j]) >= z_stop:
                    reason = "stop"
                    break
                j += 1
            x = min(j + 1, N - 1)                   # exit at the next bar open
            gross = d * (np.log(bo[x] / bo[e]) - np.log(wo[x] / wo[e])) * 1e4
            sw = nights(idx[e], idx[x]) * SWAP_BP_NIGHT
            rows.append({"entry_time": idx[e], "exit_time": idx[x], "dir": int(d), "z_entry": float(z[i]),
                         "gross_bp": gross, "net_bp": gross - COST_RT_BP - sw, "reason": reason,
                         "hours": (idx[x] - idx[e]).total_seconds() / 3600})
            i = x + 1
        else:
            i += 1
    return pd.DataFrame(rows)


def metrics(t: pd.DataFrame, lev: float = 1.0) -> dict:
    if len(t) == 0:
        return {"n": 0}
    r = t.net_bp
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    eq = np.cumprod(1 + lev * r.to_numpy() / 1e4)
    dd = float(np.max(1 - eq / np.maximum.accumulate(eq)) * 100)
    return {"n": int(len(t)), "wr": round(float((r > 0).mean()), 4), "pf": round(float(w / l), 3) if l > 0 else 99.0,
            "net_bp": round(float(r.mean()), 2), "t": round(float(r.mean() / r.std() * np.sqrt(len(r))), 2)
            if len(r) > 1 else 0.0, "dd_pct": round(dd, 2), "ret_pct": round(float((eq[-1] - 1) * 100), 2),
            "avg_hours": round(float(t.hours.mean()), 1)}


def main() -> int:
    grid = {"tf": [30, 60], "lookback_days": [10, 15, 20], "k": [2.25, 2.5, 2.75, 3.0],
            "z_exit": [0.0, 0.5, 1.0], "z_stop": [5.0, 99.0], "max_hold_h": [24, 48, 72, 120]}
    data = {tf: load(tf) for tf in grid["tf"]}
    res = []
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        p = dict(zip(keys, combo))
        t = run(data[p["tf"]], **p)
        if not len(t):
            continue
        fit = t[t.entry_time < SPLIT]
        m = metrics(fit)
        # per-year consistency on the fit window
        yrs = fit.groupby(fit.entry_time.dt.year).net_bp.sum()
        res.append({"params": p, "fit": m, "years_pos": int((yrs > 0).sum()), "n_years": int(len(yrs))})
    # selection on 2019-2024 only: enough trades for >=100 over the full span (~13/yr),
    # WR and PF above target with margin, then t-stat
    ok = [r for r in res if r["fit"]["n"] >= 80 and r["fit"]["wr"] >= 0.57 and r["fit"]["pf"] >= 1.2]
    ok.sort(key=lambda r: (r["years_pos"], r["fit"]["t"]), reverse=True)
    print(f"{len(res)} combos, {len(ok)} meet the fit filter")
    for r in ok[:8]:
        print(r["params"], r["fit"], f"years+ {r['years_pos']}/{r['n_years']}")
    # robustness: neighbourhood of the winner (median PF of single-parameter neighbours)
    best = ok[0]
    bp = best["params"]
    neigh = []
    for kk in keys:
        vals = grid[kk]
        i = vals.index(bp[kk])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                q = dict(bp, **{kk: vals[j]})
                m = next((r["fit"] for r in res if r["params"] == q), None)
                if m:
                    neigh.append(m["pf"])
    t_all = run(data[bp["tf"]], **bp)
    fit, hold = t_all[t_all.entry_time < SPLIT], t_all[t_all.entry_time >= SPLIT]
    # leverage (USD notional per leg / equity) chosen on the fit so that fit DD <= 10%
    lev = 1.0
    for L in (10, 8, 6, 5, 4, 3, 2, 1.5, 1):
        if metrics(fit, L)["dd_pct"] <= 10.0:
            lev = L
            break
    out = {"selected": bp, "leverage_per_leg": lev, "n_combos": len(res), "n_pass_fit_filter": len(ok),
           "neighbour_pf_median": float(np.median(neigh)) if neigh else None,
           "neighbour_pf_min": float(np.min(neigh)) if neigh else None,
           "fit_2019_2024": metrics(fit, lev), "holdout_2025_2026": metrics(hold, lev),
           "all_2019_2026": metrics(t_all, lev),
           "by_year": [{"year": int(y), **metrics(g, lev)} for y, g in t_all.groupby(t_all.entry_time.dt.year)],
           "exit_reasons": t_all.reason.value_counts().to_dict(),
           "cost_curve_all": [], "top_fit": [{"params": r["params"], "fit": r["fit"], "years_pos": r["years_pos"]}
                                             for r in ok[:10]]}
    for cm in (0.0, 0.5, 1.0, 1.5, 2.0):
        tt = t_all.copy()
        sw = tt.gross_bp - tt.net_bp - COST_RT_BP
        tt["net_bp"] = tt.gross_bp - cm * COST_RT_BP - sw
        out["cost_curve_all"].append({"cost_multiple": cm, **metrics(tt, lev)})
    t_all.to_csv(ROOT / "reports" / "xbr_spread_trades.csv", index=False)
    (ROOT / "reports" / "xbr_spread.json").write_text(json.dumps(out, indent=1, default=str))
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=110)
    ax.plot(t_all.exit_time, t_all.net_bp.cumsum(), color="black", lw=1.6)
    ax.axvspan(SPLIT, t_all.exit_time.max(), color="tab:green", alpha=0.08, label="2025–26 (fora do ajuste)")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_ylabel("bp acumulados (líquidos, por unidade de notional)")
    ax.set_title(f"Spread Brent–WTI: z ≥ {bp['k']}, M{bp['tf']}, janela {bp['lookback_days']} dias")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(ROOT / "reports" / "xbr_spread_equity.png")
    print(json.dumps({k: out[k] for k in ("selected", "leverage_per_leg", "neighbour_pf_median", "neighbour_pf_min",
                                           "fit_2019_2024", "holdout_2025_2026", "all_2019_2026", "exit_reasons")},
                     indent=1, default=str))
    for y in out["by_year"]:
        print(y)
    print(out["cost_curve_all"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
