"""Market-relative sessions, new instruments and the basket evaluator."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scalping import backtest as bt, basket as B
from scalping.instruments import INDICES5, STOCKS7, get_instrument
from scalping.strategy import StrategyParams, compute_signals, session_hours


def test_market_sessions_resolve_per_exchange():
    assert session_hours("cash_open", "US") == (13, 16)
    assert session_hours("cash_open", "EU") == (7, 10)
    assert session_hours("london") == (7, 12)
    assert {get_instrument(s).market for s in INDICES5} == {"US", "EU"}
    assert {get_instrument(s).market for s in STOCKS7} == {"US"}


def _bars(n=6000, seed=3, start="2024-03-04 07:00"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0002,
                         "low": np.minimum(o, c) * 0.9998, "close": c, "volume": 1.0}, index=idx)


def test_eu_index_only_signals_in_eu_hours():
    bars = _bars()
    p = StrategyParams(mode="momentum", tf_minutes=1, session="cash_open", mom_min_atr=0.1,
                       mom_confirm=0, atr_rank_min=0.0, atr_rank_max=1.0)
    sig = compute_signals(bars, p, get_instrument("GER40"))
    hrs = sig.index[sig.direction != 0].hour
    assert len(hrs) and hrs.min() >= 7 and hrs.max() < 10


def test_basket_pools_trades_from_every_symbol():
    preps = {s: bt.prepare(_bars(seed=i), s) for i, s in enumerate(["AAPL", "MSFT"])}
    basket = B.Basket(preps)
    s = StrategyParams(mode="momentum", tf_minutes=5, session="cash", mom_min_atr=0.5,
                       mom_confirm=0, atr_rank_min=0.0, atr_rank_max=1.0, sl_atr=1.0, tp_r=1.0)
    e = bt.exec_config_from(get_instrument("AAPL"), max_bars=30, force_exit_hour=19, force_exit_min=55)
    m, tr = basket.run(s, e)
    assert m.n_trades == len(tr) > 0
    assert set(tr.symbol) <= {"AAPL", "MSFT"}
    assert tr.entry_time.is_monotonic_increasing
