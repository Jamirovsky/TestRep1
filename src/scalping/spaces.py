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

from .strategy import (MODE_BANDS, MODE_BREAKOUT, MODE_FADE, MODE_MOMENTUM, MODE_ORB,
                       MODE_PULLBACK, MODE_RSI2, MODE_SWEEP)

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


# ---------------------------------------------------------------------------
# Minor metals (XAGUSD / XPTUSD / XPDUSD, and XAUUSD on real data as the
# comparison).  Three things differ from the FX/gold space above, all forced by
# the measurements in reports/metals_diagnose.json:
#
# * stop floors are in BASIS POINTS of price (s.min_sl_bp), because costs are;
# * holding times reach 8 hours: on XPT/XPD the toll is 0.7-1.0 ATR(M30), so a
#   stop has to be several M30 ATRs wide before friction is a small share of R;
# * targets go below 1R: the real metals mean-revert intraday, and a
#   mean-reversion edge is harvested with a high strike rate and a small target.
# The timeframe is NOT searched inside a run -- each M1/M5/M15/M30 is explored
# separately (scripts/explore_metals.py) and the winner is fixed.
# ---------------------------------------------------------------------------
METALS = ("XAGUSD", "XPTUSD", "XPDUSD", "XAUUSD", "XAUJPY")

MIN_SL_BP: Dict[str, List[float]] = {
    "XAUUSD": [15, 25, 40, 60],
    "XAUJPY": [20, 30, 45, 70],
    "XAGUSD": [30, 50, 80, 120],
    "XPTUSD": [60, 100, 150, 220],
    "XPDUSD": [100, 160, 250, 350],
}

_SHARED_METALS = {
    "s.session": ["london", "ny", "london_ny", "extended"],
    "s.sl_atr": [1.0, 1.5, 2.0, 3.0, 4.0],
    "s.tp_r": [0.5, 0.8, 1.0, 1.5, 2.0],
    "e.max_bars": [60, 120, 240, 480],
    "e.be_trigger_r": [0.0, 0.7],
    "e.trail_start_r": [0.0, 1.0],
    "e.partial_r": [0.0, 0.6],
    "e.cooldown_bars": [15, 60],
    "e.max_trades_per_day": [3, 6],
}

_MODE_METALS = {
    **_MODE,
    MODE_FADE: {
        "s.er_max": [0.30, 0.50, 1.0],
        "s.band_k": [1.0, 1.5, 2.0, 2.5],
        "s.rsi_lo": [20, 28, 35],
        "s.adx_max": [20, 30, 100],
        "s.confirm_mode": [0, 1, 2, 3],
    },
}
_MODE_METALS[MODE_BANDS] = {
    **_MODE_METALS[MODE_FADE],
    "s.bb_period": [20, 48, 96],
}


# Round 2: "selective".  Round 1 showed that on these symbols the toll, not
# the signal, decides the outcome: with costs zeroed the round-1 winners sit
# at 0 to +0.04R, with costs they lose 0.08-0.18R.  The only lever left is to
# trade LESS and demand bigger moves per trade -- higher entry thresholds,
# wider stops (friction a smaller share of R) and wider targets.
_SELECTIVE_OVERRIDES = {
    "s.sl_atr": [2.0, 3.0, 4.0, 6.0],
    "s.tp_r": [0.6, 1.0, 1.5, 2.5],
    "e.max_bars": [120, 240, 480],
    "e.cooldown_bars": [60, 240],
    "e.max_trades_per_day": [1, 2, 4],
}
_SELECTIVE_MODE = {
    MODE_MOMENTUM: {"s.er_min": [0.30, 0.45, 0.60], "s.mom_period": [12, 24, 48],
                    "s.mom_min_atr": [1.5, 2.5, 3.5], "s.mom_confirm": [0, 1]},
    MODE_BREAKOUT: {"s.er_min": [0.30, 0.45, 0.60], "s.don_period": [24, 48, 96],
                    "s.adx_min": [20, 30], "s.expansion_mult": [1.15, 1.4]},
    MODE_FADE: {"s.er_max": [0.30, 0.50, 1.0], "s.band_k": [2.0, 2.5, 3.0, 3.5],
                "s.rsi_lo": [15, 22, 30], "s.adx_max": [25, 100], "s.confirm_mode": [0, 2, 3]},
}
_SELECTIVE_MODE[MODE_BANDS] = {**_SELECTIVE_MODE[MODE_FADE], "s.bb_period": [48, 96, 192]}


