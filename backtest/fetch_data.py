"""Fetch and cache data for the OrderFlowIcebergEA backtest.

- Yahoo v8 chart API: 1-minute CME futures bars (real exchange volume), last ~30 days,
  fetched in 7-day windows (Yahoo's 1m limit).
- Binance public data archive: BTCUSDT perpetual aggTrades (each trade carries the
  aggressor side), one zip per day.

Cache lives in backtest/data/ (gitignored). Stdlib only.
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def yahoo_1m(ticker: str, days: int = 29) -> pd.DataFrame:
    """1-minute bars for the last `days` days, index = America/New_York time."""
    f = DATA / f"{ticker.replace('=', '_')}_1m.csv"
    if f.exists():
        df = pd.read_csv(f, index_col=0)
        df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
        return df
    end = int(time.time())
    start = end - days * 86400
    frames = []
    p1 = start
    while p1 < end:
        p2 = min(p1 + 7 * 86400, end)
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={p1}&period2={p2}&interval=1m&includePrePost=true")
        js = json.loads(_get(url))
        res = js["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        frames.append(pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"],
                                    "close": q["close"], "volume": q["volume"]},
                                   index=pd.to_datetime(ts, unit="s", utc=True)))
        p1 = p2
        time.sleep(0.5)
    df = pd.concat(frames)
    df = df[~df.index.duplicated()].sort_index().dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    df.to_csv(f)
    return df.tz_convert("America/New_York")


def binance_aggtrades(day: date, symbol: str = "BTCUSDT") -> pd.DataFrame:
    """One UTC day of USD-M futures aggTrades: time(ms), price, qty, side (+1 buy aggressor, -1 sell)."""
    f = DATA / f"{symbol}_aggTrades_{day.isoformat()}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    url = (f"https://data.binance.vision/data/futures/um/daily/aggTrades/{symbol}/"
           f"{symbol}-aggTrades-{day.isoformat()}.zip")
    raw = _get(url, timeout=120)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            head = fh.read(64)
        has_header = head[:1].isalpha()
        with z.open(name) as fh:
            df = pd.read_csv(fh, header=0 if has_header else None)
    if not has_header:
        df.columns = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
                      "transact_time", "is_buyer_maker"]
    out = pd.DataFrame({
        "ms": df["transact_time"].astype("int64"),
        "price": df["price"].astype("float64"),
        "qty": df["quantity"].astype("float64"),
        # buyer is maker -> the seller hit the bid -> aggressive SELL
        "side": (1 - 2 * df["is_buyer_maker"].astype(str).str.lower().eq("true").astype("int8")).astype("int8"),
    })
    out.to_parquet(f)
    return out


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "futures"
    if what == "futures":
        for t in ["NQ=F", "ES=F", "GC=F", "CL=F"]:
            d = yahoo_1m(t)
            print(t, len(d), d.index.min(), d.index.max())
    else:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        last = datetime.now(timezone.utc).date() - timedelta(days=2)
        for k in range(n):
            d = last - timedelta(days=k)
            try:
                df = binance_aggtrades(d)
                print(d, len(df))
            except Exception as e:  # noqa: BLE001
                print(d, "failed:", e)
