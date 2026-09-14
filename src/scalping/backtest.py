"""Orchestration: bars + parameters -> trades + metrics."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from . import data as data_mod
from . import metrics as metrics_mod
from .engine import BacktestResult, ExecConfig, run_backtest
from .instruments import Instrument, get_instrument
from .strategy import StrategyParams, compute_signals, spread_series, to_exec_signals


# Fields that change WHICH bars produce a signal.  Everything else (stop size,
# target, trade management) only changes what happens after entry, so the
# expensive indicator pass can be reused across those.
DIRECTION_FIELDS = (
    "mode", "tf_minutes", "session", "atr_period", "atr_rank_lookback",
    "atr_rank_min", "atr_rank_max", "allow_long", "allow_short",
    "er_period", "er_min", "er_max",
    "vwap_anchor_hour", "band_k", "rsi_period", "rsi_lo", "rsi_hi",
    "adx_period", "adx_max", "confirm_mode", "min_dev_atr",
    "don_period", "ema_fast", "ema_slow", "adx_min", "expansion_mult",
    "atr_avg_period",
    "pb_slope_period", "pb_rsi_lo", "pb_rsi_hi", "pb_depth_atr", "pb_lookback",
    "mom_period", "mom_min_atr", "mom_confirm",
)


def direction_key(p: StrategyParams) -> tuple:
    return tuple(getattr(p, f) for f in DIRECTION_FIELDS)


@dataclass
class Prepared:
    """Execution bars + signal bars + spread, computed once and reused."""

    symbol: str
    inst: Instrument
    exec_bars: pd.DataFrame
    spread_points: np.ndarray
    sig_cache: Dict[int, pd.DataFrame]
    dir_cache: Dict[tuple, tuple] = None

    def __post_init__(self):
        if self.dir_cache is None:
            self.dir_cache = {}

    def directions(self, p: StrategyParams) -> tuple:
        """(direction, atr) for these parameters, computed once per signal shape."""
        key = direction_key(p)
        hit = self.dir_cache.get(key)
        if hit is None:
            sig_bars = self.signal_bars(p.tf_minutes)
            frame = compute_signals(sig_bars, p, self.inst)
            hit = (
                frame["direction"].to_numpy(),
                frame["atr"].to_numpy("float64"),
                sig_bars.index,
            )
            self.dir_cache[key] = hit
        return hit

    def signal_bars(self, tf_minutes: int) -> pd.DataFrame:
        if tf_minutes not in self.sig_cache:
            self.sig_cache[tf_minutes] = data_mod.resample(self.exec_bars, f"{tf_minutes}min")
        return self.sig_cache[tf_minutes]

    def slice(self, start: Optional[str] = None, end: Optional[str] = None) -> "Prepared":
        mask = np.ones(len(self.exec_bars), dtype=bool)
        idx = self.exec_bars.index
        if start is not None:
            mask &= idx >= pd.Timestamp(start, tz="UTC")
        if end is not None:
            mask &= idx < pd.Timestamp(end, tz="UTC")
        return Prepared(
            symbol=self.symbol,
            inst=self.inst,
            exec_bars=self.exec_bars[mask],
            spread_points=self.spread_points[mask],
            sig_cache={},
            dir_cache={},
        )


def prepare(bars: pd.DataFrame, symbol: str) -> Prepared:
    inst = get_instrument(symbol)
    bars = bars.copy()
    if "volume" not in bars.columns:
        bars["volume"] = 1.0
    sp = spread_series(bars.index, bars, inst)
    return Prepared(symbol=symbol, inst=inst, exec_bars=bars, spread_points=sp, sig_cache={})


def exec_config_from(inst: Instrument, **overrides) -> ExecConfig:
    cfg = ExecConfig(
        point=inst.point,
        value_per_point_per_lot=inst.value_per_point_per_lot(),
        min_lot=inst.min_lot,
        lot_step=inst.lot_step,
        max_lot=inst.max_lot,
        commission_per_lot_rt=inst.commission_per_lot_rt,
        slippage_points_entry=inst.slippage_points_entry,
        slippage_points_stop=inst.slippage_points_stop,
        swap_long_points=inst.swap_long_points,
        swap_short_points=inst.swap_short_points,
        max_spread_points=inst.spread_max_points,
    )
    return replace(cfg, **overrides)


def run(
    prep: Prepared, params: StrategyParams, cfg: ExecConfig
) -> Tuple[metrics_mod.Metrics, pd.DataFrame, BacktestResult]:
    """Full pipeline for one parameter set."""
    sig_bars = prep.signal_bars(params.tf_minutes)
    if len(sig_bars) < 500:
        return metrics_mod.Metrics(), pd.DataFrame(), None

    direction, atr, sig_index = prep.directions(params)
    sl = params.sl_atr * atr
    floor_price = params.min_sl_points * prep.inst.point
    sl = np.where(np.isfinite(sl), np.maximum(sl, floor_price), 0.0)
    sig_frame = pd.DataFrame(
        {"direction": np.where(sl > 0, direction, 0),
         "sl_distance": sl, "tp_distance": params.tp_r * sl},
        index=sig_index,
    )
    signals = to_exec_signals(sig_frame, prep.exec_bars.index, params.tf_minutes)
    result = run_backtest(prep.exec_bars, signals, cfg, prep.spread_points)
    trades = result.trades_frame()
    m = metrics_mod.compute(trades, result.equity, prep.exec_bars.index, cfg.initial_equity)
    return m, trades, result
