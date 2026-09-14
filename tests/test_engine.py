"""Engine correctness tests.

These pin down the behaviours that decide whether a backtest is honest:
cost accounting, worst-case intrabar ordering, gap fills, and the look-ahead
barrier.  Each one has silently inflated somebody's equity curve at some point.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scalping import indicators as ind
from scalping.data import epoch_seconds
from scalping.engine import ExecConfig, REASON_NAMES, run_backtest
from scalping.instruments import get_instrument
from scalping.strategy import Signals, to_exec_signals


def make_bars(prices, start="2023-06-05 08:00", freq="1min"):
    """Build M1 bars from a list of (open, high, low, close) tuples."""
    idx = pd.date_range(start, periods=len(prices), freq=freq, tz="UTC")
    arr = np.array(prices, dtype="float64")
    return pd.DataFrame(
        {"open": arr[:, 0], "high": arr[:, 1], "low": arr[:, 2],
         "close": arr[:, 3], "volume": 100.0},
        index=idx,
    )


def flat_cfg(inst, **kw):
    base = dict(
        point=inst.point,
        value_per_point_per_lot=inst.value_per_point_per_lot(),
        min_lot=inst.min_lot, lot_step=inst.lot_step, max_lot=inst.max_lot,
        commission_per_lot_rt=0.0,
        slippage_points_entry=0.0, slippage_points_stop=0.0,
        swap_long_points=0.0, swap_short_points=0.0,
        initial_equity=10_000.0, risk_pct=0.01,
        max_bars=10_000, cooldown_bars=0, max_trades_per_day=100,
        force_exit_hour=23, force_exit_min=59, compound=False,
    )
    base.update(kw)
    return ExecConfig(**base)


def one_signal(n, at, direction, sl, tp):
    d = np.zeros(n, dtype=np.int64)
    s = np.zeros(n, dtype="float64")
    t = np.zeros(n, dtype="float64")
    d[at] = direction
    s[at] = sl
    t[at] = tp
    return Signals(d, s, t)


# ---------------------------------------------------------------------------
class TestExits:
    def test_take_profit_fill_is_exact(self):
        inst = get_instrument("EURUSD")
        bars = make_bars([
            (1.1000, 1.1002, 1.0998, 1.1000),
            (1.1000, 1.1005, 1.0999, 1.1004),
            (1.1004, 1.1030, 1.1003, 1.1028),   # target at 1.1020 touched here
            (1.1028, 1.1030, 1.1026, 1.1029),
        ])
        sig = one_signal(len(bars), 1, +1, 0.0010, 0.0020)
        res = run_backtest(bars, sig, flat_cfg(inst), np.zeros(len(bars)))
        tr = res.trades_frame()
        assert len(tr) == 1
        assert tr.exit_reason.iloc[0] == "take_profit"
        # entry at bar 1 open (1.1000), target 20 pips above
        assert tr.exit_price.iloc[0] == pytest.approx(1.1020, abs=1e-9)
        assert tr.r.iloc[0] == pytest.approx(2.0, abs=1e-6)

    def test_stop_wins_when_bar_contains_both(self):
        """A bar spanning stop and target must resolve as the stop."""
        inst = get_instrument("EURUSD")
        bars = make_bars([
            (1.1000, 1.1002, 1.0998, 1.1000),
            (1.1000, 1.1001, 1.0999, 1.1000),
            (1.1000, 1.1030, 1.0985, 1.1025),   # spans both 1.0990 and 1.1020
        ])
        sig = one_signal(len(bars), 1, +1, 0.0010, 0.0020)
        res = run_backtest(bars, sig, flat_cfg(inst), np.zeros(len(bars)))
        tr = res.trades_frame()
        assert tr.exit_reason.iloc[0] == "stop_loss"
        assert tr.r.iloc[0] == pytest.approx(-1.0, abs=1e-6)

    def test_gap_through_stop_fills_at_open_not_at_stop(self):
        inst = get_instrument("EURUSD")
        bars = make_bars([
            (1.1000, 1.1002, 1.0998, 1.1000),
            (1.1000, 1.1001, 1.0999, 1.1000),
            (1.0950, 1.0955, 1.0940, 1.0945),   # opens far below the 1.0990 stop
        ])
        sig = one_signal(len(bars), 1, +1, 0.0010, 0.0020)
        res = run_backtest(bars, sig, flat_cfg(inst), np.zeros(len(bars)))
        tr = res.trades_frame()
        assert tr.exit_reason.iloc[0] == "stop_loss"
        assert tr.exit_price.iloc[0] == pytest.approx(1.0950, abs=1e-9)
        assert tr.r.iloc[0] < -4.0          # a 50-pip gap against a 10-pip stop

    def test_time_stop_closes_the_trade(self):
        inst = get_instrument("EURUSD")
        bars = make_bars([(1.1000, 1.1001, 1.0999, 1.1000)] * 20)
        sig = one_signal(len(bars), 1, +1, 0.0010, 0.0050)
        res = run_backtest(bars, sig, flat_cfg(inst, max_bars=5), np.zeros(len(bars)))
        tr = res.trades_frame()
        assert tr.exit_reason.iloc[0] == "time_stop"
        assert tr.bars_held.iloc[0] == 5

    def test_short_is_stopped_on_the_ask(self):
        """A short's stop triggers on bid+spread, so spread works against it."""
        inst = get_instrument("EURUSD")
        bars = make_bars([
            (1.1000, 1.1002, 1.0998, 1.1000),
            (1.1000, 1.1001, 1.0999, 1.1000),
            (1.1000, 1.1008, 1.0999, 1.1007),   # bid high 1.1008; stop at 1.1010
        ])
        spread = np.full(len(bars), 30.0)       # 3.0 pips
        sig = one_signal(len(bars), 1, -1, 0.0010, 0.0020)
        res = run_backtest(bars, sig, flat_cfg(inst), spread)
        tr = res.trades_frame()
        # ask high = 1.1008 + 0.0003 = 1.1011 >= stop 1.1010 -> stopped
        assert tr.exit_reason.iloc[0] == "stop_loss"


