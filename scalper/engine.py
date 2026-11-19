"""Fast numba engine for the Adaptive Memory Scalper (AMS).

Design
------
* Six signal *families* are evaluated on every closed bar of the signal
  timeframe (TF):
      0 IMP_CONT   follow a volatility-normalised price impulse
      1 IMP_FADE   fade the same impulse
      2 BRK_CONT   follow a Donchian-channel breakout
      3 BRK_FADE   fade the breakout (false-breakout trade)
      4 MR_CHOP    fade a stretch from the EMA while the market is choppy (low ER)
      5 PULLBACK   buy dips / sell rips in the direction of a trending market
* Every signal opens a *shadow trade* (paper trade, no capital).  When a shadow
  trade closes, its result in R (net of spread/slippage) updates an
  exponentially-weighted memory cell keyed by (family, direction, regime bucket).
* A real trade is only taken for the signal whose memory cell currently has the
  best positive expectancy (after a warm-up count).  Risk is scaled by that
  expectancy and halved while the account is in drawdown.  The memory persists
  across runs (it can be saved/loaded), so the strategy keeps learning live.

Execution is simulated on 1-minute bars with Capital.com-style bid/ask:
ask = mid + spread/2, bid = mid - spread/2.  If stop and target are touched in
the same minute the stop is assumed first.  Gaps fill at the open, stops get
extra slippage, overnight funding is charged at 22:00 UTC, a currency
conversion fee is charged on P&L, and size is limited by margin (leverage).
"""
from __future__ import annotations
import numpy as np
from numba import njit

NFAM = 6
FAMILY_NAMES = ["IMP_CONT", "IMP_FADE", "BRK_CONT", "BRK_FADE", "MR_CHOP", "PULLBACK"]

# ----------------------------------------------------------------------------
# indicators (causal)
# ----------------------------------------------------------------------------


@njit(cache=True)
def ema(x, n):
    out = np.empty_like(x)
    a = 2.0 / (n + 1.0)
    out[0] = x[0]
    for i in range(1, x.size):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


@njit(cache=True)
def atr(h, l, c, n):
    tr = np.empty_like(c)
    tr[0] = h[0] - l[0]
    for i in range(1, c.size):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return ema(tr, 2 * n - 1)  # Wilder smoothing


@njit(cache=True)
def efficiency_ratio(c, n):
    out = np.zeros_like(c)
    den = 0.0
    for i in range(1, c.size):
        den += abs(c[i] - c[i - 1])
        if i - n >= 1:
            den -= abs(c[i - n] - c[i - n - 1])
        if i >= n:
            out[i] = abs(c[i] - c[i - n]) / den if den > 1e-12 else 0.0
    return out


@njit(cache=True)
def rolling_max(x, n):
    out = np.full_like(x, np.nan)
    for i in range(n - 1, x.size):
        m = x[i - n + 1]
        for j in range(i - n + 2, i + 1):
            if x[j] > m:
                m = x[j]
        out[i] = m
    return out


@njit(cache=True)
def rolling_min(x, n):
    out = np.full_like(x, np.nan)
    for i in range(n - 1, x.size):
        m = x[i - n + 1]
        for j in range(i - n + 2, i + 1):
            if x[j] < m:
                m = x[j]
        out[i] = m
    return out


# ----------------------------------------------------------------------------
# signal generation on TF bars
# ----------------------------------------------------------------------------
# signal-parameter vector layout (see backtest.SIG_KEYS)
(P_ATR_N, P_IMP_N, P_IMP_THR, P_DON_N, P_Z_N, P_Z_IN, P_ER_N, P_ER_THR, P_HTF_N,
 P_VOL_N, P_FAM_MASK, P_BUCKET, P_MOM_N, P_TREND_FILTER) = range(14)


