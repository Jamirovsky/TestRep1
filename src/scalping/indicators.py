"""Numba-compiled indicators.

All functions are *causal*: the value at index ``i`` uses only bars ``0..i``.
Warm-up regions are filled with NaN so the strategy layer can mask them out
rather than silently trading on half-formed indicators.
"""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def ema(x: np.ndarray, period: int) -> np.ndarray:
    n = x.shape[0]
    out = np.full(n, np.nan)
    if period < 1 or n == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    acc = 0.0
    cnt = 0
    seeded = False
    for i in range(n):
        xi = x[i]
        if not np.isfinite(xi):
            continue
        if not seeded:
            acc += xi
            cnt += 1
            if cnt == period:
                out[i] = acc / period
                seeded = True
        else:
            out[i] = out[i - 1] + alpha * (xi - out[i - 1])
    return out


@njit(cache=True)
def sma(x: np.ndarray, period: int) -> np.ndarray:
    """Trailing mean. NaN-tolerant: a NaN restarts the window rather than
    poisoning the running sum for the rest of the series."""
    n = x.shape[0]
    out = np.full(n, np.nan)
    if period < 1 or n < period:
        return out
    acc = 0.0
    cnt = 0
    for i in range(n):
        xi = x[i]
        if not np.isfinite(xi):
            acc = 0.0
            cnt = 0
            continue
        acc += xi
        cnt += 1
        if cnt > period:
            acc -= x[i - period]
            cnt = period
        if cnt == period:
            out[i] = acc / period
    return out


@njit(cache=True)
def rolling_std(x: np.ndarray, period: int) -> np.ndarray:
    """Population standard deviation over a trailing window."""
    n = x.shape[0]
    out = np.full(n, np.nan)
    if period < 2 or n < period:
        return out
    s = 0.0
    s2 = 0.0
    cnt = 0
    for i in range(n):
        xi = x[i]
        if not np.isfinite(xi):
            s = 0.0
            s2 = 0.0
            cnt = 0
            continue
        s += xi
        s2 += xi * xi
        cnt += 1
        if cnt > period:
            prev = x[i - period]
            s -= prev
            s2 -= prev * prev
            cnt = period
        if cnt == period:
            m = s / period
            v = s2 / period - m * m
            out[i] = np.sqrt(v) if v > 0.0 else 0.0
    return out


@njit(cache=True)
def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    n = high.shape[0]
    out = np.empty(n)
    out[0] = high[0] - low[0]
    for i in range(1, n):
        a = high[i] - low[i]
        b = abs(high[i] - close[i - 1])
        c = abs(low[i] - close[i - 1])
        m = a
        if b > m:
            m = b
        if c > m:
            m = c
        out[i] = m
    return out


@njit(cache=True)
def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's ATR."""
    tr = true_range(high, low, close)
    n = tr.shape[0]
    out = np.full(n, np.nan)
    if n < period or period < 1:
        return out
    acc = 0.0
    for i in range(period):
        acc += tr[i]
    out[period - 1] = acc / period
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