class TestCosts:
    def test_round_trip_on_unchanged_price_loses_exactly_the_costs(self):
        """Buy and sell at the same mid: the loss must equal spread + commission."""
        inst = get_instrument("EURUSD")
        bars = make_bars([(1.1000, 1.1000, 1.1000, 1.1000)] * 6)
        spread_pts = 10.0                       # 1.0 pip
        cfg = flat_cfg(inst, max_bars=3, commission_per_lot_rt=7.0)
        sig = one_signal(len(bars), 1, +1, 0.0010, 0.0500)
        res = run_backtest(bars, sig, cfg, np.full(len(bars), spread_pts))
        tr = res.trades_frame()
        lots = tr.lots.iloc[0]
        vpp = inst.value_per_point_per_lot()
        expected = -(spread_pts * vpp * lots) - 7.0 * lots
        assert tr.pnl.iloc[0] == pytest.approx(expected, rel=1e-9)
        # the reported friction must account for ALL of it, not just commission
        assert tr.cost.iloc[0] == pytest.approx(-expected, rel=1e-9)

    def test_reported_friction_includes_spread_slippage_and_commission(self):
        inst = get_instrument("XAUUSD")
        bars = make_bars([(2600.0, 2600.0, 2600.0, 2600.0)] * 6)
        spread_pts = 20.0
        cfg = flat_cfg(
            inst, max_bars=3, commission_per_lot_rt=7.0,
            slippage_points_entry=4.0, slippage_points_stop=9.0,
        )
        sig = one_signal(len(bars), 1, +1, 5.0, 100.0)
        res = run_backtest(bars, sig, cfg, np.full(len(bars), spread_pts))
        tr = res.trades_frame()
        lots = tr.lots.iloc[0]
        vpp = inst.value_per_point_per_lot()
        # time-stop exit: spread + entry slippage + exit slippage + commission
        expected = (spread_pts + 4.0 + 4.0) * vpp * lots + 7.0 * lots
        assert tr.cost.iloc[0] == pytest.approx(expected, rel=1e-9)
        assert tr.pnl.iloc[0] == pytest.approx(-expected, rel=1e-9)

    def test_stop_slippage_makes_the_loss_worse_than_one_r(self):
        inst = get_instrument("EURUSD")
        bars = make_bars([
            (1.1000, 1.1002, 1.0998, 1.1000),
            (1.1000, 1.1001, 1.0999, 1.1000),
            (1.1000, 1.1001, 1.0985, 1.0986),
        ])
        cfg = flat_cfg(inst, slippage_points_stop=5.0)
        sig = one_signal(len(bars), 1, +1, 0.0010, 0.0020)
        res = run_backtest(bars, sig, cfg, np.zeros(len(bars)))
        tr = res.trades_frame()
        assert tr.r.iloc[0] == pytest.approx(-1.05, abs=1e-6)

    def test_position_size_honours_the_risk_fraction(self):
        inst = get_instrument("XAUUSD")
        bars = make_bars([(2600.0, 2600.5, 2599.5, 2600.0)] * 6)
        cfg = flat_cfg(inst, initial_equity=10_000.0, risk_pct=0.01, max_bars=3)
        sig = one_signal(len(bars), 1, +1, 5.00, 10.00)   # USD 5 stop
        res = run_backtest(bars, sig, cfg, np.zeros(len(bars)))
        tr = res.trades_frame()
        # risk USD 100 / (500 points * USD 1 per point) = 0.20 lots
        assert tr.lots.iloc[0] == pytest.approx(0.20, abs=1e-9)