@njit(cache=True)
def tf_signals(o, h, l, c, v, p, hour):
    """Per TF bar: dir matrix (n, NFAM) in {-1,0,1}, regime bucket, ATR."""
    n = c.size
    a = atr(h, l, c, int(p[P_ATR_N]))
    imp_n = int(p[P_IMP_N])
    er = efficiency_ratio(c, int(p[P_ER_N]))
    e = ema(c, int(p[P_Z_N]))
    htf = ema(c, int(p[P_HTF_N]))
    dh = rolling_max(h, int(p[P_DON_N]))
    dl = rolling_min(l, int(p[P_DON_N]))
    a_long = ema(a, int(p[P_VOL_N]))
    mom_n = int(p[P_MOM_N])
    tfilt = int(p[P_TREND_FILTER])
    warm = int(max(p[P_ATR_N] * 3, p[P_ER_N], p[P_Z_N] * 2, p[P_HTF_N], p[P_DON_N], imp_n, mom_n)) + 3
    D = np.zeros((n, NFAM), np.int8)
    bucket = np.zeros(n, np.int8)
    mask = int(p[P_FAM_MASK])
    thr = p[P_IMP_THR]
    z_in = p[P_Z_IN]
    er_thr = p[P_ER_THR]
    sq = np.sqrt(imp_n)
    bmode = int(p[P_BUCKET])
    for k in range(warm, n):
        if bmode == 1:      # volatility regime
            bucket[k] = 1 if a[k] > a_long[k] else 0
        elif bmode == 2:    # session: Asia / Europe / US / late-US
            hr = hour[k]
            bucket[k] = 0 if hr < 7 else (1 if hr < 13 else (2 if hr < 20 else 3))
        elif bmode == 3:    # multi-day momentum state (market memory): up / down
            bucket[k] = 1 if c[k] > c[k - mom_n] else 0
        if a[k] <= 0:
            continue
        # impulse (trigger on the bar where |z| first crosses the threshold)
        z1 = (c[k] - c[k - imp_n]) / (a[k] * sq)
        z0 = (c[k - 1] - c[k - 1 - imp_n]) / (a[k - 1] * sq)
        imp = 0
        if z1 > thr and z0 <= thr:
            imp = 1
        elif z1 < -thr and z0 >= -thr:
            imp = -1
        if imp != 0:
            if mask & 1:
                D[k, 0] = imp
            if mask & 2:
                D[k, 1] = -imp
        # Donchian breakout (first close beyond the prior channel)
        brk = 0
        if c[k] > dh[k - 1] and c[k - 1] <= dh[k - 2]:
            brk = 1
        elif c[k] < dl[k - 1] and c[k - 1] >= dl[k - 2]:
            brk = -1
        if brk != 0:
            if mask & 4:
                D[k, 2] = brk
            if mask & 8:
                D[k, 3] = -brk
        # stretch from EMA in ATR units
        z = (c[k] - e[k]) / a[k]
        zp = (c[k - 1] - e[k - 1]) / a[k - 1]
        slope = htf[k] - htf[k - 3]
        if er[k] < er_thr:
            if mask & 16:
                if z < -z_in and zp >= -z_in:
                    D[k, 4] = 1
                elif z > z_in and zp <= z_in:
                    D[k, 4] = -1
        else:
            if mask & 32:
                if slope > 0 and z < -z_in * 0.5 and zp >= -z_in * 0.5:
                    D[k, 5] = 1
                elif slope < 0 and z > z_in * 0.5 and zp <= z_in * 0.5:
                    D[k, 5] = -1
    if tfilt == 1:   # keep only signals aligned with the multi-day momentum
        for k in range(warm, n):
            mom = 1 if c[k] > c[k - mom_n] else -1
            for f in range(NFAM):
                if D[k, f] != 0 and D[k, f] != mom:
                    D[k, f] = 0
    return D, bucket, a


# ----------------------------------------------------------------------------
# execution engine on 1-minute bars
# ----------------------------------------------------------------------------
(E_SL_K, E_TP_K, E_MAXH, E_BE_TRIG, E_TRAIL_K, E_RISK, E_MEM_ALPHA, E_MEM_THR,
 E_MEM_WARM, E_MEM_K, E_MIN_STOP_SPREAD, E_DD_CUT) = range(12)

(C_SPREAD, C_SLIP, C_LEV, C_MARGIN_USE, C_MIN_SIZE, C_SIZE_STEP, C_FEE_LONG,
 C_FEE_SHORT, C_FX_FEE, C_EQUITY0, C_MINLOT_RISK_CAP) = range(11)

NBUCKET = 4
NCELL = NFAM * 2 * NBUCKET
MAXV = 96


@njit(cache=True)
def cell_of(fam, dr, b):
    return (fam * NBUCKET + b) * 2 + (1 if dr > 0 else 0)


