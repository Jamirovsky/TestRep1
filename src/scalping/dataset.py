"""Where bars come from: real CSVs when you have them, synthetic when you don't.

Drop broker exports in ``data/raw/<SYMBOL>/`` and every script in this repo
switches to them automatically -- nothing else needs changing.  See
``data/README.md`` for how to produce those files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from . import data as D
from . import synth

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"


@dataclass
class Dataset:
    symbol: str
    bars: pd.DataFrame
    is_synthetic: bool
    quality: D.DataQuality
    source: str

    def banner(self) -> str:
        tag = "SYNTHETIC (engine validation only)" if self.is_synthetic else "REAL"
        return f"[{self.symbol}] {tag} | source: {self.source}\n          {self.quality}"


def have_real(symbol: str) -> bool:
    d = RAW / symbol.upper()
    return d.is_dir() and (any(d.glob("*.csv")) or any(d.glob("*.parquet")))


def _load_parquet_dir(symbol: str) -> pd.DataFrame:
    """OANDA-style monthly parquet chunks (``scripts/fetch_metals.py``).

    Columns ``time`` (epoch seconds, bar open, UTC), ``open/high/low/close``
    (mid prices) and ``volume`` (tick count).  The merged result is cached,
    keyed on the file list, because 90-odd parquet reads add up.
    """
    files = sorted((RAW / symbol).glob("*.parquet"))
    CACHE.mkdir(parents=True, exist_ok=True)
    key = f"{len(files)}_{files[0].stem[-23:]}_{files[-1].stem[-23:]}".replace(" ", "")
    cache_file = CACHE / f"{symbol}_real_{key}.parquet"
    if cache_file.exists():
        return pd.read_parquet(cache_file)
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        if "time" in df.columns:
            idx = pd.to_datetime(df["time"].astype("int64"), unit="s", utc=True)
            df = df.drop(columns=["time"])
            df.index = idx
        df.index.name = "time"
        frames.append(df[[c for c in ("open", "high", "low", "close", "volume", "spread")
                          if c in df.columns]].astype("float64"))
    out = pd.concat(frames).sort_index()
    out.to_parquet(cache_file)
    return out


def load(
    symbol: str,
    start: str = "2019-01-02",
    end: str = "2025-12-31",
    seed: int = 7,
    use_cache: bool = True,
    prefer_real: bool = True,
) -> Dataset:
    symbol = symbol.upper()
    if prefer_real and have_real(symbol):
        if any((RAW / symbol).glob("*.csv")):
            raw, src = D.load_dir(RAW / symbol, "*.csv"), f"data/raw/{symbol}/*.csv"
        else:
            raw, src = _load_parquet_dir(symbol), f"data/raw/{symbol}/*.parquet"
        bars, q = D.clean(raw)
        bars = bars.loc[str(start) : str(end)]
        return Dataset(symbol, bars, False, q, src)

    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"{symbol}_synth_{seed}_{start}_{end}.parquet"
    if use_cache and cache_file.exists():
        bars = pd.read_parquet(cache_file)
        bars, q = D.clean(bars)
        return Dataset(symbol, bars, True, q, f"cache/{cache_file.name}")

    cfg = synth.preset(symbol, seed=seed, start=start, end=end)
    bars = synth.generate(cfg)
    if use_cache:
        bars.to_parquet(cache_file)
    bars, q = D.clean(bars)
    return Dataset(symbol, bars, True, q, f"synthetic seed={seed}")
