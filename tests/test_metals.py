"""Tests for the minor-metals additions: price-scaled costs, bp stop floor,
the rolling-band fade, and the search spaces."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scalping import spaces
from scalping.engine import run_backtest
from scalping.instruments import get_instrument
from scalping.strategy import MODE_BANDS, StrategyParams, compute_signals, cost_scale_series

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engine import flat_cfg, make_bars, one_signal  # noqa: E402


def test_slippage_scales_with_cost_scale():
    """Entry slippage is paid in points x cost_scale: doubling the scale doubles it."""
    inst = get_instrument("XPTUSD")
    bars = make_bars([(1000.0, 1000.0, 1000.0, 1000.0)] * 6)
    sig = one_signal(len(bars), 1, +1, 10.0, 0.0)
    cfg = flat_cfg(inst, slippage_points_entry=20.0, max_bars=2)
    zero = np.zeros(len(bars))
    r1 = run_backtest(bars, sig, cfg, zero, np.ones(len(bars))).trades_frame()
    r2 = run_backtest(bars, sig, cfg, zero, np.full(len(bars), 2.0)).trades_frame()
    loss1 = r1["entry_price"].iloc[0] - 1000.0
    loss2 = r2["entry_price"].iloc[0] - 1000.0
    assert np.isclose(loss1, 20 * inst.point)
    assert np.isclose(loss2, 2 * loss1)


def test_cost_scale_tracks_price_for_bp_instruments():
    bars = make_bars([(15.0, 15.0, 15.0, 15.0), (60.0, 60.0, 60.0, 60.0)])
    cs = cost_scale_series(bars, get_instrument("XAGUSD"))
    assert np.allclose(cs, [0.5, 2.0])                       # ref_price = 30
    assert np.allclose(cost_scale_series(bars, get_instrument("EURUSD")), 1.0)


def _random_walk(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    c = 1000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + 0.0005)
    l = np.minimum(o, c) * (1 - 0.0005)
    idx = pd.date_range("2024-01-01 07:00", periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1.0}, index=idx)


def test_bands_mode_is_causal():
    """Signals on a prefix of the data must equal the same rows on the full data."""
    bars = _random_walk()
    p = spaces.apply_fixed(StrategyParams(mode=MODE_BANDS, tf_minutes=30, session="extended",
                                          band_k=1.5, rsi_lo=35, adx_max=100, confirm_mode=2))
    inst = get_instrument("XPDUSD")
    full = compute_signals(bars, p, inst)
    cut = 2000
    part = compute_signals(bars.iloc[:cut], p, inst)
    assert (full["direction"].iloc[:cut].to_numpy() == part["direction"].to_numpy()).all()
    assert (full["direction"] != 0).sum() > 0


def test_min_sl_bp_floor_applies():
    bars = _random_walk()
    p = StrategyParams(mode=MODE_BANDS, session="extended", sl_atr=0.01, min_sl_bp=100,
                       band_k=1.0, rsi_lo=45, rsi_hi=55, adx_max=100, confirm_mode=0)
    out = compute_signals(bars, p, get_instrument("XPTUSD"))
    sl = out["sl_distance"].to_numpy()
    ok = np.isfinite(sl) & (sl > 0)
    assert np.allclose(sl[ok], 0.01 * bars["close"].to_numpy()[ok])


def test_metals_space_pins_timeframe_and_uses_bp_floor():
    for sym in ("XAGUSD", "XPTUSD", "XPDUSD"):
        for variant in ("base", "selective"):
            sp = spaces.space_for("momentum", sym, 5, variant)
            assert sp["s.tf_minutes"] == [5]
            assert "s.min_sl_bp" in sp and "s.min_sl_points" not in sp