@njit(cache=True)
def run(o1, h1, l1, c1, minute_of_day, day_id, sig_idx, D, bucket, sig_atr,
        tf_minutes, e, cost, mem_init):
    """Simulate one period. sig_idx[k] = 1m index where TF bar k closes.

    Returns trades (N x 11), daily mark-to-market equity, memory (NCELL x 2).
    trade cols: entry_i, exit_i, dir, size, entry_px, exit_px, pnl, R, cell, reason, family
    reason: 1 stop, 2 target, 3 time
    """
    n1 = c1.size
    spread = cost[C_SPREAD]
    half = spread / 2.0
    slip = cost[C_SLIP]
    eq = cost[C_EQUITY0]
    peak = eq
    mem = mem_init.copy()     # [:,0] = EW mean R, [:,1] = count

    act = np.full(n1, -1, np.int64)
    for k in range(sig_idx.size):
        j = sig_idx[k] + 1
        if j < n1:
            act[j] = k

    trades = np.zeros((100000, 11))
    nt = 0
    pos = 0
    size = 0.0
    entry = 0.0
    sl = 0.0
    tp = 0.0
    risk_pts = 0.0
    e_atr = 0.0
    ent_i = 0
    cell = 0
    fam_real = 0
    fees = 0.0
    be_done = False
    maxh_min = int(e[E_MAXH] * tf_minutes)

    # shadow trades: dir, entry, sl, tp, risk_pts, start_i, cell, atr, be_done, active
    vt = np.zeros((MAXV, 10))
    cell_busy = np.zeros(NCELL, np.int64)

    ndays = day_id[-1] - day_id[0] + 1
    deq = np.zeros(ndays)
    d0 = day_id[0]
    sl_k = e[E_SL_K]
    tp_k = e[E_TP_K]

    for i in range(n1):
        # ---------------- signals become actionable at the open of bar i ----------------
        k = act[i]
        if k >= 0:
            a = sig_atr[k]
            b = bucket[k]
            stop_d = sl_k * a
            tgt_d = tp_k * a
            if stop_d >= e[E_MIN_STOP_SPREAD] * spread:
                best_s = -1e9
                best_f = -1
                for f in range(NFAM):
                    dr = D[k, f]
                    if dr == 0:
                        continue
                    cl = cell_of(f, dr, b)
                    px = o1[i] + half if dr > 0 else o1[i] - half
                    if cell_busy[cl] == 0:
                        for s in range(MAXV):
                            if vt[s, 9] == 0:
                                vt[s, 0] = dr
                                vt[s, 1] = px
                                vt[s, 2] = px - dr * stop_d
                                vt[s, 3] = px + dr * tgt_d
                                vt[s, 4] = stop_d
                                vt[s, 5] = i
                                vt[s, 6] = cl
                                vt[s, 7] = a
                                vt[s, 8] = 0
                                vt[s, 9] = 1
                                cell_busy[cl] = 1
                                break
                    if mem[cl, 1] >= e[E_MEM_WARM] and mem[cl, 0] > e[E_MEM_THR] and mem[cl, 0] > best_s:
                        best_s = mem[cl, 0]
                        best_f = f
                if pos == 0 and best_f >= 0 and eq > 0:
                    dr = D[k, best_f]
                    px = o1[i] + half if dr > 0 else o1[i] - half
                    r = e[E_RISK] * min(2.0, max(0.25, 1.0 + e[E_MEM_K] * best_s))
                    if (peak - eq) / peak > e[E_DD_CUT]:
                        r *= 0.5
                    sz = eq * r / (stop_d + slip)
                    max_sz = eq * cost[C_LEV] * cost[C_MARGIN_USE] / px
                    if sz > max_sz:
                        sz = max_sz
                    sz = np.floor(sz / cost[C_SIZE_STEP] + 1e-9) * cost[C_SIZE_STEP]
                    # small accounts: the broker minimum lot may exceed the risk budget.
                    # Allow the minimum lot only if its risk stays under the hard cap
                    # and the margin is available.
                    if sz < cost[C_MIN_SIZE] - 1e-12:
                        mn = cost[C_MIN_SIZE]
                        if (mn * (stop_d + slip) <= cost[C_MINLOT_RISK_CAP] * eq
                                and mn * px <= eq * cost[C_LEV] * cost[C_MARGIN_USE]):
                            sz = mn
                    if sz >= cost[C_MIN_SIZE] - 1e-12:
                        pos = dr
                        size = sz
                        entry = px
                        sl = px - dr * stop_d
                        tp = px + dr * tgt_d
                        risk_pts = stop_d
                        e_atr = a
                        ent_i = i
                        cell = cell_of(best_f, dr, b)
                        fam_real = best_f
                        fees = 0.0
                        be_done = False

        # ---------------- manage the real position ----------------
        if pos != 0:
            exit_px = 0.0
            reason = 0
            if pos > 0:
                if o1[i] - half <= sl:
                    exit_px = o1[i] - half - slip
                    reason = 1
                elif l1[i] - half <= sl:
                    exit_px = sl - slip
                    reason = 1
                elif h1[i] - half >= tp:
                    exit_px = tp
                    reason = 2
            else:
                if o1[i] + half >= sl:
                    exit_px = o1[i] + half + slip
                    reason = 1
                elif h1[i] + half >= sl:
                    exit_px = sl + slip
                    reason = 1
                elif l1[i] + half <= tp:
                    exit_px = tp
                    reason = 2
            if reason == 0 and i - ent_i >= maxh_min:
                exit_px = c1[i] - half if pos > 0 else c1[i] + half
                reason = 3
            if reason == 0:
                fav = (c1[i] - entry) * pos
                if e[E_BE_TRIG] > 0 and not be_done and fav >= e[E_BE_TRIG] * e_atr:
                    sl = entry + pos * half
                    be_done = True
                if e[E_TRAIL_K] > 0 and be_done:
                    nsl = c1[i] - pos * e[E_TRAIL_K] * e_atr
                    if (nsl - sl) * pos > 0:
                        sl = nsl
                if minute_of_day[i] == 22 * 60:
                    fr = cost[C_FEE_LONG] if pos > 0 else cost[C_FEE_SHORT]
                    fval = fr * size * c1[i]
                    fees += fval
                    eq -= fval
            if reason != 0:
                gross = (exit_px - entry) * pos * size
                pnl = gross - cost[C_FX_FEE] * abs(gross)
                eq += pnl
                tot = pnl - fees
                if nt < trades.shape[0]:
                    trades[nt, 0] = ent_i
                    trades[nt, 1] = i
                    trades[nt, 2] = pos
                    trades[nt, 3] = size
                    trades[nt, 4] = entry
                    trades[nt, 5] = exit_px
                    trades[nt, 6] = tot
                    trades[nt, 7] = tot / (risk_pts * size)
                    trades[nt, 8] = cell
                    trades[nt, 9] = reason
                    trades[nt, 10] = fam_real
                    nt += 1
                pos = 0
                if eq > peak:
                    peak = eq

        # ---------------- shadow trades -> memory ----------------
        for s in range(MAXV):
            if vt[s, 9] == 0:
                continue
            dr = vt[s, 0]
            xp = 0.0
            done = False
            if dr > 0:
                if l1[i] - half <= vt[s, 2]:
                    xp = min(vt[s, 2], o1[i] - half) - slip
                    done = True
                elif h1[i] - half >= vt[s, 3]:
                    xp = vt[s, 3]
                    done = True
            else:
                if h1[i] + half >= vt[s, 2]:
                    xp = max(vt[s, 2], o1[i] + half) + slip
                    done = True
                elif l1[i] + half <= vt[s, 3]:
                    xp = vt[s, 3]
                    done = True
            if not done and i - vt[s, 5] >= maxh_min:
                xp = c1[i] - half if dr > 0 else c1[i] + half
                done = True
            if not done:
                fav = (c1[i] - vt[s, 1]) * dr
                if e[E_BE_TRIG] > 0 and vt[s, 8] == 0 and fav >= e[E_BE_TRIG] * vt[s, 7]:
                    vt[s, 2] = vt[s, 1] + dr * half
                    vt[s, 8] = 1
                if e[E_TRAIL_K] > 0 and vt[s, 8] == 1:
                    nsl = c1[i] - dr * e[E_TRAIL_K] * vt[s, 7]
                    if (nsl - vt[s, 2]) * dr > 0:
                        vt[s, 2] = nsl
            else:
                R = (xp - vt[s, 1]) * dr / vt[s, 4]
                cl = int(vt[s, 6])
                al = e[E_MEM_ALPHA]
                if mem[cl, 1] == 0:
                    mem[cl, 0] = R * 0.5   # shrink first observation
                else:
                    mem[cl, 0] = (1 - al) * mem[cl, 0] + al * R
                mem[cl, 1] += 1
                vt[s, 9] = 0
                cell_busy[cl] = 0

        # ---------------- daily mark-to-market equity ----------------
        if i == n1 - 1 or day_id[i + 1] != day_id[i]:
            m = eq
            if pos != 0:
                xp = c1[i] - half if pos > 0 else c1[i] + half
                m += (xp - entry) * pos * size
            deq[day_id[i] - d0] = m

    return trades[:nt], deq, mem
