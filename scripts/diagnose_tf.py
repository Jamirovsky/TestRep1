#!/usr/bin/env python3
"""Stage 0 for the metals: which signal timeframe (M1..M30) can pay the toll?

For every symbol and every candidate timeframe this prints, measured in basis
points of price during the liquid London/NY hours (07-18 UTC):

* median ATR(14) of the signal timeframe,
* round-trip friction (spread + entry slippage + stop slippage),
* friction / ATR -- the hurdle every trade starts behind,
* the Lo-MacKinlay variance ratio at 1, 2 and 4 hours, i.e. whether there is
  directional structure to pay that hurdle with.

The rule of thumb from the XAUUSD study: a scalper needs friction below ~0.15
of the stop, and stops are 1.5-3 ATR, so friction / ATR must be under ~0.3-0.4
on the chosen timeframe before an optimiser is worth running at all.

    python3 scripts/diagnose_tf.py --symbols XAGUSD XPTUSD XPDUSD XAUUSD
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import dataset, indicators as ind, research
from scalping.instruments import get_instrument

TFS = (1, 5, 15, 30)


def friction_bp(inst, price: float) -> float:
    scale = price / inst.ref_price if inst.ref_price > 0 else 1.0
    pts = research.round_trip_cost_points(inst) * scale
    return pts * inst.point / price * 1e4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["XAGUSD", "XPTUSD", "XPDUSD", "XAUUSD"])
    ap.add_argument("--start", default="2019-01-02")
    ap.add_argument("--end", default="2026-10-31")
    ap.add_argument("--out", default=str(ROOT / "reports" / "metals_diagnose.json"))
    args = ap.parse_args()

    rows = []
    for symbol in args.symbols:
        inst = get_instrument(symbol)
        ds = dataset.load(symbol, start=args.start, end=args.end)
        print(ds.banner(), flush=True)
        bars = ds.bars
        for tf in TFS:
            agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
            b = bars if tf == 1 else bars.resample(f"{tf}min", label="left", closed="left").agg(agg).dropna()
            h, l, c = (b[k].to_numpy("float64") for k in ("high", "low", "close"))
            atr = ind.atr(h, l, c, 14)
            hrs = b.index.hour
            liquid = (hrs >= 7) & (hrs < 18)
            atr_bp = np.nanmedian((atr / c * 1e4)[liquid])
            fr = np.nanmedian([friction_bp(inst, p) for p in np.nanpercentile(c, [25, 50, 75])])
            horizons = [max(1, 60 // tf), max(1, 120 // tf), max(1, 240 // tf)]
            vr = research.variance_ratio(b["close"], [x for x in horizons if x >= 2] or [2])
            vrd = {int(r.horizon_bars * tf): (round(float(r.variance_ratio), 3), round(float(r.z_stat), 2))
                   for r in vr.itertuples()}
            row = {"symbol": symbol, "tf": tf, "atr_bp": round(float(atr_bp), 2),
                   "friction_bp": round(float(fr), 2),
                   "friction_over_atr": round(float(fr / atr_bp), 3), "vr": vrd}
            rows.append(row)
            print(f"  M{tf:<2d} ATR {atr_bp:6.2f}bp  friction {fr:5.2f}bp  "
                  f"friction/ATR {fr / atr_bp:5.2f}  VR(min:(vr,z)) {vrd}", flush=True)
    Path(args.out).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