class TestLookAhead:
    def test_signal_fires_one_timeframe_after_its_bar_label(self):
        """An M5 bar labelled 08:00 closes at 08:05 and may not trade before it."""
        exec_idx = pd.date_range("2023-06-05 08:00", periods=20, freq="1min", tz="UTC")
        sig_idx = pd.date_range("2023-06-05 08:00", periods=4, freq="5min", tz="UTC")
        frame = pd.DataFrame(
            {"direction": [1, 0, -1, 0],
             "sl_distance": [0.001] * 4,
             "tp_distance": [0.002] * 4},
            index=sig_idx,
        )
        sig = to_exec_signals(frame, exec_idx, 5)
        fired = np.flatnonzero(sig.direction != 0)
        assert list(exec_idx[fired]) == [
            pd.Timestamp("2023-06-05 08:05", tz="UTC"),
            pd.Timestamp("2023-06-05 08:15", tz="UTC"),
        ]

    def test_stale_signal_across_a_gap_is_dropped(self):
        """After a weekend hole the old signal must not be resurrected."""
        exec_idx = pd.DatetimeIndex(
            [pd.Timestamp("2023-06-09 20:55", tz="UTC"),
             pd.Timestamp("2023-06-11 21:00", tz="UTC")]     # 48h later
        )
        frame = pd.DataFrame(
            {"direction": [1], "sl_distance": [0.001], "tp_distance": [0.002]},
            index=pd.DatetimeIndex([pd.Timestamp("2023-06-09 20:55", tz="UTC")]),
        )
        sig = to_exec_signals(frame, exec_idx, 5)
        assert sig.direction.sum() == 0


class TestTimeHandling:
    def test_epoch_seconds_is_resolution_independent(self):
        idx = pd.date_range("2023-01-02", periods=3, freq="1D", tz="UTC")
        s = epoch_seconds(idx)
        assert np.all(np.diff(s) == 86_400)
        for unit in ("s", "ms", "us", "ns"):
            conv = idx.as_unit(unit) if hasattr(idx, "as_unit") else idx
            assert np.array_equal(epoch_seconds(conv), s)

    def test_daily_trade_cap_resets_each_day(self):
        inst = get_instrument("EURUSD")
        n = 60 * 24 * 3
        idx = pd.date_range("2023-06-05 00:00", periods=n, freq="1min", tz="UTC")
        bars = pd.DataFrame(
            {"open": 1.1, "high": 1.1001, "low": 1.0999, "close": 1.1, "volume": 1.0},
            index=idx,
        )
        d = np.zeros(n, dtype=np.int64)
        d[::30] = 1                                   # a signal every 30 minutes
        sig = Signals(d, np.where(d != 0, 0.0010, 0.0), np.where(d != 0, 0.05, 0.0))
        cfg = flat_cfg(inst, max_bars=5, max_trades_per_day=2)
        res = run_backtest(bars, sig, cfg, np.zeros(n))
        tr = res.trades_frame()
        # The cap is per FX trading day, which rolls at 21:00 UTC -- NOT per
        # calendar day.  One calendar date therefore legitimately spans two
        # trading days and can hold two caps' worth of trades.
        entry = pd.DatetimeIndex(tr.entry_time)
        fx_day = (epoch_seconds(entry) + 3 * 3600) // 86_400
        per_day = pd.Series(1, index=fx_day).groupby(level=0).size()
        assert per_day.max() <= 2
        assert len(per_day) >= 3          # the cap resets, it is not a global cap


class TestIndicators:
    def test_running_indicators_survive_leading_nans(self):
        x = np.concatenate([np.full(12, np.nan), np.arange(1.0, 61.0)])
        for fn in (ind.sma, ind.rolling_std, ind.ema):
            out = fn(x, 10)
            assert np.isfinite(out[-1]), f"{fn.__name__} poisoned by leading NaN"

    def test_efficiency_ratio_bounds(self):
        straight = np.arange(100.0)
        assert ind.efficiency_ratio(straight, 20)[-1] == pytest.approx(1.0)
        chop = np.tile([100.0, 101.0], 50)
        assert ind.efficiency_ratio(chop, 20)[-1] < 0.1

    def test_indicators_are_causal(self):
        """Changing a future bar must not change a past indicator value."""
        rng = np.random.default_rng(0)
        c = np.cumsum(rng.standard_normal(500)) + 100.0
        h, l = c + 0.5, c - 0.5
        base = {
            "ema": ind.ema(c, 20), "rsi": ind.rsi(c, 14),
            "atr": ind.atr(h, l, c, 14), "er": ind.efficiency_ratio(c, 24),
            "adx": ind.adx(h, l, c, 14),
        }
        c2, h2, l2 = c.copy(), h.copy(), l.copy()
        c2[400:] += 50.0
        h2[400:] += 50.0
        l2[400:] += 50.0
        after = {
            "ema": ind.ema(c2, 20), "rsi": ind.rsi(c2, 14),
            "atr": ind.atr(h2, l2, c2, 14), "er": ind.efficiency_ratio(c2, 24),
            "adx": ind.adx(h2, l2, c2, 14),
        }
        for k in base:
            np.testing.assert_allclose(
                base[k][:399], after[k][:399], equal_nan=True,
                err_msg=f"{k} leaks future information",
            )