@njit(cache=True)
def rsi(close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's RSI."""
    n = close.shape[0]
    out = np.full(n, np.nan)
    if n <= period or period < 1:
        return out
    gain = 0.0
    loss = 0.0
    for i in range(1, period + 1):
        d = close[i] - close[i - 1]
        if d > 0:
            gain += d
        else:
            loss -= d
    avg_g = gain / period
    avg_l = loss / period
    out[period] = 100.0 - 100.0 / (1.0 + (avg_g / avg_l if avg_l > 0 else 1e9))
    for i in range(period + 1, n):
        d = close[i] - close[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        out[i] = 100.0 - 100.0 / (1.0 + (avg_g / avg_l if avg_l > 0 else 1e9))
    return out


@njit(cache=True)
def highest(x: np.ndarray, period: int) -> np.ndarray:
    n = x.shape[0]
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        m = x[i - period + 1]
        for j in range(i - period + 2, i + 1):
            if x[j] > m:
                m = x[j]
        out[i] = m
    return out


@njit(cache=True)
def lowest(x: np.ndarray, period: int) -> np.ndarray:
    n = x.shape[0]
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        m = x[i - period + 1]
        for j in range(i - period + 2, i + 1):
            if x[j] < m:
                m = x[j]
        out[i] = m
    return out


@njit(cache=True)
def session_vwap(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
    volume: np.ndarray, session_id: np.ndarray,
):
    """VWAP and VWAP-deviation sigma, both anchored at the start of each session.

    ``session_id`` changes value whenever a new session starts.  Returns
    ``(vwap, sigma)`` where sigma is the running volume-weighted RMS deviation of
    typical price from VWAP -- the band width used by the fade strategy.
    """
    n = close.shape[0]
    vwap = np.full(n, np.nan)
    sigma = np.full(n, np.nan)
    pv = 0.0
    vv = 0.0
    pv2 = 0.0
    cur = session_id[0] - 1 if n else 0
    for i in range(n):
        if session_id[i] != cur:
            cur = session_id[i]
            pv = 0.0
            vv = 0.0
            pv2 = 0.0
        tp = (high[i] + low[i] + close[i]) / 3.0
        v = volume[i]
        if v <= 0.0:
            v = 1.0
        pv += tp * v
        vv += v
        pv2 += tp * tp * v
        w = pv / vv
        vwap[i] = w
        var = pv2 / vv - w * w
        sigma[i] = np.sqrt(var) if var > 0.0 else 0.0
    return vwap, sigma


@njit(cache=True)
def rolling_rank(x: np.ndarray, period: int) -> np.ndarray:
    """Fraction of the trailing window that ``x[i]`` exceeds, in [0, 1].

    Used as a distribution-free volatility-regime filter: it adapts to whatever
    ATR level the instrument happens to be trading at, so the same parameter
    means the same thing on gold and on EURUSD.
    """
    n = x.shape[0]
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        if np.isnan(x[i]):
            continue
        cnt = 0
        tot = 0
        for j in range(i - period + 1, i + 1):
            if not np.isnan(x[j]):
                tot += 1
                if x[j] < x[i]:
                    cnt += 1
        if tot > 0:
            out[i] = cnt / tot
    return out


@njit(cache=True)
def linreg_slope(x: np.ndarray, period: int) -> np.ndarray:
    """Slope of an OLS fit over a trailing window, in price units per bar."""
    n = x.shape[0]
    out = np.full(n, np.nan)
    if period < 2 or n < period:
        return out
    t_sum = 0.0
    t2_sum = 0.0
    for k in range(period):
        t_sum += k
        t2_sum += k * k
    denom = period * t2_sum - t_sum * t_sum
    for i in range(period - 1, n):
        y_sum = 0.0
        ty_sum = 0.0
        for k in range(period):
            y = x[i - period + 1 + k]
            y_sum += y
            ty_sum += k * y
        out[i] = (period * ty_sum - t_sum * y_sum) / denom
    return out


@njit(cache=True)
def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's ADX -- trend-strength filter."""
    n = high.shape[0]
    out = np.full(n, np.nan)
    if n < 2 * period + 1:
        return out
    tr = true_range(high, low, close)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        if up > dn and up > 0:
            plus_dm[i] = up
        if dn > up and dn > 0:
            minus_dm[i] = dn

    atr_s = 0.0
    p_s = 0.0
    m_s = 0.0
    for i in range(1, period + 1):
        atr_s += tr[i]
        p_s += plus_dm[i]
        m_s += minus_dm[i]

    dx_sum = 0.0
    dx_cnt = 0
    for i in range(period + 1, n):
        atr_s = atr_s - atr_s / period + tr[i]
        p_s = p_s - p_s / period + plus_dm[i]
        m_s = m_s - m_s / period + minus_dm[i]
        if atr_s <= 0.0:
            continue
        pdi = 100.0 * p_s / atr_s
        mdi = 100.0 * m_s / atr_s
        s = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / s if s > 0.0 else 0.0
        if dx_cnt < period:
            dx_sum += dx
            dx_cnt += 1
            if dx_cnt == period:
                out[i] = dx_sum / period
        else:
            out[i] = (out[i - 1] * (period - 1) + dx) / period
    return out


@njit(cache=True)
def efficiency_ratio(close: np.ndarray, period: int) -> np.ndarray:
    """Kaufman's Efficiency Ratio: net move divided by the path walked.

    ``|close[i] - close[i-n]| / sum(|close[j] - close[j-1]|)`` over the window.
    1.0 is a straight line, ~0 is pure chop.  It is the cleanest cheap estimate
    of "is there a trend here", which is exactly the question a continuation
    entry needs answered before it risks the spread.
    """
    n = close.shape[0]
    out = np.full(n, np.nan)
    if period < 2 or n <= period:
        return out
    path = 0.0
    for i in range(1, n):
        path += abs(close[i] - close[i - 1])
        if i > period:
            path -= abs(close[i - period] - close[i - period - 1])
        if i >= period:
            net = abs(close[i] - close[i - period])
            out[i] = net / path if path > 0.0 else 0.0
    return out


@njit(cache=True)
def zscore(x: np.ndarray, period: int) -> np.ndarray:
    """Rolling z-score, NaN-tolerant."""
    m = sma(x, period)
    s = rolling_std(x, period)
    n = x.shape[0]
    out = np.full(n, np.nan)
    for i in range(n):
        if np.isfinite(m[i]) and np.isfinite(s[i]) and s[i] > 0.0:
            out[i] = (x[i] - m[i]) / s[i]
    return out
