"""Motor de backtest (numba) + indicadores + métricas."""
import numpy as np, pandas as pd
from numba import njit

S = '/tmp/claude-0/-home-user-TestRep1/32cf2e0d-ed49-5180-b82e-f2cdb4b87ec8/scratchpad'
FEE = 0.0005      # comissão por lado (taker perp USDT-M)
SLIP = 0.0002     # slippage por lado
COST = FEE + SLIP
FUND_SHORT_PER_HOUR = 0.0001 / 8   # funding médio 0.01%/8h
TF_HOURS = {'15m': 0.25, '1h': 1.0, '4h': 4.0, '1d': 24.0}

IS_START, IS_END = '2018-01-01', '2023-12-31 23:59'
OOS_START, OOS_END = '2024-01-01', '2026-12-31'


def load(tf, sym=None):
    import os
    sym = sym or os.environ.get('SYM', 'BTC')
    return pd.read_pickle(f'{S}/data/{sym}USD_{tf}.pkl')


# ---------------------------------------------------------------- kernel
@njit(cache=True)
def kernel(o, h, l, c, entry, exitsig, direction, tp, sl, maxbars, trail_act, trail,
           cost, fund_bar, start, end):
    n_max = end - start
    t_ret = np.empty(n_max); t_in = np.empty(n_max, np.int64); t_out = np.empty(n_max, np.int64); t_mae = np.empty(n_max)
    mae = 0.0
    nt = 0
    pos = 0
    ep = 0.0; stop = 0.0; tgt = 0.0; bars = 0; ext = 0.0; ein = 0
    eq = 1.0; peak = 1.0; maxdd = 0.0
    for i in range(start + 1, end):
        if pos == 0:
            if entry[i - 1]:
                pos = direction; ep = o[i]; bars = 0; ein = i; mae = 0.0
                slp = sl[i - 1]; tpp = tp[i - 1]
                if pos == 1:
                    stop = ep * (1 - slp) if slp > 0 else 0.0
                    tgt = ep * (1 + tpp) if tpp > 0 else 1e18
                    ext = h[i]
                else:
                    stop = ep * (1 + slp) if slp > 0 else 1e18
                    tgt = ep * (1 - tpp) if tpp > 0 else 0.0
                    ext = l[i]
        if pos != 0:
            bars += 1
            px = -1.0
            if pos == 1:
                if l[i] <= stop:
                    px = min(o[i], stop) if bars > 1 else stop
                elif h[i] >= tgt:
                    px = max(o[i], tgt) if bars > 1 else tgt
                elif exitsig[i] or (maxbars > 0 and bars >= maxbars):
                    px = c[i]
                worst = l[i] if px < 0 else min(l[i], px)
                mtm = eq * (1 + (worst / ep - 1) - cost)
            else:
                if h[i] >= stop:
                    px = max(o[i], stop) if bars > 1 else stop
                elif l[i] <= tgt:
                    px = min(o[i], tgt) if bars > 1 else tgt
                elif exitsig[i] or (maxbars > 0 and bars >= maxbars):
                    px = c[i]
                worst = h[i] if px < 0 else max(h[i], px)
                mtm = eq * (1 - (worst / ep - 1) - cost)
            if mtm / eq - 1 < mae:
                mae = mtm / eq - 1
            dd = 1 - mtm / peak
            if dd > maxdd:
                maxdd = dd
            if px > 0:
                r = pos * (px / ep - 1) - 2 * cost
                r -= fund_bar * bars   # funding (cobrado nos dois lados, conservador)
                eq *= (1 + r)
                if eq > peak:
                    peak = eq
                t_ret[nt] = r; t_in[nt] = ein; t_out[nt] = i; t_mae[nt] = min(mae, r); nt += 1
                pos = 0
            else:
                # trailing stop update (fecho da barra)
                if trail > 0:
                    if pos == 1:
                        if h[i] > ext:
                            ext = h[i]
                        if ext >= ep * (1 + trail_act):
                            ns = ext * (1 - trail)
                            if ns > stop:
                                stop = ns
                    else:
                        if l[i] < ext:
                            ext = l[i]
                        if ext <= ep * (1 - trail_act):
                            ns = ext * (1 + trail)
                            if ns < stop:
                                stop = ns
    return t_ret[:nt], t_in[:nt], t_out[:nt], maxdd, eq, t_mae[:nt]


def metrics(ret, maxdd, eq, years):
    n = len(ret)
    if n == 0:
        return dict(trades=0, winrate=0, pf=0, maxdd=maxdd * 100, ret=0, cagr=0, exp=0)
    w = ret[ret > 0]; ls = ret[ret <= 0]
    pf = w.sum() / (-ls.sum()) if ls.sum() < 0 else 99.0
    cagr = (eq ** (1 / years) - 1) * 100 if eq > 0 else -100
    return dict(trades=n, winrate=len(w) / n * 100, pf=pf, maxdd=maxdd * 100,
                ret=(eq - 1) * 100, cagr=cagr, exp=ret.mean() * 100)


