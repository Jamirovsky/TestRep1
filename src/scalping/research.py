"""Signal research: does the entry condition predict anything?

Optimising exit parameters on a signal with no forecasting power just fits
noise -- you can always find a stop/target pair that looked good in-sample.  So
before any optimisation, a signal has to clear two tests here:

``forward_returns``
    Mean forward return in ATR units, signed by trade direction, at several
    horizons, compared against the unconditional mean over the same bars.  A
    real signal beats the baseline by a visible margin at a horizon compatible
    with the intended holding time.

``triple_barrier``
    The question the engine actually asks: starting at the signal, is the
    ``+tp`` barrier touched before the ``-sl`` barrier within ``max_bars``?
    This yields the *cost-free* hit rate.  Subtract the cost drag (also
    reported) to see what survives.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from numba import njit


@njit(cache=True)
def _triple_barrier(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
    idxs: np.ndarray, dirs: np.ndarray, sl_dist: np.ndarray, tp_dist: np.ndarray,
    max_bars: int,
):
    """For each signal, which barrier is hit first. 1 = target, -1 = stop, 0 = timeout."""
    m = idxs.shape[0]
    n = close.shape[0]
    out = np.zeros(m, dtype=np.int64)
    bars = np.zeros(m, dtype=np.int64)
    ret_r = np.zeros(m, dtype=np.float64)
    for k in range(m):
        i0 = idxs[k]
        d = dirs[k]
        entry = close[i0]
        sl = sl_dist[k]
        tp = tp_dist[k]
        if sl <= 0.0:
            continue
        sl_px = entry - d * sl
        tp_px = entry + d * tp
        hit = 0
        held = 0
        for i in range(i0 + 1, min(i0 + 1 + max_bars, n)):
            held = i - i0
            if d > 0:
                if low[i] <= sl_px:          # stop checked first: pessimistic
                    hit = -1
                    break
                if high[i] >= tp_px:
                    hit = 1
                    break
            else:
                if high[i] >= sl_px:
                    hit = -1
                    break
                if low[i] <= tp_px:
                    hit = 1
                    break
        out[k] = hit
        bars[k] = held
        if hit == 1:
            ret_r[k] = tp / sl
        elif hit == -1:
            ret_r[k] = -1.0
        else:
            j = min(i0 + max_bars, n - 1)
            ret_r[k] = d * (close[j] - entry) / sl
    return out, bars, ret_r


@dataclass
class EdgeReport:
    n_signals: int
    horizons: List[int]
    signal_mean_atr: List[float]
    baseline_mean_atr: List[float]
    t_stats: List[float]
    barrier_hit_rate: float
    barrier_timeout_rate: float
    barrier_expectancy_r: float
    cost_drag_r: float
    net_expectancy_r: float

    def __str__(self) -> str:
        lines = [f"signals: {self.n_signals}"]
        lines.append("  horizon |  signal |  base  |   t   ")
        for h, s, b, t in zip(self.horizons, self.signal_mean_atr,
                              self.baseline_mean_atr, self.t_stats):
            lines.append(f"  {h:6d}  | {s:+6.3f} | {b:+6.3f} | {t:+5.2f}")
        lines.append(
            f"  barrier: hit {self.barrier_hit_rate*100:.1f}% "
            f"timeout {self.barrier_timeout_rate*100:.1f}% "
            f"gross {self.barrier_expectancy_r:+.3f}R "
            f"- cost {self.cost_drag_r:.3f}R "
            f"= net {self.net_expectancy_r:+.3f}R"
        )
        return "\n".join(lines)


def forward_returns(
    close: np.ndarray, atr: np.ndarray, idxs: np.ndarray, dirs: np.ndarray,
    horizons: Iterable[int] = (6, 12, 24, 48),
) -> Dict[str, List[float]]:
    """Direction-signed forward return in ATR units, signal vs unconditional."""
    n = len(close)
    sig_mean, base_mean, tstats = [], [], []
    for h in horizons:
        fwd = np.full(n, np.nan)
        fwd[: n - h] = (close[h:] - close[: n - h]) / np.where(atr[: n - h] > 0, atr[: n - h], np.nan)
        keep = idxs < n - h
        valid = idxs[keep]
        vd = dirs[keep]
        s = fwd[valid] * vd
        s = s[np.isfinite(s)]
        sig_mean.append(float(s.mean()) if len(s) else 0.0)
        # Baseline: the same long/short mix applied to *every* bar.  A signal is
        # only interesting if it beats simply being in the market with that bias.
        b = fwd[np.isfinite(fwd)]
        long_share = float((vd > 0).mean()) if len(vd) else 0.5
        base_mean.append(float(b.mean() * (2.0 * long_share - 1.0)) if len(b) else 0.0)
        t = float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))) if len(s) > 2 and s.std() > 0 else 0.0
        tstats.append(t)
    return {"signal": sig_mean, "baseline": base_mean, "t": tstats}


def edge_report(
    bars: pd.DataFrame,
    sig_frame: pd.DataFrame,
    sl_dist: np.ndarray,
    tp_dist: np.ndarray,
    cost_points: float,
    point: float,
    max_bars: int = 48,
    horizons: Iterable[int] = (6, 12, 24, 48),
) -> EdgeReport:
    """Full pre-optimisation diagnostic for one signal definition."""
    close = bars["close"].to_numpy("float64")
    high = bars["high"].to_numpy("float64")
    low = bars["low"].to_numpy("float64")
    atr = sig_frame["atr"].to_numpy("float64")

    d = sig_frame["direction"].to_numpy()
    idxs = np.flatnonzero(d != 0).astype(np.int64)
    dirs = d[idxs].astype(np.int64)
    if len(idxs) == 0:
        return EdgeReport(0, list(horizons), [], [], [], 0, 0, 0, 0, 0)

    fr = forward_returns(close, atr, idxs, dirs, horizons)

    sl_k = sl_dist[idxs]
    tp_k = tp_dist[idxs]
    hit, bars_held, ret_r = _triple_barrier(high, low, close, idxs, dirs, sl_k, tp_k, max_bars)

    hit_rate = float((hit == 1).mean())
    timeout = float((hit == 0).mean())
    gross = float(ret_r.mean())
    with np.errstate(invalid="ignore", divide="ignore"):
        drag = float(np.mean(cost_points * point / np.where(sl_k > 0, sl_k, np.nan)))
    return EdgeReport(
        n_signals=len(idxs),
        horizons=list(horizons),
        signal_mean_atr=fr["signal"],
        baseline_mean_atr=fr["baseline"],
        t_stats=fr["t"],
        barrier_hit_rate=hit_rate,
        barrier_timeout_rate=timeout,
        barrier_expectancy_r=gross,
        cost_drag_r=drag,
        net_expectancy_r=gross - drag,
    )


def round_trip_cost_points(inst, hour: int = 14, stop_exit: bool = True) -> float:
    """Total friction of one round trip, in points: spread + slippage + commission."""
    spread = inst.spread_points_for_hour(hour)
    comm_points = inst.commission_per_lot_rt / inst.value_per_point_per_lot()
    slip = inst.slippage_points_entry + (inst.slippage_points_stop if stop_exit else 0.0)
    return spread + comm_points + slip


def variance_ratio(close: pd.Series, horizons_bars: Iterable[int] = (2, 4, 12, 24, 48, 96)) -> pd.DataFrame:
    """Lo-MacKinlay variance ratio at several horizons.

    ``VR(q) = Var(q-bar return) / (q * Var(1-bar return))``

    * ``VR = 1``  random walk -- nothing for either family to trade
    * ``VR > 1``  trending: momentum / breakout / pullback have something to find
    * ``VR < 1``  mean-reverting: the fade family is the right tool

    Run this **first** on any new instrument or timeframe.  It costs a second and
    tells you which strategy family is even worth optimising, and at what
    horizon -- which is a far better use of time than discovering the same thing
    after a thousand backtests.  The accompanying z-statistic is the
    heteroskedasticity-robust test of VR = 1; |z| below ~2 means the deviation
    from a random walk is not distinguishable from noise.
    """
    r = np.log(close.astype("float64")).diff().dropna().to_numpy()
    n = len(r)
    if n < 100:
        return pd.DataFrame(columns=["horizon_bars", "variance_ratio", "z_stat"])
    v1 = r.var(ddof=1)
    rows = []
    for q in horizons_bars:
        if q < 2 or n // q < 10:
            continue
        agg = r[: n // q * q].reshape(-1, q).sum(axis=1)
        vr = agg.var(ddof=1) / (q * v1)
        # heteroskedasticity-consistent standard error (Lo & MacKinlay 1988)
        mu = r.mean()
        d = (r - mu) ** 2
        theta = 0.0
        for j in range(1, q):
            num = float(np.sum(d[j:] * d[: n - j]))
            den = float(np.sum(d)) ** 2      # squared SUM, not sum of squares / n
            delta = num / den if den > 0 else 0.0
            theta += (2.0 * (q - j) / q) ** 2 * delta
        z = (vr - 1.0) / np.sqrt(theta) if theta > 0 else np.nan
        rows.append({"horizon_bars": q, "variance_ratio": round(float(vr), 4),
                     "z_stat": round(float(z), 2) if np.isfinite(z) else np.nan})
    return pd.DataFrame(rows)
