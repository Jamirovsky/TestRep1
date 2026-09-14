"""Calibrated synthetic M1 bar generator.

WHY THIS EXISTS
---------------
This sandbox's egress policy blocks every market-data vendor (Dukascopy,
HistData, Yahoo, OANDA, Alpha Vantage, ...), so no genuine XAUUSD/EURUSD history
can be downloaded here.  This module produces a price process that reproduces
the *stylised facts* of intraday FX/gold so that the engine, the strategies and
the optimiser can be built and validated end to end.

READ THIS BEFORE QUOTING ANY NUMBER PRODUCED ON SYNTHETIC DATA
--------------------------------------------------------------
A backtest on synthetic data measures the **machinery**, not the **edge**.  The
generator contains, by construction, the mean reversion and the trend
persistence that the strategies look for, so a positive result here proves the
code is correct and the optimiser converges -- it is *not* evidence that the
strategy makes money on real XAUUSD or EURUSD.  Re-run on real data (see
``data/README.md``) before risking anything.

Reproduced stylised facts
-------------------------
* intraday volatility seasonality (Asia / London / NY-overlap / rollover)
* volatility clustering (GARCH(1,1))
* fat-tailed returns (standardised Student-t innovations)
* slow trend regimes (3-state Markov chain) + mean reversion to a slow anchor
* bid-ask bounce -> negative autocorrelation of 1-minute returns
* scheduled news jumps at 12:30 / 14:00 UTC
* session- and volatility-dependent spread
* the FX week: Sunday 21:00 UTC open -> Friday 21:00 UTC close
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd
from numba import njit

# Hourly volatility multipliers, index = UTC hour.
VOL_SEASON = {
    "EURUSD": np.array([
        0.55, 0.55, 0.60, 0.60, 0.55, 0.60, 0.75, 1.25, 1.45, 1.35, 1.20, 1.00,
        1.15, 1.55, 1.60, 1.45, 1.20, 0.95, 0.80, 0.70, 0.60, 0.35, 0.45, 0.50,
    ]),
    "XAUUSD": np.array([
        0.50, 0.50, 0.55, 0.60, 0.55, 0.60, 0.70, 1.00, 1.25, 1.25, 1.15, 1.00,
        1.20, 1.70, 1.75, 1.60, 1.35, 1.10, 0.90, 0.75, 0.60, 0.35, 0.45, 0.50,
    ]),
}

# Monday..Friday activity multipliers.
DOW_SEASON = np.array([0.95, 1.05, 1.05, 1.05, 1.00])


@dataclass
class SynthConfig:
    """Parameters of the synthetic price process."""

    symbol: str
    start: str = "2022-01-03"
    end: str = "2025-12-31"
    start_price: float = 1.08
    annual_vol: float = 0.065          # annualised sigma of the efficient price
    digits: int = 5
    point: float = 0.00001

    # GARCH(1,1) on the de-seasonalised residual
    garch_omega: float = 0.02
    garch_alpha: float = 0.075
    garch_beta: float = 0.905
    t_df: float = 4.5                  # Student-t degrees of freedom

    # 3-state trend regime: 0 = range, 1 = up, 2 = down
    p_stay_range: float = 0.9975
    p_stay_trend: float = 0.9945
    trend_drift_k: float = 0.05        # drift as a fraction of per-minute sigma

    # Mean reversion of log-price to a slow EMA anchor
    mr_theta: float = 0.004
    mr_anchor_halflife_min: float = 240.0
    mr_z_cap: float = 4.0

    # Microstructure
    bounce_frac_of_spread: float = 0.30
    substeps: int = 12                 # sub-bars per minute used to build OHLC

    # Scheduled news
    news_hours: tuple = (12, 14)
    news_minute: int = 30
    news_prob: float = 0.16
    news_size_sigma: float = 6.0

    seed: int = 7


@njit(cache=True)
def _simulate(
    n: int,
    hour_mult: np.ndarray,
    dow_mult: np.ndarray,
    sigma_min: float,
    omega: float,
    alpha: float,
    beta: float,
    t_df: float,
    p_stay_range: float,
    p_stay_trend: float,
    trend_k: float,
    mr_theta: float,
    mr_lambda: float,
    mr_z_cap: float,
    news_flag: np.ndarray,
    news_prob: float,
    news_size: float,
    substeps: int,
    bounce: np.ndarray,
    start_logp: float,
    seed: int,
):
    """Core recursion. Returns (open, high, low, close) log-price arrays."""
    np.random.seed(seed)

    o = np.empty(n, dtype=np.float64)
    h = np.empty(n, dtype=np.float64)
    l = np.empty(n, dtype=np.float64)
    c = np.empty(n, dtype=np.float64)

    logp = start_logp
    anchor = start_logp
    g = 1.0                      # GARCH variance of the standardised residual
    regime = 0
    sq = np.sqrt(float(substeps))
    t_scale = np.sqrt((t_df - 2.0) / t_df)   # standardise Student-t to unit var

    for i in range(n):
        # --- regime chain ------------------------------------------------
        u = np.random.random()
        if regime == 0:
            if u > p_stay_range:
                regime = 1 if np.random.random() < 0.5 else 2
        else:
            if u > p_stay_trend:
                regime = 0

        # --- conditional volatility --------------------------------------
        season = hour_mult[i] * dow_mult[i]
        sig = sigma_min * season * np.sqrt(g)

        # --- drift: trend regime + mean reversion to the slow anchor ------
        drift = 0.0
        if regime == 1:
            drift += trend_k * sig
        elif regime == 2:
            drift -= trend_k * sig
        z = (logp - anchor) / (sigma_min * 60.0)
        if z > mr_z_cap:
            z = mr_z_cap
        elif z < -mr_z_cap:
            z = -mr_z_cap
        drift -= mr_theta * z * sig

        # --- scheduled news jump -----------------------------------------
        jump = 0.0
        if news_flag[i] == 1 and np.random.random() < news_prob:
            jump = np.random.normal(0.0, news_size * sig)

        # --- intrabar path -> OHLC ---------------------------------------
        sub_sig = sig / sq
        sub_drift = drift / substeps
        sub_jump = jump / substeps
        p = logp
        o[i] = p
        hi = p
        lo = p
        for _ in range(substeps):
            eps = np.random.standard_t(t_df) * t_scale
            p = p + sub_drift + sub_jump + sub_sig * eps
            if p > hi:
                hi = p
            if p < lo:
                lo = p
        c[i] = p

        # --- GARCH update on the standardised residual --------------------
        resid = (c[i] - o[i] - drift - jump) / (sig if sig > 0.0 else 1e-12)
        g = omega + alpha * resid * resid + beta * g
        if g < 0.05:
            g = 0.05
        elif g > 40.0:
            g = 40.0

        anchor = anchor + mr_lambda * (c[i] - anchor)
        logp = c[i]

        # --- bid-ask bounce on the observed open/close --------------------
        b = bounce[i]
        if b > 0.0:
            o[i] += b if np.random.random() < 0.5 else -b
            c[i] += b if np.random.random() < 0.5 else -b
            if o[i] > hi:
                hi = o[i]
            if o[i] < lo:
                lo = o[i]
            if c[i] > hi:
                hi = c[i]
            if c[i] < lo:
                lo = c[i]
        h[i] = hi
        l[i] = lo

    return o, h, l, c


def _fx_minute_index(start: str, end: str) -> pd.DatetimeIndex:
    """Every minute the FX market is open between two dates (UTC)."""
    idx = pd.date_range(start=start, end=end, freq="1min", tz="UTC")
    dow, hour = idx.dayofweek, idx.hour
    weekend = (dow == 5) | ((dow == 4) & (hour >= 21)) | ((dow == 6) & (hour < 21))
    return idx[~weekend]


def generate(cfg: SynthConfig) -> pd.DataFrame:
    """Generate one synthetic M1 OHLC series."""
    idx = _fx_minute_index(cfg.start, cfg.end)
    n = len(idx)
    if n == 0:
        raise ValueError("empty date range")

    hours = idx.hour.to_numpy()
    season = VOL_SEASON.get(cfg.symbol.upper(), VOL_SEASON["EURUSD"])
    # Normalise so the *average variance* multiplier is 1 -> annual_vol is honoured.
    season = season / np.sqrt(np.mean(season ** 2))
    hour_mult = season[hours]
    dow_mult = DOW_SEASON[np.clip(idx.dayofweek.to_numpy(), 0, 4)]

    minutes_per_year = 1440.0 * 5.0 * 52.0
    sigma_min = cfg.annual_vol / np.sqrt(minutes_per_year)

    news_flag = (
        np.isin(hours, np.array(cfg.news_hours)) & (idx.minute.to_numpy() == cfg.news_minute)
    ).astype(np.int8)

    # Bounce is half a typical spread, expressed in log terms.
    bounce_price = cfg.bounce_frac_of_spread * _typical_spread_price(cfg)
    bounce = np.full(n, bounce_price / cfg.start_price, dtype=np.float64)

    mr_lambda = 1.0 - np.exp(-np.log(2.0) / cfg.mr_anchor_halflife_min)

    o, h, l, c = _simulate(
        n,
        hour_mult.astype(np.float64),
        dow_mult.astype(np.float64),
        float(sigma_min),
        cfg.garch_omega, cfg.garch_alpha, cfg.garch_beta, cfg.t_df,
        cfg.p_stay_range, cfg.p_stay_trend, cfg.trend_drift_k,
        cfg.mr_theta, float(mr_lambda), cfg.mr_z_cap,
        news_flag, cfg.news_prob, cfg.news_size_sigma,
        cfg.substeps, bounce,
        float(np.log(cfg.start_price)), int(cfg.seed),
    )

    df = pd.DataFrame(
        {
            "open": np.exp(o), "high": np.exp(h),
            "low": np.exp(l), "close": np.exp(c),
        },
        index=idx,
    )
    df = df.round(cfg.digits)
    # Rounding can invert a flat bar; repair the invariant.
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    df["volume"] = np.round(
        400.0 * hour_mult * (1.0 + 0.4 * np.random.default_rng(cfg.seed).standard_normal(n))
    ).clip(1.0)
    df.index.name = "time"
    df.attrs["synthetic"] = True
    df.attrs["symbol"] = cfg.symbol
    return df


def _typical_spread_price(cfg: SynthConfig) -> float:
    from .instruments import get_instrument

    try:
        inst = get_instrument(cfg.symbol)
    except KeyError:
        return 4.0 * cfg.point
    return inst.spread_base_points * inst.point


# ---------------------------------------------------------------------------
# presets calibrated to recent real-world levels
# ---------------------------------------------------------------------------
def preset(symbol: str, seed: int = 7, start: str = "2022-01-03", end: str = "2025-12-31") -> SynthConfig:
    s = symbol.upper()
    if s == "EURUSD":
        return SynthConfig(
            symbol="EURUSD", start=start, end=end,
            start_price=1.0850, annual_vol=0.055, digits=5, point=0.00001,
            trend_drift_k=0.05, mr_theta=0.004,
            bounce_frac_of_spread=0.35, seed=seed,
        )
    if s == "XAUUSD":
        return SynthConfig(
            symbol="XAUUSD", start=start, end=end,
            start_price=2650.0, annual_vol=0.115, digits=2, point=0.01,
            trend_drift_k=0.05, mr_theta=0.0035, t_df=4.0,
            bounce_frac_of_spread=0.45, seed=seed,
        )
    raise KeyError(symbol)


def describe(df: pd.DataFrame, symbol: str) -> str:
    """Stylised-fact report used to check the generator against reality."""
    from .instruments import get_instrument

    inst = get_instrument(symbol)
    r = np.log(df["close"]).diff().dropna()
    daily = df["close"].resample("1D").last().dropna()
    dret = np.log(daily).diff().dropna()
    day_hi = df["high"].resample("1D").max().dropna()
    day_lo = df["low"].resample("1D").min().dropna()
    day_range = (day_hi - day_lo)
    day_range = day_range[day_range > 0]

    m5 = resample_for_stats(df)
    tr = np.maximum(
        m5["high"] - m5["low"],
        np.maximum(
            (m5["high"] - m5["close"].shift()).abs(),
            (m5["low"] - m5["close"].shift()).abs(),
        ),
    ).dropna()

    lines = [
        f"--- synthetic {symbol} stylised facts ---",
        f"bars M1                : {len(df):,}",
        f"span                   : {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}",
        f"annualised vol (daily) : {dret.std() * np.sqrt(252) * 100:.2f}%",
        f"median daily range     : {day_range.median() / inst.pip:.1f} pips "
        f"({day_range.median():.4f} price)",
        f"mean M5 true range     : {tr.mean() / inst.pip:.2f} pips",
        f"1-min return autocorr  : {r.autocorr(1):+.4f}  (bid-ask bounce => negative)",
        f"|r| autocorr lag 1     : {r.abs().autocorr(1):+.4f}  (vol clustering => positive)",
        f"kurtosis of 1-min ret  : {r.kurtosis():.1f}  (fat tails)",
    ]
    return "\n".join(lines)


def resample_for_stats(df: pd.DataFrame) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return df.resample("5min", label="left", closed="left").agg(agg).dropna()
