#!/usr/bin/env python3
"""Run this FIRST on any instrument, before optimising anything.

It answers, in about a minute, the two questions that decide whether a scalping
strategy is possible at all:

1. **Is there any structure to trade?**  The variance ratio says whether returns
   trend, mean-revert, or are indistinguishable from a random walk -- and at
   which horizon.  If VR is 1.0 at your intended holding time, no amount of
   optimisation will help; you are fitting noise.
2. **Can the structure pay for the spread?**  Round-trip friction divided by
   ATR is the hurdle every trade must clear before it earns anything.

    python3 scripts/diagnose.py --symbols EURUSD XAUUSD
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import dataset, indicators as ind, research
from scalping.instruments import get_instrument


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["EURUSD", "XAUUSD"])
    ap.add_argument("--start", default="2019-01-02")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--tf", type=int, default=5, help="signal timeframe in minutes")
    args = ap.parse_args()

    for symbol in args.symbols:
        inst = get_instrument(symbol)
        ds = dataset.load(symbol, start=args.start, end=args.end)
        print("=" * 72)
        print(ds.banner())

        bars = ds.bars
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        tf = bars.resample(f"{args.tf}min", label="left", closed="left").agg(agg).dropna()

        atr = ind.atr(
            tf["high"].to_numpy("float64"), tf["low"].to_numpy("float64"),
            tf["close"].to_numpy("float64"), 14,
        )
        atr_med = float(np.nanmedian(atr))
        friction = research.round_trip_cost_points(inst)
        friction_price = friction * inst.point

        print(f"\n  friction (round trip)   {friction:6.1f} points = "
              f"{inst.fmt_distance(friction_price)}")
        print(f"  median ATR({args.tf}m)        {inst.fmt_distance(atr_med)}")
        print(f"  friction / ATR          {friction_price / atr_med:6.2f}"
              "   <- every trade starts this far behind")

        print(f"\n  stop size -> friction as a share of the risked amount (R):")
        for mult in (1.0, 2.0, 3.0, 5.0, 8.0):
            sl = mult * atr_med
            print(f"    {mult:.0f} x ATR = {inst.fmt_distance(sl):>14s}"
                  f" -> {friction_price / sl * 100:5.1f}% of R"
                  f"   (breakeven win rate at 1:1 = "
                  f"{50 * (1 + friction_price / sl):.1f}%)")

        vr = research.variance_ratio(tf["close"], (2, 4, 12, 24, 48, 96))
        vr["horizon_min"] = vr["horizon_bars"] * args.tf
        vr["reading"] = np.where(
            vr["z_stat"].abs() < 2, "random walk",
            np.where(vr["variance_ratio"] > 1, "TRENDING", "mean-reverting"),
        )
        print("\n  variance ratio (VR=1 random walk; |z|<2 = not distinguishable):")
        print(vr[["horizon_min", "variance_ratio", "z_stat", "reading"]]
              .to_string(index=False, justify="right"))

        tradeable = vr[(vr["z_stat"].abs() >= 2)]
        if len(tradeable):
            first = int(tradeable["horizon_min"].iloc[0])
            print(f"\n  -> structure first becomes significant at {first} minutes.")
            print(f"     Holding for less than that means trading noise while paying "
                  f"{inst.fmt_distance(friction_price)} a round trip.")
        else:
            print("\n  -> no horizon shows structure distinguishable from a random walk.")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
