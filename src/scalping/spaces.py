"""Search spaces, one per strategy mode.

DELIBERATELY SMALL, and it got smaller after measurement.

The first version of this file searched 10^11 combinations across 23 free
parameters.  Picking the single best of 400 random draws from that space
produced in-sample profit factors around 1.35 that collapsed to 0.66 out of
sample -- the search was fitting the sample, not the market.  The fix was not a
better optimiser, it was fewer knobs: anything that measurement showed was not
decisive is now fixed at a sensible default instead of being searched.

Two rules kept here:

* **Coarse, log-spaced values.**  Neighbouring settings must be genuinely
  different regimes, otherwise the neighbourhood-stability check is measuring
  rounding noise.
* **No redundant parameters.**  ``ema_fast``/``ema_slow``/``atr_period`` and
  friends are fixed, because varying them mostly re-expresses what the
  Efficiency-Ratio gate and the ATR stop already control.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from .strategy import MODE_BREAKOUT, MODE_FADE, MODE_MOMENTUM, MODE_PULLBACK

# Minimum stop distance in points, per symbol.  The single most important
# parameter in the system: round-trip friction is ~15.5 points on EURUSD and
# ~45 on XAUUSD, so a stop below these floors hands 15-40% of the risked amount
# straight to the broker before the strategy has done anything.
MIN_SL_POINTS: Dict[str, List[float]] = {
    "EURUSD": [80, 120, 160, 220, 300],        # 8 - 30 pips
    "XAUUSD": [200, 300, 400, 550, 750],       # 2.00 - 7.50 USD
}

_SHARED = {
    "s.tf_minutes": [5, 15],
    "s.session": ["london", "ny", "london_ny", "extended"],
    "s.sl_atr": [1.5, 2.0, 2.5, 3.0],
    "s.tp_r": [1.2, 1.5, 1.8, 2.2],
    "e.max_bars": [45, 75, 120, 180],
    "e.be_trigger_r": [0.0, 1.0],
    "e.trail_start_r": [0.0, 1.2],
    # partial-then-breakeven is the main lever on win rate: it converts
    # trades that would have round-tripped into small wins
    "e.partial_r": [0.0, 0.8, 1.2],
    "e.cooldown_bars": [5, 20],
    "e.max_trades_per_day": [4, 8],
}

_ER_GATE = {"s.er_min": [0.30, 0.45, 0.60]}

_MODE = {
    MODE_BREAKOUT: {
        **_ER_GATE,
        "s.don_period": [12, 24, 36],
        "s.adx_min": [12, 20],
        "s.expansion_mult": [1.0, 1.15],
    },
    MODE_MOMENTUM: {
        **_ER_GATE,
        "s.mom_period": [12, 24, 36],
        "s.mom_min_atr": [0.5, 1.0, 1.5],
        "s.mom_confirm": [0, 1],
    },
    MODE_PULLBACK: {
        **_ER_GATE,
        "s.pb_rsi_lo": [35, 40, 45],
        "s.pb_depth_atr": [0.3, 0.6],
        "s.pb_lookback": [4, 8],
        "s.adx_min": [12, 20],
    },
    MODE_FADE: {
        # a fade wants the opposite regime: cap the Efficiency Ratio
        "s.er_max": [0.30, 0.50, 1.0],
        "s.band_k": [1.5, 2.0, 2.5],
        "s.rsi_lo": [22, 28],
        "s.adx_max": [20, 30],
        "s.confirm_mode": [0, 1, 2, 3],
    },
}

# Fixed, not searched.  Each of these was a free parameter in the first version
# and was demoted after it proved to be a noise dimension.
FIXED = {
    "atr_period": 14,
    "atr_rank_lookback": 288,
    "atr_rank_min": 0.10,
    "atr_rank_max": 0.99,
    "er_period": 24,
    "ema_fast": 12,
    "ema_slow": 48,
    "adx_period": 14,
    "rsi_period": 7,
    "atr_avg_period": 48,
    "pb_slope_period": 30,
}


def space_for(mode: str, symbol: str) -> Dict[str, Sequence]:
    """Full search space for one mode on one symbol."""
    sp = dict(_SHARED)
    sp.update(_MODE[mode])
    sp["s.min_sl_points"] = MIN_SL_POINTS[symbol.upper()]
    return sp


def apply_fixed(params):
    """Stamp the non-searched defaults onto a StrategyParams."""
    from dataclasses import replace

    fade_extra = {}
    if params.mode == MODE_FADE:
        # keep the RSI band symmetric so it stays one decision, not two
        fade_extra["rsi_hi"] = 100.0 - params.rsi_lo
    return replace(params, **FIXED, **fade_extra)


def size(space: Dict[str, Sequence]) -> int:
    n = 1
    for v in space.values():
        n *= len(v)
    return n


ALL_MODES = [MODE_BREAKOUT, MODE_MOMENTUM, MODE_PULLBACK, MODE_FADE]
