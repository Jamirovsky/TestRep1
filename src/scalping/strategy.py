"""Signal generation for the two scalping engines.

Two families, both parameterised, both available to both symbols -- the
optimiser decides which one each instrument actually gets.

**VWAP fade (mean reversion).**  Intraday FX and gold spend most of their time
oscillating around a volume-weighted fair value while dealers work inventory.
When price is stretched a long way from the session VWAP, momentum is
exhausted (RSI), the move is not part of a strong directional trend (ADX low)
and volatility is in a normal regime, the reversion back toward VWAP is the
highest-probability short-horizon move available.  High hit rate, modest R.

**Momentum breakout.**  The counterpart regime: when volatility expands and the
higher-timeframe trend is aligned, a break of the recent range continues rather
than reverts.  Lower hit rate, larger R.

THE LOOK-AHEAD BARRIER
----------------------
Indicators are computed on closed signal-timeframe bars.  A bar *labelled* ``t``
covers ``[t, t + tf)`` and is only known at ``t + tf``.  ``to_exec_signals``
therefore places the signal on the execution bar at ``t + tf`` and the engine
fills it at that bar's open.  Nothing else in the codebase is allowed to move a
signal earlier.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from . import indicators as ind
from .data import epoch_seconds
from .instruments import Instrument

MODE_FADE = "fade"
MODE_BREAKOUT = "breakout"
MODE_PULLBACK = "pullback"
MODE_MOMENTUM = "momentum"

# UTC hour windows, end-exclusive.  Rollover (21:00) is excluded everywhere.
SESSION_PRESETS: Dict[str, Tuple[int, int]] = {
    "london": (7, 12),
    "ny": (12, 18),
    "overlap": (13, 17),
    "london_ny": (7, 18),
    "london_early": (7, 10),
    "ny_early": (13, 16),
    "extended": (6, 20),
}


@dataclass
class Signals:
    """Per-execution-bar instructions handed to the engine."""

    direction: np.ndarray     # int64, -1 / 0 / +1
    sl_distance: np.ndarray   # float64, price units
    tp_distance: np.ndarray   # float64, price units (0 = no fixed target)


@dataclass
class StrategyParams:
    mode: str = MODE_FADE
    tf_minutes: int = 5
    session: str = "london_ny"

    # --- shared ---------------------------------------------------------
    atr_period: int = 14
    atr_rank_lookback: int = 288      # ~1 trading day of M5 bars
    atr_rank_min: float = 0.15
    atr_rank_max: float = 0.95
    sl_atr: float = 1.2               # stop distance = sl_atr * ATR
    tp_r: float = 1.5                 # target = tp_r * stop distance
    min_sl_points: float = 0.0        # floor so costs stay a small % of risk
    allow_long: bool = True
    allow_short: bool = True
    # Efficiency-Ratio gate, shared by every continuation mode.  This is the
    # filter that decides whether the market is in a state where paying the
    # spread for a directional bet is justified at all.
    er_period: int = 24
    er_min: float = 0.0               # 0 = lower gate disabled
    er_max: float = 1.0               # < 1 demands CHOP, which is what a fade wants

    # --- fade -----------------------------------------------------------
    vwap_anchor_hour: int = 0
    band_k: float = 2.0               # entry at band_k session sigmas from VWAP
    rsi_period: int = 7
    rsi_lo: float = 28.0
    rsi_hi: float = 72.0
    adx_period: int = 14
    adx_max: float = 30.0
    # 0 = none, 1 = rejection candle, 2 = close beyond prior close,
    # 3 = close beyond prior high/low.  Modes 2 and 3 test the stretch on the
    # PREVIOUS bar and enter on the turn, which is what actually makes a fade
    # tradable -- demanding a bullish candle on the same bar that prints an
    # RSI extreme is close to self-contradictory.
    confirm_mode: int = 2
    min_dev_atr: float = 0.0          # minimum |price - VWAP| in ATRs (0 = off)

    # --- breakout -------------------------------------------------------
    don_period: int = 24
    ema_fast: int = 12
    ema_slow: int = 48
    adx_min: float = 20.0
    expansion_mult: float = 1.15      # ATR / ATR-average must exceed this
    atr_avg_period: int = 48          # denominator of the expansion test

    # --- pullback -------------------------------------------------------
    # Trend continuation after a shallow retracement: the highest-hit-rate
    # structure of the three, because entry is *with* the dominant flow and
    # the stop sits behind the retracement low rather than at an arbitrary
    # ATR distance.
    pb_slope_period: int = 30         # EMA-slope window defining the trend
    pb_rsi_lo: float = 40.0           # long: RSI must dip to here...
    pb_rsi_hi: float = 60.0           # short: ...or rise to here
    pb_depth_atr: float = 0.5         # minimum retracement depth, in ATR
    pb_lookback: int = 6              # bars the retracement may span

    # --- momentum -------------------------------------------------------
    # The most direct expression of trend persistence: take the sign of the
    # move over ``mom_period`` bars, but only when the Efficiency Ratio says
    # the move is directional rather than noise, and only on a continuation
    # tick so we are not buying the exact top of an exhausted push.
    mom_period: int = 24
    mom_min_atr: float = 1.0          # net move must be at least this many ATR
    mom_confirm: int = 1              # 1 = require close beyond prior bar extreme

    def to_dict(self) -> Dict:
        return asdict(self)


def _session_id(index: pd.DatetimeIndex, anchor_hour: int) -> np.ndarray:
    """Integer that increments at ``anchor_hour`` UTC -- the VWAP anchor."""
    return ((epoch_seconds(index) - anchor_hour * 3600) // 86_400).astype(np.int64)


def _hours_mask(index: pd.DatetimeIndex, session: str) -> np.ndarray:
    lo, hi = SESSION_PRESETS[session]
    h = index.hour.to_numpy()
    return (h >= lo) & (h < hi) & (h != 21)


def compute_signals(sig_bars: pd.DataFrame, p: StrategyParams, inst: Instrument) -> pd.DataFrame:
    """Return a frame on the signal timeframe with direction / sl / tp columns."""
    o = sig_bars["open"].to_numpy(dtype="float64")
    h = sig_bars["high"].to_numpy(dtype="float64")
    l = sig_bars["low"].to_numpy(dtype="float64")
    c = sig_bars["close"].to_numpy(dtype="float64")
    v = sig_bars["volume"].to_numpy(dtype="float64") if "volume" in sig_bars else np.ones_like(c)
    n = len(c)

    a = ind.atr(h, l, c, p.atr_period)
    a_rank = ind.rolling_rank(a, p.atr_rank_lookback)
    ok_vol = (a_rank >= p.atr_rank_min) & (a_rank <= p.atr_rank_max)
    ok_hours = _hours_mask(sig_bars.index, p.session)
    valid = np.isfinite(a) & (a > 0) & ok_vol & ok_hours
    if p.er_min > 0.0 or p.er_max < 1.0:
        er = ind.efficiency_ratio(c, p.er_period)
        valid = valid & np.isfinite(er) & (er >= p.er_min) & (er <= p.er_max)

    long_sig = np.zeros(n, dtype=bool)
    short_sig = np.zeros(n, dtype=bool)

    if p.mode == MODE_FADE:
        sid = _session_id(sig_bars.index, p.vwap_anchor_hour)
        vwap, vsig = ind.session_vwap(h, l, c, v, sid)
        r = ind.rsi(c, p.rsi_period)
        adx_v = ind.adx(h, l, c, p.adx_period)

        with np.errstate(invalid="ignore", divide="ignore"):
            dev = c - vwap
            z = np.where(vsig > 0, dev / vsig, 0.0)

        far = np.abs(dev) >= p.min_dev_atr * a if p.min_dev_atr > 0 else np.ones(n, dtype=bool)
        calm = np.isfinite(adx_v) & (adx_v <= p.adx_max)
        stretched_dn = (z <= -p.band_k) & (r <= p.rsi_lo) & far & calm & np.isfinite(vwap)
        stretched_up = (z >= p.band_k) & (r >= p.rsi_hi) & far & calm & np.isfinite(vwap)

        prev_c = np.roll(c, 1); prev_c[0] = np.nan
        prev_h = np.roll(h, 1); prev_h[0] = np.nan
        prev_l = np.roll(l, 1); prev_l[0] = np.nan
        prev_dn = np.roll(stretched_dn, 1); prev_dn[0] = False
        prev_up = np.roll(stretched_up, 1); prev_up[0] = False
        rng = np.maximum(h - l, 1e-12)

        if p.confirm_mode == 0:
            trig_long, trig_short = stretched_dn, stretched_up
        elif p.confirm_mode == 1:
            # rejection: the bar prints the extreme but closes in the far half
            trig_long = stretched_dn & (c >= l + 0.5 * rng)
            trig_short = stretched_up & (c <= h - 0.5 * rng)
        elif p.confirm_mode == 2:
            trig_long = prev_dn & (c > prev_c)
            trig_short = prev_up & (c < prev_c)
        elif p.confirm_mode == 3:
            trig_long = prev_dn & (c > prev_h)
            trig_short = prev_up & (c < prev_l)
        else:
            raise ValueError(f"unknown confirm_mode {p.confirm_mode!r}")

        long_sig = valid & trig_long
        short_sig = valid & trig_short

    elif p.mode == MODE_BREAKOUT:
        prior_hi = np.roll(ind.highest(h, p.don_period), 1)
        prior_lo = np.roll(ind.lowest(l, p.don_period), 1)
        prior_hi[0] = np.nan
        prior_lo[0] = np.nan
        ef = ind.ema(c, p.ema_fast)
        es = ind.ema(c, p.ema_slow)
        adx_v = ind.adx(h, l, c, p.adx_period)
        a_avg = ind.sma(a, p.atr_avg_period)
        with np.errstate(invalid="ignore", divide="ignore"):
            expanding = np.isfinite(a_avg) & (a_avg > 0) & (a / a_avg >= p.expansion_mult)
        trending = np.isfinite(adx_v) & (adx_v >= p.adx_min)

        long_sig = valid & (c > prior_hi) & (ef > es) & expanding & trending & np.isfinite(prior_hi)
        short_sig = valid & (c < prior_lo) & (ef < es) & expanding & trending & np.isfinite(prior_lo)
    elif p.mode == MODE_PULLBACK:
        ef = ind.ema(c, p.ema_fast)
        es = ind.ema(c, p.ema_slow)
        slope = ind.linreg_slope(es, p.pb_slope_period)
        r = ind.rsi(c, p.rsi_period)
        adx_v = ind.adx(h, l, c, p.adx_period)
        trending = np.isfinite(adx_v) & (adx_v >= p.adx_min)

        up = (ef > es) & np.isfinite(slope) & (slope > 0)
        dn = (ef < es) & np.isfinite(slope) & (slope < 0)

        # the retracement itself: a recent dip toward / through the fast EMA
        swing_lo = ind.lowest(l, p.pb_lookback)
        swing_hi = ind.highest(h, p.pb_lookback)
        deep_enough_dn = (ef - swing_lo) >= p.pb_depth_atr * a
        deep_enough_up = (swing_hi - ef) >= p.pb_depth_atr * a

        prev_h = np.roll(h, 1); prev_h[0] = np.nan
        prev_l = np.roll(l, 1); prev_l[0] = np.nan
        dipped_dn = np.roll(r <= p.pb_rsi_lo, 1); dipped_dn[0] = False
        dipped_up = np.roll(r >= p.pb_rsi_hi, 1); dipped_up[0] = False

        long_sig = valid & up & trending & deep_enough_dn & dipped_dn & (c > prev_h)
        short_sig = valid & dn & trending & deep_enough_up & dipped_up & (c < prev_l)

    elif p.mode == MODE_MOMENTUM:
        prev_c = np.roll(c, p.mom_period)
        prev_c[: p.mom_period] = np.nan
        net = c - prev_c
        big = np.isfinite(net) & (np.abs(net) >= p.mom_min_atr * a)

        prev_h = np.roll(h, 1); prev_h[0] = np.nan
        prev_l = np.roll(l, 1); prev_l[0] = np.nan
        if p.mom_confirm:
            cont_up = c > prev_h
            cont_dn = c < prev_l
        else:
            cont_up = np.ones(n, dtype=bool)
            cont_dn = np.ones(n, dtype=bool)

        long_sig = valid & big & (net > 0) & cont_up
        short_sig = valid & big & (net < 0) & cont_dn

    else:
        raise ValueError(f"unknown mode {p.mode!r}")

    if not p.allow_long:
        long_sig[:] = False
    if not p.allow_short:
        short_sig[:] = False

    direction = np.where(long_sig, 1, np.where(short_sig, -1, 0)).astype(np.int64)

    sl = p.sl_atr * a
    floor_price = p.min_sl_points * inst.point
    sl = np.where(np.isfinite(sl), np.maximum(sl, floor_price), 0.0)
    tp = p.tp_r * sl

    out = pd.DataFrame(
        {"direction": direction, "sl_distance": sl, "tp_distance": tp, "atr": a},
        index=sig_bars.index,
    )
    out.loc[~np.isfinite(out["sl_distance"]) | (out["sl_distance"] <= 0), "direction"] = 0
    return out


def to_exec_signals(
    sig_frame: pd.DataFrame, exec_index: pd.DatetimeIndex, tf_minutes: int
) -> Signals:
    """Project signal-timeframe decisions onto execution bars, one timeframe late.

    This is the look-ahead barrier: a bar labelled ``t`` closes at ``t + tf``, so
    the earliest execution bar that may act on it is the one at ``t + tf``.
    """
    n = len(exec_index)
    direction = np.zeros(n, dtype=np.int64)
    sl = np.zeros(n, dtype="float64")
    tp = np.zeros(n, dtype="float64")

    active = sig_frame["direction"].to_numpy() != 0
    if not active.any():
        return Signals(direction, sl, tp)

    fire_times = sig_frame.index[active] + pd.Timedelta(minutes=tf_minutes)
    exec_s = epoch_seconds(exec_index)
    fire_s = epoch_seconds(fire_times)
    pos = np.searchsorted(exec_s, fire_s, side="left")
    keep = pos < n
    pos = pos[keep]
    # Only act if the execution bar is the one the signal bar actually closed on;
    # a long gap (weekend, data hole) must not resurrect a stale signal.
    stale = (exec_s[pos] - fire_s[keep]) > tf_minutes * 60
    pos = pos[~stale]

    d = sig_frame["direction"].to_numpy()[active][keep][~stale]
    s = sig_frame["sl_distance"].to_numpy()[active][keep][~stale]
    t = sig_frame["tp_distance"].to_numpy()[active][keep][~stale]

    direction[pos] = d
    sl[pos] = s
    tp[pos] = t
    return Signals(direction, sl, tp)


def spread_series(exec_index: pd.DatetimeIndex, bars: pd.DataFrame, inst: Instrument) -> np.ndarray:
    """Per-bar spread in points: broker's own column when present, else modelled."""
    if "spread" in bars.columns and bars["spread"].notna().any():
        s = bars["spread"].to_numpy(dtype="float64")
        return np.where(np.isfinite(s) & (s > 0), s, inst.spread_base_points)

    h = exec_index.hour.to_numpy()
    tr = ind.true_range(
        bars["high"].to_numpy("float64"),
        bars["low"].to_numpy("float64"),
        bars["close"].to_numpy("float64"),
    )
    tr_avg = ind.sma(tr, 240)
    with np.errstate(invalid="ignore", divide="ignore"):
        vol_z = np.where(np.isfinite(tr_avg) & (tr_avg > 0), tr / tr_avg - 1.0, 0.0)
    vol_z = np.clip(np.nan_to_num(vol_z), 0.0, 4.0)

    base = np.full(len(exec_index), inst.spread_base_points, dtype="float64")
    asia = (h >= 22) | (h < 6)
    base[asia] *= inst.spread_asia_mult
    base[h == 21] *= inst.spread_rollover_mult
    base += inst.spread_vol_coeff * vol_z * inst.spread_base_points
    return np.minimum(base, inst.spread_max_points)
