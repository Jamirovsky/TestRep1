"""Loading, cleaning and resampling of OHLC bar data.

The loader auto-detects the four formats a retail trader is most likely to have
on disk, so you can drop an export straight into ``data/raw/`` and run:

  * **MetaTrader 5** bar export  ``<DATE>\\t<TIME>\\t<OPEN>\\t...``
  * **HistData.com** ASCII M1    ``YYYYMMDD HHMMSS;O;H;L;C;V``
  * **Dukascopy** CSV            ``Gmt time,Open,High,Low,Close,Volume``
  * **generic**                  ``datetime,open,high,low,close[,volume,spread]``

Everything is normalised to a tz-aware UTC index with float64 OHLC columns.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd

OHLC = ["open", "high", "low", "close"]


def epoch_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    """UTC seconds since the epoch, independent of the index's time resolution.

    pandas 3 defaults DatetimeIndex to microsecond resolution while pandas 2
    used nanoseconds, so any ``view("int64") // 1e9`` arithmetic is silently
    wrong on one of them.  Everything that needs integer time goes through here.
    """
    naive = index.tz_convert("UTC").tz_localize(None) if index.tz is not None else index
    return naive.to_numpy().astype("datetime64[s]").astype("int64")


@dataclass
class DataQuality:
    """Summary of what the cleaner found, printed before every backtest."""

    rows_in: int
    rows_out: int
    duplicates: int
    non_monotonic: int
    invalid_ohlc: int
    zero_range: int
    first: Optional[pd.Timestamp]
    last: Optional[pd.Timestamp]
    trading_days: int
    median_gap_s: float
    largest_gap_h: float

    def __str__(self) -> str:
        span = "-"
        if self.first is not None and self.last is not None:
            span = f"{self.first:%Y-%m-%d} -> {self.last:%Y-%m-%d}"
        return (
            f"rows {self.rows_in} -> {self.rows_out} | {span} | "
            f"{self.trading_days} trading days | dupes {self.duplicates} | "
            f"bad-ohlc {self.invalid_ohlc} | flat {self.zero_range} | "
            f"median gap {self.median_gap_s:.0f}s | max gap {self.largest_gap_h:.1f}h"
        )


# ---------------------------------------------------------------------------
# format sniffing
# ---------------------------------------------------------------------------
def _sniff(sample: str) -> str:
    head = sample.lstrip("﻿").splitlines()
    first = head[0] if head else ""
    if "<DATE>" in first.upper() or "<OPEN>" in first.upper():
        return "mt5"
    if ";" in first and re.match(r"^\s*\d{8}\s+\d{6};", first):
        return "histdata"
    low = first.lower()
    if "gmt time" in low:
        return "dukascopy"
    return "generic"


def _read_mt5(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    if "date" in df.columns and "time" in df.columns:
        ts = df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip()
        idx = pd.to_datetime(ts.str.replace(".", "-", regex=False), format="mixed")
    else:
        idx = pd.to_datetime(df.iloc[:, 0], format="mixed")
    out = pd.DataFrame(index=pd.DatetimeIndex(idx))
    for c in OHLC:
        out[c] = pd.to_numeric(df[c], errors="coerce").to_numpy()
    vol_col = "tickvol" if "tickvol" in df.columns else ("vol" if "vol" in df.columns else None)
    out["volume"] = pd.to_numeric(df[vol_col], errors="coerce").to_numpy() if vol_col else 0.0
    if "spread" in df.columns:
        out["spread"] = pd.to_numeric(df["spread"], errors="coerce").to_numpy()
    return out


def _read_histdata(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path, sep=";", header=None,
        names=["ts", "open", "high", "low", "close", "volume"],
    )
    idx = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    out = df[OHLC + ["volume"]].astype("float64")
    out.index = pd.DatetimeIndex(idx)
    return out


def _read_dukascopy(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(c for c in df.columns if "time" in c or "date" in c)
    idx = pd.to_datetime(df[tcol], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce")
    if idx.isna().all():
        idx = pd.to_datetime(df[tcol], format="mixed")
    out = pd.DataFrame(index=pd.DatetimeIndex(idx))
    for c in OHLC:
        out[c] = pd.to_numeric(df[c], errors="coerce").to_numpy()
    out["volume"] = pd.to_numeric(df.get("volume", 0.0), errors="coerce").to_numpy()
    return out


def _read_generic(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(
        (c for c in df.columns if c in ("datetime", "date", "time", "timestamp", "ts")),
        df.columns[0],
    )
    idx = pd.to_datetime(df[tcol], format="mixed", errors="coerce")
    out = pd.DataFrame(index=pd.DatetimeIndex(idx))
    for c in OHLC:
        match = next((k for k in df.columns if k.startswith(c)), None)
        if match is None:
            raise ValueError(f"{path.name}: no column for {c!r} (found {list(df.columns)})")
        out[c] = pd.to_numeric(df[match], errors="coerce").to_numpy()
    out["volume"] = pd.to_numeric(df.get("volume", 0.0), errors="coerce").to_numpy()
    if "spread" in df.columns:
        out["spread"] = pd.to_numeric(df["spread"], errors="coerce").to_numpy()
    return out


_READERS = {
    "mt5": _read_mt5,
    "histdata": _read_histdata,
    "dukascopy": _read_dukascopy,
    "generic": _read_generic,
}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def load_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    """Load one CSV of bars, auto-detecting the vendor format."""
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(4096)
    kind = _sniff(sample)
    df = _READERS[kind](path)
    df = df[~df.index.isna()]
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    df.index = df.index.tz_convert("UTC")
    df.index.name = "time"
    df.attrs["source_format"] = kind
    df.attrs["source_file"] = path.name
    return df


def load_dir(directory: str | Path, pattern: str = "*.csv", tz: str = "UTC") -> pd.DataFrame:
    """Load and concatenate every matching CSV in a directory."""
    directory = Path(directory)
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no files matching {pattern!r} in {directory}")
    frames = [load_csv(f, tz=tz) for f in files]
    df = pd.concat(frames).sort_index()
    df.attrs["source_files"] = [f.name for f in files]
    return df


def clean(df: pd.DataFrame, drop_weekends: bool = True) -> tuple[pd.DataFrame, DataQuality]:
    """Remove duplicates, impossible bars and weekend rows; report what happened."""
    rows_in = len(df)
    non_monotonic = int((df.index.to_series().diff().dropna() <= pd.Timedelta(0)).sum())

    df = df.sort_index()
    dup_mask = df.index.duplicated(keep="last")
    duplicates = int(dup_mask.sum())
    df = df[~dup_mask]

    o, h, l, c = (df[k].to_numpy(dtype="float64") for k in OHLC)
    finite = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
    consistent = (h >= l) & (h >= np.maximum(o, c) - 1e-12) & (l <= np.minimum(o, c) + 1e-12)
    positive = (o > 0) & (h > 0) & (l > 0) & (c > 0)
    ok = finite & consistent & positive
    invalid_ohlc = int((~ok).sum())
    df = df[ok]

    zero_range = int((df["high"].to_numpy() == df["low"].to_numpy()).sum())

    if drop_weekends and len(df):
        dow, hour = df.index.dayofweek, df.index.hour
        # FX week: Friday 21:00 UTC close -> Sunday 21:00 UTC open.
        weekend = (dow == 5) | ((dow == 4) & (hour >= 21)) | ((dow == 6) & (hour < 21))
        df = df[~weekend]

    if len(df) > 1:
        deltas = df.index.to_series().diff().dropna().dt.total_seconds().to_numpy()
        median_gap = float(np.median(deltas))
        largest_gap = float(np.max(deltas)) / 3600.0
    else:
        median_gap, largest_gap = float("nan"), float("nan")

    q = DataQuality(
        rows_in=rows_in,
        rows_out=len(df),
        duplicates=duplicates,
        non_monotonic=non_monotonic,
        invalid_ohlc=invalid_ohlc,
        zero_range=zero_range,
        first=df.index[0] if len(df) else None,
        last=df.index[-1] if len(df) else None,
        trading_days=int(df.index.normalize().nunique()) if len(df) else 0,
        median_gap_s=median_gap,
        largest_gap_h=largest_gap,
    )
    return df, q


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate bars to a higher timeframe (left-closed, left-labelled)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    if "spread" in df.columns:
        agg["spread"] = "mean"
    out = df.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna(subset=OHLC)


def align_signal_to_exec(signal_index: pd.DatetimeIndex, exec_index: pd.DatetimeIndex) -> np.ndarray:
    """Map each higher-timeframe bar to the execution bar that may act on it.

    A signal produced by the bar *closing* at ``t + tf`` can only be traded from
    the first execution bar at or after ``t + tf``.  Returns, for every entry in
    ``signal_index``, the integer position in ``exec_index`` of that bar (or -1).
    This is the single place where look-ahead bias is prevented.
    """
    pos = np.searchsorted(exec_index.to_numpy(), signal_index.to_numpy(), side="left")
    pos = np.where(pos >= len(exec_index), -1, pos)
    return pos.astype(np.int64)