# ---------------------------------------------------------------------------
# XBRUSD (Brent).  The brief asks for a HIGH STRIKE RATE (WR >= 57%) with only
# a positive profit factor, so the exits lean towards small targets, partial
# profit and breakeven; three new families (orb / rsi2 / sweep) join the four
# inherited from the XAUUSD scalper.
# ---------------------------------------------------------------------------
_SHARED_OIL = {
    "s.session": ["london", "ny", "london_ny", "overlap", "extended"],
    "s.sl_atr": [1.0, 1.5, 2.0, 3.0],
    "s.tp_r": [0.4, 0.6, 0.8, 1.0, 1.5],
    "e.max_bars": [30, 60, 120, 240],
    "e.be_trigger_r": [0.0, 0.5],
    "e.trail_start_r": [0.0, 0.8],
    "e.partial_r": [0.0, 0.4],
    "e.cooldown_bars": [5, 20, 60],
    "e.max_trades_per_day": [2, 4],
    "s.min_sl_bp": [15, 25, 40, 60],
}
_MODE_OIL = {
    **_MODE_METALS,
    MODE_ORB: {"s.orb_hour": [7, 8, 13, 14], "s.orb_bars": [2, 4, 6],
               "s.orb_buffer_atr": [0.0, 0.2, 0.5], "s.er_min": [0.0, 0.3], "s.orb_fade": [0, 1]},
    MODE_RSI2: {"s.r2_period": [2, 3], "s.r2_lo": [5, 10, 20], "s.trend_ema": [50, 100, 200],
                "s.er_max": [0.5, 1.0]},
    MODE_SWEEP: {"s.sweep_lookback": [12, 24, 48, 96], "s.sweep_wick_atr": [0.2, 0.5, 1.0],
                 "s.er_max": [0.3, 0.5, 1.0]},
}
# round-2 "tight" variant: even smaller targets, more management -> strike rate
_TIGHT_OIL = {
    "s.sl_atr": [1.5, 2.0, 3.0, 4.0],
    "s.tp_r": [0.3, 0.4, 0.5, 0.6, 0.8],
    "e.be_trigger_r": [0.0, 0.3, 0.5],
    "e.partial_r": [0.0, 0.25, 0.4],
    "e.max_bars": [20, 45, 90, 180],
}
OIL_MODES = ["orb", "rsi2", "sweep", "momentum", "breakout", "fade", "bands"]


def space_for(mode: str, symbol: str, tf_minutes: int | None = None,
              variant: str = "base") -> Dict[str, Sequence]:
    """Full search space for one mode on one symbol.

    For the metals, ``tf_minutes`` pins the signal timeframe (the timeframe is
    chosen by a separate exploration, not inside the walk-forward).
    """
    if symbol.upper() == "XBRUSD":
        sp = dict(_SHARED_OIL)
        sp.update(_MODE_OIL[mode])
        if variant in ("tight", "selective"):
            sp.update(_TIGHT_OIL)
        sp["s.tf_minutes"] = [tf_minutes or 15]
        return sp
    if symbol.upper() in METALS and (symbol.upper() != "XAUUSD" or tf_minutes is not None):
        sp = dict(_SHARED_METALS)
        sp.update(_MODE_METALS[mode])
        sp["s.min_sl_bp"] = MIN_SL_BP[symbol.upper()]
        sp["s.tf_minutes"] = [tf_minutes or 15]
        if variant == "selective":
            sp.update(_SELECTIVE_OVERRIDES)
            for k in [k for k in sp if k.startswith("s.") and k not in _SHARED_METALS
                      and k not in ("s.min_sl_bp", "s.tf_minutes")]:
                del sp[k]
            sp.update(_SELECTIVE_MODE[mode])
            b = MIN_SL_BP[symbol.upper()]
            sp["s.min_sl_bp"] = [b[1], b[2], b[3], round(b[3] * 1.6)]
        return sp
    sp = dict(_SHARED)
    sp.update(_MODE[mode])
    sp["s.min_sl_points"] = MIN_SL_POINTS[symbol.upper()]
    return sp


def apply_fixed(params):
    """Stamp the non-searched defaults onto a StrategyParams."""
    from dataclasses import replace

    fade_extra = {}
    if params.mode in (MODE_FADE, MODE_BANDS):
        # keep the RSI band symmetric so it stays one decision, not two
        fade_extra["rsi_hi"] = 100.0 - params.rsi_lo
    return replace(params, **FIXED, **fade_extra)


def size(space: Dict[str, Sequence]) -> int:
    n = 1
    for v in space.values():
        n *= len(v)
    return n


ALL_MODES = [MODE_BREAKOUT, MODE_MOMENTUM, MODE_PULLBACK, MODE_FADE, MODE_BANDS, MODE_ORB, MODE_RSI2,
             MODE_SWEEP]


# ---------------------------------------------------------------------------
# Baskets (7 US stocks, 5 cash indices): ONE shared parameter set per basket.
# Sessions are market-relative (strategy.MARKET_SESSIONS) so US and European
# indices each trade their own cash session with the same parameter.
# ---------------------------------------------------------------------------
BASKET_MIN_SL_BP: Dict[str, List[float]] = {
    "stocks": [10, 20, 35, 50],
    "indices": [8, 12, 20, 30],
}

_SHARED_BASKET = {
    "s.session": ["cash_open", "cash_mid", "cash_pm", "cash"],
    "s.sl_atr": [1.0, 1.5, 2.0, 3.0],
    "s.tp_r": [0.6, 1.0, 1.5, 2.0],
    "e.max_bars": [30, 60, 120, 240],
    "e.be_trigger_r": [0.0, 0.7],
    "e.trail_start_r": [0.0, 1.0],
    "e.partial_r": [0.0, 0.6],
    "e.cooldown_bars": [5, 20, 60],
    "e.max_trades_per_day": [2, 4],
}


def basket_space(mode: str, basket: str, tf_minutes: int, variant: str = "base") -> Dict[str, Sequence]:
    sp = dict(_SHARED_BASKET)
    if variant == "selective":
        sp.update(_SELECTIVE_OVERRIDES)
        sp["e.max_bars"] = [60, 120, 240]
        sp.update(_SELECTIVE_MODE[mode])
    else:
        sp.update(_MODE_METALS[mode])
    sp["s.min_sl_bp"] = BASKET_MIN_SL_BP[basket]
    sp["s.tf_minutes"] = [tf_minutes]
    return sp
