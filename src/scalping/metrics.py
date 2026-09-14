"""Performance statistics.

Everything that decides whether a strategy passes is computed here, in R
(multiples of the risked amount) wherever possible, so results are comparable
across instruments with completely different tick values.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional

import numpy as np
import pandas as pd


@dataclass
class Metrics:
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    payoff: float = 0.0
    total_r: float = 0.0
    net_profit: float = 0.0
    return_pct: float = 0.0
    max_dd_pct: float = 0.0
    max_dd_r: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    cagr_pct: float = 0.0
    calmar: float = 0.0
    trades_per_day: float = 0.0
    avg_bars_held: float = 0.0
    max_consec_losses: int = 0
    t_stat: float = 0.0
    cost_share_of_gross: float = 0.0
    long_share: float = 0.0
    days: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)

    def passes(self, min_trades=100, min_pf=1.2, min_wr=0.50) -> bool:
        return (
            self.n_trades >= min_trades
            and self.profit_factor >= min_pf
            and self.win_rate >= min_wr
        )

    def summary(self) -> str:
        return (
            f"trades {self.n_trades:5d} | WR {self.win_rate*100:5.1f}% | "
            f"PF {self.profit_factor:5.2f} | exp {self.expectancy_r:+.3f}R | "
            f"payoff {self.payoff:4.2f} | totR {self.total_r:+7.1f} | "
            f"ret {self.return_pct:+7.1f}% | DD {self.max_dd_pct:5.1f}% | "
            f"Sharpe {self.sharpe:5.2f} | t {self.t_stat:5.2f}"
        )


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    with np.errstate(invalid="ignore", divide="ignore"):
        dd = np.where(peak > 0, (peak - equity) / peak, 0.0)
    return float(np.nanmax(dd))


def _max_consecutive_losses(r: np.ndarray) -> int:
    worst = run = 0
    for x in r:
        if x < 0:
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    return worst


def compute(
    trades: pd.DataFrame,
    equity: np.ndarray,
    index: pd.DatetimeIndex,
    initial_equity: float,
) -> Metrics:
    m = Metrics()
    m.days = int(index.normalize().nunique()) if len(index) else 0
    if len(trades) == 0:
        m.net_profit = float(equity[-1] - initial_equity) if equity.size else 0.0
        return m

    r = trades["r"].to_numpy(dtype="float64")
    pnl = trades["pnl"].to_numpy(dtype="float64")
    wins = r[r > 0]
    losses = r[r <= 0]

    m.n_trades = len(r)
    m.win_rate = float(len(wins) / len(r))
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    m.profit_factor = float(gross_win / gross_loss) if gross_loss > 1e-12 else float("inf")
    m.expectancy_r = float(r.mean())
    m.avg_win_r = float(wins.mean()) if len(wins) else 0.0
    m.avg_loss_r = float(losses.mean()) if len(losses) else 0.0
    m.payoff = float(m.avg_win_r / abs(m.avg_loss_r)) if m.avg_loss_r < 0 else float("inf")
    m.total_r = float(r.sum())
    m.net_profit = float(pnl.sum())
    m.return_pct = float(100.0 * m.net_profit / initial_equity)
    m.max_dd_pct = float(100.0 * _max_drawdown(equity))

    cum_r = np.cumsum(r)
    peak_r = np.maximum.accumulate(cum_r)
    m.max_dd_r = float(np.max(peak_r - cum_r)) if len(cum_r) else 0.0

    m.max_consec_losses = _max_consecutive_losses(r)
    m.avg_bars_held = float(trades["bars_held"].mean())
    m.trades_per_day = float(m.n_trades / m.days) if m.days else 0.0
    m.long_share = float((trades["direction"] == "long").mean())

    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    m.t_stat = float(m.expectancy_r / (sd / np.sqrt(len(r)))) if sd > 0 else 0.0

    # daily equity -> risk-adjusted return
    eq = pd.Series(equity, index=index)
    daily = eq.resample("1D").last().dropna()
    dret = daily.pct_change().dropna()
    if len(dret) > 2 and dret.std() > 0:
        m.sharpe = float(dret.mean() / dret.std() * np.sqrt(252))
        downside = dret[dret < 0]
        if len(downside) > 1 and downside.std() > 0:
            m.sortino = float(dret.mean() / downside.std() * np.sqrt(252))
    years = max(m.days / 252.0, 1e-9)
    final = float(equity[-1]) if equity.size else initial_equity
    if final > 0 and initial_equity > 0:
        m.cagr_pct = float(((final / initial_equity) ** (1.0 / years) - 1.0) * 100.0)
    m.calmar = float(m.cagr_pct / m.max_dd_pct) if m.max_dd_pct > 1e-9 else 0.0

    gross = float(np.abs(pnl).sum()) + float(trades["cost"].sum())
    m.cost_share_of_gross = float(trades["cost"].sum() / gross) if gross > 0 else 0.0
    return m


def breakdown(trades: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Slices used to sanity-check where the edge actually comes from."""
    if len(trades) == 0:
        return {}
    t = trades.copy()
    t["hour"] = pd.DatetimeIndex(t["entry_time"]).hour
    t["dow"] = pd.DatetimeIndex(t["entry_time"]).day_name()
    t["year"] = pd.DatetimeIndex(t["entry_time"]).year

    def agg(g):
        return pd.DataFrame({
            "trades": g["r"].size(),
            "win_rate": g["r"].apply(lambda s: (s > 0).mean()),
            "total_r": g["r"].sum(),
            "exp_r": g["r"].mean(),
        })

    return {
        "by_hour": agg(t.groupby("hour")),
        "by_dow": agg(t.groupby("dow")),
        "by_year": agg(t.groupby("year")),
        "by_direction": agg(t.groupby("direction")),
        "by_exit": agg(t.groupby("exit_reason")),
    }


def bootstrap_pvalue(r: np.ndarray, n_boot: int = 5000, seed: int = 0) -> float:
    """P(mean R <= 0) under a stationary bootstrap of the trade sequence."""
    if len(r) < 10:
        return 1.0
    rng = np.random.default_rng(seed)
    centred = r - r.mean()
    means = np.empty(n_boot)
    n = len(r)
    for i in range(n_boot):
        means[i] = centred[rng.integers(0, n, n)].mean()
    return float((means >= r.mean()).mean())
