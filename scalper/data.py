"""Data loading: Binance public 1m klines (proxy feed) + optional Capital.com loader."""
from __future__ import annotations
import glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CACHE = os.path.join(ROOT, "data", "btcusd_1m.parquet")

COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "qvol", "trades", "tbb", "tbq", "ignore"]


def _read_zip(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        df = pd.read_csv(io.BytesIO(z.read(name)), header=None, names=COLS)
    if not np.issubdtype(df["open_time"].dtype, np.number):  # header row present
        df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()].astype({"open_time": "int64"})
    t = df["open_time"].astype("int64")
    unit = "us" if t.iloc[0] > 1e14 else "ms"   # Binance switched to microseconds in 2025
    df.index = pd.to_datetime(t, unit=unit, utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def load_1m(refresh: bool = False, source: str | None = None) -> pd.DataFrame:
    """1-minute BTC/USD bars.  Source (env AMS_DATA): 'bitstamp' (default, real USD
    market), 'mt5' (data/mt5_btcusd_m1.csv exported from the broker terminal) or
    'binance' (BTCUSDT proxy used in the first research round)."""
    source = source or os.environ.get("AMS_DATA", "bitstamp")
    if source == "bitstamp":
        path = os.path.join(ROOT, "data", "bitstamp_btcusd_1m.parquet")
        if not os.path.exists(path):          # merge parallel download parts
            parts = sorted(glob.glob(os.path.join(ROOT, "data", "parts", "part_*.parquet")))
            df = pd.concat([pd.read_parquet(p) for p in parts]).sort_index()
            df = df[~df.index.duplicated()]
            df.to_parquet(path)
        return pd.read_parquet(path)
    if source == "mt5":
        p = os.path.join(ROOT, "data", "mt5_btcusd_m1.csv.gz")
        return load_mt5_csv(p if os.path.exists(p) else p[:-3])
    if os.path.exists(CACHE) and not refresh:
        return pd.read_parquet(CACHE)
    files = sorted(glob.glob(os.path.join(RAW, "BTCUSDT-1m-*.zip")))
    df = pd.concat([_read_zip(f) for f in files])
    df = df[~df.index.duplicated()].sort_index()
    df.index.name = "time"
    df.to_parquet(CACHE)
    return df


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return df
    r = df.resample(f"{minutes}min", label="left", closed="left")
    out = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                        "low": r["low"].min(), "close": r["close"].last(),
                        "volume": r["volume"].sum()}).dropna()
    return out


def load_mt5_csv(path: str) -> pd.DataFrame:
    """Load M1 bars written by mt5/export_btcusd.py.  MT5 bars are BID prices; we
    convert to mid using each bar's spread (in points) so the engine can add the
    modelled spread symmetrically."""
    df = pd.read_csv(path)
    idx = pd.to_datetime(df["time"], unit="s", utc=True)
    spec = os.path.join(os.path.dirname(path), "mt5_symbol_spec.json")
    point = float(json.load(open(spec))["point"]) if os.path.exists(spec) else 0.01
    half = df["spread"].astype(float) * point / 2 if "spread" in df else 0.0
    out = pd.DataFrame({"open": df["open"] + half, "high": df["high"] + half,
                        "low": df["low"] + half, "close": df["close"] + half,
                        "volume": df.get("tick_volume", df.get("real_volume", 0)).astype(float)}).set_index(idx)
    out.index.name = "time"
    return out[~out.index.duplicated()].sort_index()
