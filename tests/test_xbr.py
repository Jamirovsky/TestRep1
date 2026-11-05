"""XBRUSD families (orb / rsi2 / sweep): no look-ahead, sane signals."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scalping.instruments import get_instrument
from scalping.strategy import StrategyParams, compute_signals


def _walk(n=8000, seed=11):
    rng = np.random.default_rng(seed)
    c = 80 * np.exp(np.cumsum(rng.normal(0, 0.0012, n)))
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range("2024-03-04 00:00", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0008,
                         "low": np.minimum(o, c) * 0.9992, "close": c, "volume": 1.0}, index=idx)


@pytest.mark.parametrize("params", [
    dict(mode="orb", orb_hour=7, orb_bars=4),
    dict(mode="orb", orb_hour=13, orb_bars=2, orb_fade=1),
    dict(mode="rsi2", r2_period=2, r2_lo=10, trend_ema=50),
    dict(mode="sweep", sweep_lookback=24, sweep_wick_atr=0.2),
])
def test_new_families_are_causal(params):
    bars = _walk()
    p = StrategyParams(tf_minutes=15, session="extended", atr_rank_min=0.0, atr_rank_max=1.0, **params)
    inst = get_instrument("XBRUSD")
    full = compute_signals(bars, p, inst)["direction"].to_numpy()
    for cut in (3001, 5555):
        part = compute_signals(bars.iloc[:cut], p, inst)["direction"].to_numpy()
        assert (full[:cut] == part).all()
    assert (full != 0).sum() > 5


def test_orb_trades_at_most_once_per_day_per_side():
    bars = _walk()
    p = StrategyParams(mode="orb", tf_minutes=15, session="extended", orb_hour=7, orb_bars=4,
                       atr_rank_min=0.0, atr_rank_max=1.0)
    sig = compute_signals(bars, p, get_instrument("XBRUSD"))
    d = sig[sig.direction != 0]
    per_day = d.groupby([d.index.date, d.direction]).size()
    assert per_day.max() == 1
    assert (d.index.hour >= 8).all()          # never inside the 07:00-08:00 range itself
