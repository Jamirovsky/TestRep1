"""EA tick order-flow detector (OnTradeTick / CheckStopRun) on real aggressor-flagged trades.

Uses Binance USD-M aggTrades, where every trade carries the aggressor side. That is the
same information MT5 exposes through TICK_FLAG_BUY / TICK_FLAG_SELL on exchange feeds.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

from fetch_data import DATA


@njit(cache=True)
def _detect(ms, pt, qty, side, swh, swl, thr_ice, thr_sr, win_abs, win_sr, through, pad):
    n = ms.shape[0]
    cap = 200_000
    a_p = np.empty(cap, np.int64)
    a_start = np.empty(cap, np.int64)
    a_buy = np.empty(cap, np.float64)
    a_sell = np.empty(cap, np.float64)
    a_min = np.empty(cap, np.int64)
    a_max = np.empty(cap, np.int64)
    a_fired = np.empty(cap, np.bool_)
    na = 0
    out_ms = []
    out_lo = []
    out_hi = []
    out_k = []
    head = 0
    buy_sum = 0.0
    sell_sum = 0.0
    last_sr = -(1 << 62)
    for i in range(n):
        m = ms[i]
        p = pt[i]
        v = qty[i]
        s = side[i]
        # --- stop-run burst buffer (BufferPush / BufferEvict / CheckStopRun)
        if s > 0:
            buy_sum += v
        else:
            sell_sum += v
        while ms[head] < m - win_sr:
            if side[head] > 0:
                buy_sum -= qty[head]
            else:
                sell_sum -= qty[head]
            head += 1
        if m - last_sr >= win_sr:
            if buy_sum >= thr_sr and swh[i] > 0:
                bmin = 1 << 62
                bmax = 0
                for k in range(head, i + 1):
                    if side[k] > 0:
                        if pt[k] < bmin:
                            bmin = pt[k]
                        if pt[k] > bmax:
                            bmax = pt[k]
                if bmax > swh[i]:
                    out_ms.append(m)
                    out_lo.append(bmin)
                    out_hi.append(bmax)
                    out_k.append(3)
                    last_sr = m
            if m != last_sr and sell_sum >= thr_sr and swl[i] > 0:
                smin = 1 << 62
                smax = 0
                for k in range(head, i + 1):
                    if side[k] < 0:
                        if pt[k] < smin:
                            smin = pt[k]
                        if pt[k] > smax:
                            smax = pt[k]
                if smin < swl[i]:
                    out_ms.append(m)
                    out_lo.append(smin)
                    out_hi.append(smax)
                    out_k.append(4)
                    last_sr = m
        # --- per-price absorption accumulators
        w = 0
        for k in range(na):
            if a_start[k] < m - win_abs:
                continue
            if w != k:
                a_p[w] = a_p[k]
                a_start[w] = a_start[k]
                a_buy[w] = a_buy[k]
                a_sell[w] = a_sell[k]
                a_min[w] = a_min[k]
                a_max[w] = a_max[k]
                a_fired[w] = a_fired[k]
            w += 1
        na = w
        found = -1
        for k in range(na):
            if p < a_min[k]:
                a_min[k] = p
            if p > a_max[k]:
                a_max[k] = p
            if a_p[k] == p:
                found = k
        if found < 0:
            if na >= cap:
                continue
            found = na
            na += 1
            a_p[found] = p
            a_start[found] = m
            a_buy[found] = 0.0
            a_sell[found] = 0.0
            a_min[found] = p
            a_max[found] = p
            a_fired[found] = False
        if s > 0:
            a_buy[found] += v
        else:
            a_sell[found] += v
        if a_fired[found]:
            continue
        lvl = a_p[found]
        if a_sell[found] >= thr_ice and a_min[found] >= lvl - through:
            a_fired[found] = True
            out_ms.append(m)
            out_lo.append(lvl - pad)
            out_hi.append(lvl + pad)
            out_k.append(1)
        elif a_buy[found] >= thr_ice and a_max[found] <= lvl + through:
            a_fired[found] = True
            out_ms.append(m)
            out_lo.append(lvl - pad)
            out_hi.append(lvl + pad)
            out_k.append(2)
    return out_ms, out_lo, out_hi, out_k


KIND = {1: "BI", 2: "SI", 3: "BS", 4: "SS"}


def load_trades(symbol: str = "BTCUSDT") -> pd.DataFrame:
    files = sorted(DATA.glob(f"{symbol}_aggTrades_*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df.sort_values("ms", kind="stable").reset_index(drop=True)


def bars_from_trades(tr: pd.DataFrame, rule: str) -> pd.DataFrame:
    ts = pd.to_datetime(tr["ms"].to_numpy(), unit="ms", utc=True)
    s = pd.DataFrame({"price": tr["price"].to_numpy(), "qty": tr["qty"].to_numpy()}, index=ts)
    b = s["price"].resample(rule).ohlc()
    b["volume"] = s["qty"].resample(rule).sum()
    b = b.dropna()
    return b.tz_convert("America/New_York")


def detect_events(tr: pd.DataFrame, tick: float, prm, bars_1m: pd.DataFrame) -> pd.DataFrame:
    """Run the EA detector over all trades. Returns events with ms, lo, hi, kind."""
    pt = np.round(tr["price"].to_numpy() / tick).astype(np.int64)
    # swing of the prior N completed 1-minute bars, as the EA refreshes on each new M1 bar
    swh_m = bars_1m["high"].shift(1).rolling(prm.swing_bars).max()
    swl_m = bars_1m["low"].shift(1).rolling(prm.swing_bars).min()
    minute = pd.to_datetime(tr["ms"].to_numpy(), unit="ms", utc=True).floor("1min").tz_convert("America/New_York")
    swh = np.round(swh_m.reindex(minute).ffill().fillna(0).to_numpy() / tick).astype(np.int64)
    swl = np.round(swl_m.reindex(minute).ffill().fillna(0).to_numpy() / tick).astype(np.int64)
    o_ms, o_lo, o_hi, o_k = _detect(
        tr["ms"].to_numpy(np.int64), pt, tr["qty"].to_numpy(np.float64), tr["side"].to_numpy(np.int8),
        swh, swl, float(prm.min_iceberg), float(prm.min_stoprun),
        int(prm.absorb_window_s * 1000), int(prm.stoprun_window_s * 1000),
        int(prm.absorb_through_ticks), int(prm.zone_pad_ticks))
    ev = pd.DataFrame({"ms": np.array(o_ms, dtype=np.int64), "lo": np.array(o_lo) * tick,
                       "hi": np.array(o_hi) * tick, "kind": [KIND[k] for k in o_k]})
    return ev


def events_to_bars(ev: pd.DataFrame, bar_index: pd.DatetimeIndex, bar_seconds: int) -> list[tuple]:
    """Activate each zone at the first bar that STARTS after the event (no lookahead)."""
    t_bar = ((bar_index.tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy()
    j = np.searchsorted(t_bar, ev["ms"].to_numpy(), side="right")
    out = []
    for jj, lo, hi, k in zip(j, ev["lo"], ev["hi"], ev["kind"]):
        if jj < len(t_bar):
            out.append((int(jj), float(lo), float(hi), k))
    return out
