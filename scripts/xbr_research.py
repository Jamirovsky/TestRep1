#!/usr/bin/env python3
"""XBRUSD: raw-edge tests of non-traditional, practitioner/academic oil strategies.

Each idea is measured directly on real OANDA M1 bars, net of a round-trip cost,
BEFORE any optimisation, so only ideas with a measurable edge get an EA:

1. EIA Wednesday (Unger Academy "one trade a week"; Wen et al., Energy J. 2023):
   direction of the first N minutes after the 10:30 ET release, held to the
   14:30 ET settlement window -- momentum and fade.
2. Intraday momentum (Gao-Han-Li-Zhou; Wen et al. 2021 for oil): first
   half-hour return (incl. overnight) predicts the last half-hour before
   settlement; EIA days use the 10:30-11:00 ET half-hour.
3. Larry Williams volatility breakout: open +/- k x prior-day range, exit at the
   Brent settlement (19:30 London).
4. Brent-WTI spread mean reversion (Ogrodniczuk hourly z-score; arXiv
   2309.00875): rolling 15-day z of ln(Brent/WTI), fade |z| > k, two legs costed.

    python3 scripts/xbr_research.py      -> reports/xbr_research.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import dataset

COST_BP = 7.0          # Brent round trip (spread 5 bp + slippage), as in the optimiser
EVENT_COST_BP = 10.0   # around the EIA release spreads widen
WTI_COST_BP = 7.0


def stats(r: pd.Series, cost: float) -> dict:
    r = r.dropna()
    net = r - cost
    if len(net) < 10:
        return {"n": int(len(net))}
    w, l = net[net > 0].sum(), -net[net <= 0].sum()
    eq = net.cumsum()
    return {"n": int(len(net)), "gross_bp": round(float(r.mean()), 2), "net_bp": round(float(net.mean()), 2),
            "wr": round(float((net > 0).mean()), 3), "pf": round(float(w / l), 3) if l > 0 else None,
            "t": round(float(net.mean() / net.std() * np.sqrt(len(net))), 2),
            "max_dd_bp": round(float((eq.cummax() - eq).max()), 1),
            "pf_2025_26": _pf(net[net.index >= pd.Timestamp("2025-01-01", tz="UTC")])}


def _pf(x):
    if len(x) < 5:
        return None
    w, l = x[x > 0].sum(), -x[x <= 0].sum()
    return round(float(w / l), 3) if l > 0 else None


def at(px: pd.Series, local: pd.DatetimeIndex, day, hhmm: str):
    """Close of the M1 bar that ENDS at local time hhmm on `day` (label = hhmm - 1 min)."""
    return px.get((day, hhmm))


def main() -> int:
    b = dataset.load("XBRUSD", start="2019-01-02", end="2026-10-31").bars
    c = b["close"]
    out = {}

    # ---------------- 1 + 2: New-York clock events ---------------------------
    ny = c.copy()
    ny.index = c.index.tz_convert("America/New_York")
    key = pd.MultiIndex.from_arrays([ny.index.date, ny.index.strftime("%H:%M")])
    s = pd.Series(ny.values, index=key)
    s = s[~s.index.duplicated()]
    days = sorted(set(ny.index.date))
    utc_of = {d: pd.Timestamp(d).tz_localize("America/New_York").tz_convert("UTC") for d in days}

    def px(d, hhmm):  # close of the bar labelled hhmm
        try:
            return float(s.loc[(d, hhmm)])
        except KeyError:
            return np.nan

    # EIA: Wednesdays, release 10:30 ET
    for n in (5, 15, 30):
        for hold_to in ("11:29", "12:29", "14:29"):
            rows = []
            for d in days:
                if pd.Timestamp(d).dayofweek != 2:
                    continue
                p0 = px(d, "10:29")
                t1 = (pd.Timestamp("2000-01-01 10:29") + pd.Timedelta(minutes=n)).strftime("%H:%M")
                p1, p2 = px(d, t1), px(d, hold_to)
                if not np.isfinite([p0, p1, p2]).all():
                    continue
                move = np.log(p1 / p0) * 1e4
                if abs(move) < 5:
                    continue
                rows.append((utc_of[d], np.sign(move) * np.log(p2 / p1) * 1e4))
            r = pd.Series(dict(rows))
            out[f"eia_mom_first{n}m_to_{hold_to}"] = stats(r, EVENT_COST_BP)
            out[f"eia_fade_first{n}m_to_{hold_to}"] = stats(-r, EVENT_COST_BP)

    # intraday momentum: (prev 14:29 -> 09:59) predicts 14:00 -> 14:29 ET
    rows, rows_eia = [], []
    prev_settle = None
    for d in days:
        if pd.Timestamp(d).dayofweek >= 5:
            continue
        p_open, p_a, p_b = px(d, "09:59"), px(d, "13:59"), px(d, "14:29")
        if prev_settle is not None and np.isfinite([prev_settle, p_open, p_a, p_b]).all():
            sig = np.sign(np.log(p_open / prev_settle))
            if pd.Timestamp(d).dayofweek == 2:
                p_r0, p_r1 = px(d, "10:29"), px(d, "10:59")
                if np.isfinite([p_r0, p_r1]).all():
                    rows_eia.append((utc_of[d], np.sign(np.log(p_r1 / p_r0)) * np.log(p_b / p_a) * 1e4))
            rows.append((utc_of[d], sig * np.log(p_b / p_a) * 1e4))
        if np.isfinite(px(d, "14:29")):
            prev_settle = px(d, "14:29")
    out["imom_ny_firsthalf_to_lasthalf"] = stats(pd.Series(dict(rows)), COST_BP)
    out["imom_ny_eia_1030_to_lasthalf"] = stats(pd.Series(dict(rows_eia)), COST_BP)

    # London-clock version for Brent (ICE settlement 19:28-19:30 London)
    ld = c.copy()
    ld.index = c.index.tz_convert("Europe/London")
    keyl = pd.MultiIndex.from_arrays([ld.index.date, ld.index.strftime("%H:%M")])
    sl = pd.Series(ld.values, index=keyl)
    sl = sl[~sl.index.duplicated()]
    ldays = sorted(set(ld.index.date))

    def pl(d, hhmm):
        try:
            return float(sl.loc[(d, hhmm)])
        except KeyError:
            return np.nan

    rows = []
    prev = None
    for d in ldays:
        if pd.Timestamp(d).dayofweek >= 5:
            continue
        po, pa, pb = pl(d, "08:29"), pl(d, "18:59"), pl(d, "19:27")
        if prev is not None and np.isfinite([prev, po, pa, pb]).all():
            rows.append((pd.Timestamp(d, tz="UTC"), np.sign(np.log(po / prev)) * np.log(pb / pa) * 1e4))
        if np.isfinite(pl(d, "19:27")):
            prev = pl(d, "19:27")
    out["imom_london_firsthalf_to_settle"] = stats(pd.Series(dict(rows)), COST_BP)

    # ---------------- 3: Larry Williams volatility breakout ---------------------
    lb = b.copy()
    lb.index = b.index.tz_convert("Europe/London")
    lb["d"] = lb.index.date
    daily = lb.groupby("d").agg(o=("open", "first"), h=("high", "max"), l=("low", "min"))
    daily["rng_prev"] = (daily.h - daily.l).shift(1)
    for k in (0.3, 0.5, 0.7):
        rows = []
        for d, g in lb.groupby("d"):
            if d not in daily.index or not np.isfinite(daily.loc[d, "rng_prev"]):
                continue
            g = g[(g.index.hour >= 1) & ((g.index.hour < 19) | ((g.index.hour == 19) & (g.index.minute < 28)))]
            if len(g) < 60:
                continue
            o, R = g.open.iloc[0], daily.loc[d, "rng_prev"]
            up, dn = o + k * R, o - k * R
            hit_up = g.index[g.high >= up]
            hit_dn = g.index[g.low <= dn]
            t_up = hit_up[0] if len(hit_up) else None
            t_dn = hit_dn[0] if len(hit_dn) else None
            if t_up is None and t_dn is None:
                continue
            exit_px = g.close.iloc[-1]
            if t_dn is None or (t_up is not None and t_up <= t_dn):
                rows.append((pd.Timestamp(d, tz="UTC"), np.log(exit_px / up) * 1e4))
            else:
                rows.append((pd.Timestamp(d, tz="UTC"), np.log(dn / exit_px) * 1e4))
        out[f"williams_vbo_k{k}"] = stats(pd.Series(dict(rows)), COST_BP)

    # ---------------- 4: Brent-WTI spread mean reversion -------------------------
    w = dataset.load("XTIUSD", start="2019-01-02", end="2026-10-31").bars["close"]
    hb = c.resample("60min").last()
    hw = w.resample("60min").last()
    df = pd.concat([hb.rename("b"), hw.rename("w")], axis=1, sort=True).dropna()
    df = df[(df.b > 5) & (df.w > 5)]                      # April 2020: WTI went negative
    spread = np.log(df.b) - np.log(df.w)
    mu = spread.rolling(360).mean()
    sd = spread.rolling(360).std()
    z = (spread - mu) / sd
    hrs = df.index.hour
    for kz in (2.0, 2.5, 3.0):
        for hold in (24, 72):
            rows, i = [], 360
            zv, sv = z.to_numpy(), spread.to_numpy()
            while i < len(df) - 1:
                if np.isfinite(zv[i]) and abs(zv[i]) >= kz and 7 <= hrs[i] < 20:
                    d = -np.sign(zv[i])
                    j = i + 1
                    while j < len(df) - 1 and j - i < hold and abs(zv[j]) > 0.5:
                        j += 1
                    rows.append((df.index[i], d * (sv[j] - sv[i]) * 1e4))
                    i = j + 1
                else:
                    i += 1
            out[f"brent_wti_z{kz}_hold{hold}h"] = stats(pd.Series(dict(rows)), COST_BP + WTI_COST_BP)

    (ROOT / "reports" / "xbr_research.json").write_text(json.dumps(out, indent=1))
    for k, v in out.items():
        print(f"{k:40s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
