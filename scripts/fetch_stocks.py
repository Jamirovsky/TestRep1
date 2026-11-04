#!/usr/bin/env python3
"""Download real 1-minute bars for the seven largest US stocks.

Source: the free ``getdata-finance/<ticker>-1m-ohlcv-stocks-historical-data``
samples on GitHub.  Each weekly commit holds a rolling ~6-month window, so the
union over the git history reaches back further than any single snapshot
(Feb 2026 onwards at the time of writing).  Regular US session only, UTC
timestamps, consolidated volume.

    python3 scripts/fetch_stocks.py            # AAPL MSFT NVDA AMZN GOOGL META TSLA
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
SOURCE = {"GOOGL": "GOOG"}   # only the class-C line is published; it tracks GOOGL tick for tick


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=TICKERS)
    ap.add_argument("--tf", default="1m")
    args = ap.parse_args()
    for t in args.tickers:
        src = SOURCE.get(t, t)
        url = f"https://github.com/getdata-finance/{src.lower()}-{args.tf}-ohlcv-stocks-historical-data"
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "clone", "-q", "--bare", url, tmp + "/r"], check=True)
            revs = subprocess.run(["git", "-C", tmp + "/r", "rev-list", "--all"], check=True,
                                  capture_output=True, text=True).stdout.split()
            frames = []
            for rev in revs:
                out = subprocess.run(["git", "-C", tmp + "/r", "show", f"{rev}:{src}_{args.tf}.csv"],
                                     capture_output=True)
                if out.returncode == 0 and out.stdout:
                    f = pd.read_csv(io.BytesIO(out.stdout))
                    frames.append(f.rename(columns={"time": "datetime"}))
        df = pd.concat(frames)
        ts = pd.to_datetime(df["datetime"], utc=True, format="ISO8601")
        df["time"] = ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).astype("int64")
        df = (df.drop(columns=["datetime"]).drop_duplicates("time", keep="last")
                .sort_values("time")[["time", "open", "high", "low", "close", "volume"]])
        dest = ROOT / "data" / "raw" / t
        dest.mkdir(parents=True, exist_ok=True)
        df.to_parquet(dest / f"{t}_{args.tf}_getdata.parquet", index=False)
        first = pd.to_datetime(df.time.iloc[0], unit="s")
        last = pd.to_datetime(df.time.iloc[-1], unit="s")
        print(f"{t}: {len(df):,} bars from {len(revs)} snapshots, {first} -> {last}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
