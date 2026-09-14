"""Bar-by-bar execution engine for intraday strategies.

Modelling choices (all deliberately pessimistic)
------------------------------------------------
* **Bars are BID prices**, the MetaTrader convention.  A long fills at the ask
  (``bid + spread``) and exits on the bid; a short fills at the bid and exits on
  the ask.  The spread is therefore paid exactly once per round trip, in the
  same direction as it is paid live.
* **Worst-case intrabar ordering.**  When a bar's range contains both the stop
  and the target, the stop is taken.  There is no way to know the intrabar path
  from OHLC, and assuming the favourable one is the single most common way a
  backtest flatters itself.
* **Gaps fill at the open.**  If a bar opens through the stop, the fill is the
  open, not the stop level.
* **Slippage** is adverse on market entries and worse again on stop exits, which
  is where slippage actually hurts.  Limit exits (take-profit, partial) do not
  slip -- a resting limit either fills at its price or does not fill.
* **Trailing stops cannot rescue the bar that sets them**: exits are evaluated
  before the trail is advanced with that bar's extreme.
* **Swap** is charged on every 21:00 UTC rollover crossed, tripled on Wednesday.

Look-ahead is prevented one level up, in ``strategy.py``: a signal derived from
a bar closing at ``t`` is handed to the engine on the execution bar at ``t``,
and is filled at that bar's *open*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from numba import njit

from . import data as data_mod

# --- trade record layout ---------------------------------------------------
T_ENTRY_IDX, T_EXIT_IDX, T_DIR, T_ENTRY_PX, T_EXIT_PX = 0, 1, 2, 3, 4
T_LOTS, T_SL_PX, T_TP_PX, T_PNL, T_R = 5, 6, 7, 8, 9
T_REASON, T_MAE_R, T_MFE_R, T_BARS, T_EQUITY, T_COST = 10, 11, 12, 13, 14, 15
N_TCOLS = 16

# --- exit reason codes -----------------------------------------------------
EXIT_SL, EXIT_TP, EXIT_TRAIL, EXIT_TIME = 1, 2, 3, 4
EXIT_SESSION, EXIT_BE, EXIT_EOD, EXIT_DAYSTOP = 5, 6, 7, 8
REASON_NAMES = {
    EXIT_SL: "stop_loss", EXIT_TP: "take_profit", EXIT_TRAIL: "trailing_stop",
    EXIT_TIME: "time_stop", EXIT_SESSION: "session_close", EXIT_BE: "breakeven",
    EXIT_EOD: "end_of_data", EXIT_DAYSTOP: "daily_stop",
}


@dataclass
class ExecConfig:
    """Everything the engine needs that is not a price series."""

    point: float
    value_per_point_per_lot: float
    min_lot: float
    lot_step: float
    max_lot: float
    commission_per_lot_rt: float
    slippage_points_entry: float
    slippage_points_stop: float
    swap_long_points: float = 0.0
    swap_short_points: float = 0.0

    initial_equity: float = 10_000.0
    risk_pct: float = 0.005            # fraction of equity risked per trade
    max_spread_points: float = 1e9

    # trade management, all in R (multiples of the initial stop distance)
    be_trigger_r: float = 0.0          # 0 disables
    be_offset_r: float = 0.0
    partial_r: float = 0.0             # 0 disables
    partial_frac: float = 0.5
    trail_start_r: float = 0.0         # 0 disables
    trail_dist_r: float = 1.0

    max_bars: int = 240
    cooldown_bars: int = 5
    max_trades_per_day: int = 100
    daily_loss_limit_r: float = 1e9    # stop trading for the day below -this
    force_exit_hour: int = 20          # close everything at this UTC hour
    force_exit_min: int = 45
    compound: bool = True


@njit(cache=True)
def _run(
    op: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray,
    hour: np.ndarray, minute: np.ndarray, day_id: np.ndarray, dow: np.ndarray,
    spread_pts: np.ndarray,
    sig_dir: np.ndarray, sig_sl: np.ndarray, sig_tp: np.ndarray,
    point: float, vpp: float, min_lot: float, lot_step: float, max_lot: float,
    commission_rt: float, slip_entry: float, slip_stop: float,
    swap_long: float, swap_short: float,
    initial_equity: float, risk_pct: float, max_spread: float,
    be_trigger_r: float, be_offset_r: float,
    partial_r: float, partial_frac: float,
    trail_start_r: float, trail_dist_r: float,
    max_bars: int, cooldown_bars: int, max_trades_day: int,
    daily_loss_limit_r: float, force_hour: int, force_min: int,
    compound: int, max_trades: int,
):
    n = op.shape[0]
    trades = np.zeros((max_trades, N_TCOLS))
    equity_curve = np.empty(n)

    equity = initial_equity
    n_trades = 0

    pos = 0                  # 0 flat, +1 long, -1 short
    entry_px = 0.0
    lots = 0.0
    lots_open = 0.0
    sl_px = 0.0
    tp_px = 0.0
    sl_dist0 = 0.0           # initial stop distance -> defines 1R
    risk_money = 0.0
    entry_i = 0
    partial_done = 0
    realized = 0.0           # money banked from the partial
    cost_acc = 0.0
    exit_px_acc = 0.0        # lots-weighted exit price accumulator
    best_px = 0.0
    mae_r = 0.0
    mfe_r = 0.0

    cur_day = -1
    trades_today = 0
    day_r = 0.0
    day_blocked = 0
    cooldown = 0

    for i in range(n):
        # ---- day roll -------------------------------------------------
        if day_id[i] != cur_day:
            cur_day = day_id[i]
            trades_today = 0
            day_r = 0.0
            day_blocked = 0

        # ---- swap at rollover -----------------------------------------
        if pos != 0 and hour[i] == 21 and minute[i] == 0:
            sw = swap_long if pos > 0 else swap_short
            mult = 3.0 if dow[i] == 2 else 1.0
            fee = sw * point * lots_open * (vpp / point) * mult
            equity += fee
            cost_acc -= fee if fee < 0.0 else 0.0

        sp = spread_pts[i] * point

        # ================= manage an open position =====================
        if pos != 0:
            bars_held = i - entry_i
            exited = 0
            reason = 0
            fill = 0.0

            if pos > 0:
                bar_lo, bar_hi, bar_op, bar_cl = lo[i], hi[i], op[i], cl[i]
            else:
                # shorts are stopped/targeted on the ask
                bar_lo, bar_hi = lo[i] + sp, hi[i] + sp
                bar_op, bar_cl = op[i] + sp, cl[i] + sp

            # --- excursion tracking (before any exit) -------------------
            if pos > 0:
                adverse = (entry_px - bar_lo) / sl_dist0
                favour = (bar_hi - entry_px) / sl_dist0
            else:
                adverse = (bar_hi - entry_px) / sl_dist0
                favour = (entry_px - bar_lo) / sl_dist0
            if adverse > mae_r:
                mae_r = adverse
            if favour > mfe_r:
                mfe_r = favour

            # --- 1. gap through the stop --------------------------------
            if pos > 0 and bar_op <= sl_px:
                fill = bar_op - slip_stop * point
                exited, reason = 1, EXIT_SL
                cost_acc += slip_stop * vpp * lots_open
            elif pos < 0 and bar_op >= sl_px:
                fill = bar_op + slip_stop * point
                exited, reason = 1, EXIT_SL
                cost_acc += slip_stop * vpp * lots_open

            # --- 2. stop touched inside the bar (pessimistic first) -----
            if exited == 0:
                if pos > 0 and bar_lo <= sl_px:
                    fill = sl_px - slip_stop * point
                    exited, reason = 1, EXIT_SL
                    cost_acc += slip_stop * vpp * lots_open
                elif pos < 0 and bar_hi >= sl_px:
                    fill = sl_px + slip_stop * point
                    exited, reason = 1, EXIT_SL
                    cost_acc += slip_stop * vpp * lots_open

            # --- 3. partial take-profit (a resting limit) ---------------
            if exited == 0 and partial_r > 0.0 and partial_done == 0:
                lvl = entry_px + pos * partial_r * sl_dist0
                touched = (pos > 0 and bar_hi >= lvl) or (pos < 0 and bar_lo <= lvl)
                if touched:
                    part_lots = lots_open * partial_frac
                    part_lots = np.floor(part_lots / lot_step + 1e-9) * lot_step
                    if part_lots >= min_lot and part_lots < lots_open:
                        pnl_part = pos * (lvl - entry_px) * (vpp / point) * part_lots
                        comm = commission_rt * part_lots
                        equity += pnl_part - comm
                        realized += pnl_part - comm
                        cost_acc += comm
                        exit_px_acc += lvl * part_lots
                        lots_open -= part_lots
                        partial_done = 1
                        # bank the rest: stop to breakeven (+ offset)
                        new_sl = entry_px + pos * be_offset_r * sl_dist0
                        if (pos > 0 and new_sl > sl_px) or (pos < 0 and new_sl < sl_px):
                            sl_px = new_sl

            # --- 4. fixed target ---------------------------------------
            if exited == 0 and tp_px > 0.0:
                if pos > 0 and bar_hi >= tp_px:
                    fill = tp_px
                    exited, reason = 1, EXIT_TP
                elif pos < 0 and bar_lo <= tp_px:
                    fill = tp_px
                    exited, reason = 1, EXIT_TP

            # --- 5. time / session stops --------------------------------
            if exited == 0:
                if bars_held >= max_bars:
                    fill = bar_cl - pos * slip_entry * point
                    exited, reason = 1, EXIT_TIME
                    cost_acc += slip_entry * vpp * lots_open
                elif hour[i] > force_hour or (hour[i] == force_hour and minute[i] >= force_min):
                    fill = bar_cl - pos * slip_entry * point
                    exited, reason = 1, EXIT_SESSION
                    cost_acc += slip_entry * vpp * lots_open

            # --- 6. advance breakeven / trail (never saves this bar) ----
            if exited == 0:
                if pos > 0:
                    if bar_hi > best_px:
                        best_px = bar_hi
                else:
                    if bar_lo < best_px:
                        best_px = bar_lo
                run_r = pos * (best_px - entry_px) / sl_dist0
                if be_trigger_r > 0.0 and run_r >= be_trigger_r:
                    new_sl = entry_px + pos * be_offset_r * sl_dist0
                    if (pos > 0 and new_sl > sl_px) or (pos < 0 and new_sl < sl_px):
                        sl_px = new_sl
                if trail_start_r > 0.0 and run_r >= trail_start_r:
                    new_sl = best_px - pos * trail_dist_r * sl_dist0
                    if (pos > 0 and new_sl > sl_px) or (pos < 0 and new_sl < sl_px):
                        sl_px = new_sl

            # --- 7. book the exit ---------------------------------------
            if exited == 1:
                if reason == EXIT_SL and partial_done == 1:
                    reason = EXIT_BE if abs(sl_px - entry_px) < 0.25 * sl_dist0 else EXIT_SL
                pnl_rest = pos * (fill - entry_px) * (vpp / point) * lots_open
                comm = commission_rt * lots_open
                equity += pnl_rest - comm
                cost_acc += comm
                exit_px_acc += fill * lots_open
                total_pnl = realized + pnl_rest - comm

                if n_trades < max_trades:
                    t = trades[n_trades]
                    t[T_ENTRY_IDX] = entry_i
                    t[T_EXIT_IDX] = i
                    t[T_DIR] = pos
                    t[T_ENTRY_PX] = entry_px
                    t[T_EXIT_PX] = exit_px_acc / lots if lots > 0 else fill
                    t[T_LOTS] = lots
                    t[T_SL_PX] = entry_px - pos * sl_dist0
                    t[T_TP_PX] = tp_px
                    t[T_PNL] = total_pnl
                    t[T_R] = total_pnl / risk_money if risk_money > 0 else 0.0
                    t[T_REASON] = reason
                    t[T_MAE_R] = mae_r
                    t[T_MFE_R] = mfe_r
                    t[T_BARS] = bars_held
                    t[T_EQUITY] = equity
                    t[T_COST] = cost_acc
                    n_trades += 1
                day_r += total_pnl / risk_money if risk_money > 0 else 0.0
                if day_r <= -daily_loss_limit_r:
                    day_blocked = 1
                pos = 0
                cooldown = cooldown_bars
                equity_curve[i] = equity
                continue

        # ================= look for a new entry ========================
        if pos == 0:
            if cooldown > 0:
                cooldown -= 1
            elif (
                sig_dir[i] != 0
                and day_blocked == 0
                and trades_today < max_trades_day
                and spread_pts[i] <= max_spread
                and sig_sl[i] > 0.0
                and not (hour[i] > force_hour or (hour[i] == force_hour and minute[i] >= force_min))
            ):
                d = sig_dir[i]
                sl_dist0 = sig_sl[i]
                base = initial_equity if compound == 0 else equity
                risk_amount = base * risk_pct
                sl_points = sl_dist0 / point
                per_lot_risk = sl_points * vpp
                raw_lots = risk_amount / per_lot_risk if per_lot_risk > 0 else 0.0
                lt = np.floor(raw_lots / lot_step + 1e-9) * lot_step
                if lt < min_lot:
                    lt = min_lot
                if lt > max_lot:
                    lt = max_lot

                if d > 0:
                    entry_px = op[i] + sp + slip_entry * point       # buy the ask
                else:
                    entry_px = op[i] - slip_entry * point            # sell the bid

                pos = d
                lots = lt
                lots_open = lt
                risk_money = sl_points * vpp * lt
                sl_px = entry_px - d * sl_dist0
                tp_px = entry_px + d * sig_tp[i] if sig_tp[i] > 0.0 else 0.0
                entry_i = i
                partial_done = 0
                realized = 0.0
                # Friction accounting: spread and slippage are embedded in the
                # fill prices, so they have to be tracked explicitly or the
                # reported cost is commission only, which badly understates it.
                cost_acc = (sp / point + slip_entry) * vpp * lt
                exit_px_acc = 0.0
                best_px = entry_px
                mae_r = 0.0
                mfe_r = 0.0
                trades_today += 1

        # ---- mark to market -------------------------------------------
        if pos != 0:
            mtm = pos * (cl[i] - entry_px) * (vpp / point) * lots_open
            equity_curve[i] = equity + mtm
        else:
            equity_curve[i] = equity

    # ---- force-close anything still open at the end -------------------
    if pos != 0 and n_trades < max_trades:
        i = n - 1
        fill = cl[i] if pos > 0 else cl[i] + spread_pts[i] * point
        pnl_rest = pos * (fill - entry_px) * (vpp / point) * lots_open
        comm = commission_rt * lots_open
        equity += pnl_rest - comm
        exit_px_acc += fill * lots_open
        total_pnl = realized + pnl_rest - comm
        t = trades[n_trades]
        t[T_ENTRY_IDX] = entry_i
        t[T_EXIT_IDX] = i
        t[T_DIR] = pos
        t[T_ENTRY_PX] = entry_px
        t[T_EXIT_PX] = exit_px_acc / lots if lots > 0 else fill
        t[T_LOTS] = lots
        t[T_SL_PX] = entry_px - pos * sl_dist0
        t[T_TP_PX] = tp_px
        t[T_PNL] = total_pnl
        t[T_R] = total_pnl / risk_money if risk_money > 0 else 0.0
        t[T_REASON] = EXIT_EOD
        t[T_MAE_R] = mae_r
        t[T_MFE_R] = mfe_r
        t[T_BARS] = i - entry_i
        t[T_EQUITY] = equity
        t[T_COST] = cost_acc + comm
        n_trades += 1
        equity_curve[i] = equity

    return trades[:n_trades], equity_curve


def run_backtest(
    bars: pd.DataFrame,
    signals: "Signals",
    cfg: ExecConfig,
    spread_points: np.ndarray,
) -> "BacktestResult":
    """Execute ``signals`` against ``bars`` and return trades + equity curve."""
    idx = bars.index
    op = bars["open"].to_numpy(dtype="float64")
    hi = bars["high"].to_numpy(dtype="float64")
    lo = bars["low"].to_numpy(dtype="float64")
    cl = bars["close"].to_numpy(dtype="float64")
    hour = idx.hour.to_numpy().astype(np.int64)
    minute = idx.minute.to_numpy().astype(np.int64)
    dow = idx.dayofweek.to_numpy().astype(np.int64)
    # trading day rolls at 21:00 UTC, matching the FX session
    day_id = ((data_mod.epoch_seconds(idx) + 3 * 3600) // 86400).astype(np.int64)

    max_trades = max(1000, len(bars) // 20)
    trades, equity = _run(
        op, hi, lo, cl, hour, minute, day_id, dow,
        spread_points.astype("float64"),
        signals.direction, signals.sl_distance, signals.tp_distance,
        cfg.point, cfg.value_per_point_per_lot, cfg.min_lot, cfg.lot_step, cfg.max_lot,
        cfg.commission_per_lot_rt, cfg.slippage_points_entry, cfg.slippage_points_stop,
        cfg.swap_long_points, cfg.swap_short_points,
        cfg.initial_equity, cfg.risk_pct, cfg.max_spread_points,
        cfg.be_trigger_r, cfg.be_offset_r, cfg.partial_r, cfg.partial_frac,
        cfg.trail_start_r, cfg.trail_dist_r,
        cfg.max_bars, cfg.cooldown_bars, cfg.max_trades_per_day,
        cfg.daily_loss_limit_r, cfg.force_exit_hour, cfg.force_exit_min,
        1 if cfg.compound else 0, int(max_trades),
    )
    return BacktestResult(trades=trades, equity=equity, index=idx, cfg=cfg)


@dataclass
class BacktestResult:
    trades: np.ndarray
    equity: np.ndarray
    index: pd.DatetimeIndex
    cfg: ExecConfig

    def trades_frame(self) -> pd.DataFrame:
        t = self.trades
        if len(t) == 0:
            return pd.DataFrame(
                columns=[
                    "entry_time", "exit_time", "direction", "entry_price", "exit_price",
                    "lots", "sl_price", "tp_price", "pnl", "r", "exit_reason",
                    "mae_r", "mfe_r", "bars_held", "equity", "cost",
                ]
            )
        ei = t[:, T_ENTRY_IDX].astype(int)
        xi = t[:, T_EXIT_IDX].astype(int)
        return pd.DataFrame({
            "entry_time": self.index[ei],
            "exit_time": self.index[xi],
            "direction": np.where(t[:, T_DIR] > 0, "long", "short"),
            "entry_price": t[:, T_ENTRY_PX],
            "exit_price": t[:, T_EXIT_PX],
            "lots": t[:, T_LOTS],
            "sl_price": t[:, T_SL_PX],
            "tp_price": t[:, T_TP_PX],
            "pnl": t[:, T_PNL],
            "r": t[:, T_R],
            "exit_reason": [REASON_NAMES.get(int(x), "?") for x in t[:, T_REASON]],
            "mae_r": t[:, T_MAE_R],
            "mfe_r": t[:, T_MFE_R],
            "bars_held": t[:, T_BARS].astype(int),
            "equity": t[:, T_EQUITY],
            "cost": t[:, T_COST],
        })