def run(df, sig, start, end, tf, cost=None, full_out=False):
    """sig: dict(entry, exit, dir, tp, sl, maxbars, trail_act, trail)"""
    idx = df.index
    s = idx.searchsorted(pd.Timestamp(start)); e = idx.searchsorted(pd.Timestamp(end), 'right')
    n = len(df)
    def arr(v):
        if v is None: return np.zeros(n)
        if np.isscalar(v): return np.full(n, float(v))
        return np.nan_to_num(np.asarray(v, float))
    tp = arr(sig.get('tp')); sl = arr(sig.get('sl'))
    ent = np.nan_to_num(np.asarray(sig['entry'], float)).astype(np.bool_)
    ex = np.nan_to_num(np.asarray(sig.get('exit', np.zeros(n)), float)).astype(np.bool_)
    r, ti, to, dd, eq, mae = kernel(df.open.values, df.high.values, df.low.values, df.close.values,
                               ent, ex, int(sig['dir']), tp, sl, int(sig.get('maxbars', 0)),
                               float(sig.get('trail_act', 0)), float(sig.get('trail', 0)),
                               COST if cost is None else cost, FUND_SHORT_PER_HOUR * TF_HOURS[tf], s, e)
    years = (idx[min(e, n) - 1] - idx[s]).total_seconds() / (365.25 * 86400)
    m = metrics(r, dd, eq, years)
    if full_out:
        return m, r, ti, to, mae
    return m, r, ti, to


# ---------------------------------------------------------------- indicadores
def sma(x, n): return x.rolling(n).mean()
def ema(x, n): return x.ewm(span=n, adjust=False).mean()

def rsi(x, n):
    d = x.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False).mean(); ad = dn.ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + au / ad.replace(0, 1e-12))

def atr(df, n):
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def adx(df, n=14):
    up = df.high.diff(); dn = -df.low.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(pdm, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(mdm, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-12)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi

def cci(df, n):
    tp = (df.high + df.low + df.close) / 3
    m = tp.rolling(n).mean(); md = tp.rolling(n).apply(lambda v: np.abs(v - v.mean()).mean(), raw=True)
    return (tp - m) / (0.015 * md)

def cci_fast(df, n):
    # aproximação com desvio padrão (muito mais rápida)
    tp = (df.high + df.low + df.close) / 3
    return (tp - tp.rolling(n).mean()) / (0.015 * tp.rolling(n).std() * 0.8)

def stoch(df, n, k=3):
    ll = df.low.rolling(n).min(); hh = df.high.rolling(n).max()
    fk = 100 * (df.close - ll) / (hh - ll).replace(0, 1e-12)
    return fk, fk.rolling(k).mean()

def willr(df, n):
    ll = df.low.rolling(n).min(); hh = df.high.rolling(n).max()
    return -100 * (hh - df.close) / (hh - ll).replace(0, 1e-12)

def mfi(df, n):
    tp = (df.high + df.low + df.close) / 3; mf = tp * df.volume
    pos = mf.where(tp > tp.shift(), 0).rolling(n).sum(); neg = mf.where(tp < tp.shift(), 0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, 1e-12))

def supertrend(df, n, mult):
    a = atr(df, n).values; hl2 = ((df.high + df.low) / 2).values; c = df.close.values
    ub = hl2 + mult * a; lb = hl2 - mult * a
    fu = ub.copy(); fl = lb.copy(); d = np.ones(len(c))
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if c[i] > fu[i - 1]: d[i] = 1
        elif c[i] < fl[i - 1]: d[i] = -1
        else: d[i] = d[i - 1]
    return pd.Series(d, df.index)

def cross_up(a, b): return (a > b) & (a.shift() <= b.shift())
def cross_dn(a, b): return (a < b) & (a.shift() >= b.shift())


class Ind:
    """Cache de indicadores por dataframe."""
    def __init__(self, df):
        self.df = df; self.c = {}
        dtm = (df.index[1:] - df.index[:-1]).to_series().median()
        self.bpd = pd.Timedelta('1D') / dtm
    def get(self, key, fn):
        if key not in self.c: self.c[key] = fn()
        return self.c[key]
    def sma(self, n, src='close'): return self.get(('sma', n, src), lambda: sma(self.df[src], n))
    def ema(self, n): return self.get(('ema', n), lambda: ema(self.df.close, n))
    def rsi(self, n): return self.get(('rsi', n), lambda: rsi(self.df.close, n))
    def atr(self, n): return self.get(('atr', n), lambda: atr(self.df, n))
    def adx(self, n=14): return self.get(('adx', n), lambda: adx(self.df, n))
    def cci(self, n): return self.get(('cci', n), lambda: cci_fast(self.df, n))
    def stoch(self, n): return self.get(('stoch', n), lambda: stoch(self.df, n))
    def willr(self, n): return self.get(('willr', n), lambda: willr(self.df, n))
    def mfi(self, n): return self.get(('mfi', n), lambda: mfi(self.df, n))
    def std(self, n): return self.get(('std', n), lambda: self.df.close.rolling(n).std())
    def st(self, n, m): return self.get(('st', n, m), lambda: supertrend(self.df, n, m))
    def hh(self, n): return self.get(('hh', n), lambda: self.df.high.rolling(n).max())
    def ll(self, n): return self.get(('ll', n), lambda: self.df.low.rolling(n).min())
    def volm(self, n): return self.get(('volm', n), lambda: self.df.volume.rolling(n).mean())
