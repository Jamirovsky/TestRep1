"""
Famílias de estratégias de scalping BTCUSD + indicadores.
Cada família recebe um DataFrame do timeframe do setup e devolve (long, short)
booleanos avaliados no FECHO de cada vela.
"""
import numpy as np
import pandas as pd
from functools import lru_cache

import os as _os
DATA_PATH = _os.path.join(_os.path.dirname(__file__), '..', 'data',
                          'btc_1m_ext.npz' if _os.path.exists(_os.path.join(_os.path.dirname(__file__), '..', 'data', 'btc_1m_ext.npz')) else 'btc_1m.npz')

_M1 = None
_TF = {}


def load_m1():
    global _M1
    if _M1 is None:
        z = np.load(DATA_PATH)
        _M1 = {k: z[k] for k in z.files}
    return _M1


def tf_frame(tf):
    """Velas do timeframe tf (minutos), alinhadas ao relógio UTC, com coluna 'entry_idx'
    = índice da vela de 1m onde se entra (abertura do minuto seguinte ao fecho)."""
    if tf in _TF:
        return _TF[tf]
    m = load_m1()
    ts = m['ts']
    df = pd.DataFrame({'open': m['o'], 'high': m['h'], 'low': m['l'], 'close': m['c'], 'volume': m['v']},
                      index=pd.to_datetime(ts, unit='s'))
    if tf == 1:
        r = df.copy()
    else:
        r = df.resample(f'{tf}min', label='left', closed='left').agg(
            {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    start = r.index.values.astype('datetime64[s]').astype(np.int64)
    entry_ts = start + tf * 60
    r['entry_idx'] = (entry_ts - ts[0]) // 60
    r['hour'] = r.index.hour
    r['dow'] = r.index.dayofweek
    # indicadores base
    r['atr14'] = atr(r, 14)
    _TF[tf] = r
    return r


# ---------------------------------------------------------------- indicadores
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def sma(s, n):
    return s.rolling(n).mean()


def rsi(s, n):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df, n):
    pc = df['close'].shift(1)
    tr = pd.concat([df['high'] - df['low'], (df['high'] - pc).abs(), (df['low'] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def session_vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    day = df.index.floor('D')
    pv = (tp * df['volume']).groupby(day).cumsum()
    vv = df['volume'].groupby(day).cumsum().replace(0, np.nan)
    return (pv / vv).fillna(tp)


def stoch(df, n, d):
    ll = df['low'].rolling(n).min()
    hh = df['high'].rolling(n).max()
    k = 100 * (df['close'] - ll) / (hh - ll).replace(0, np.nan)
    return k.fillna(50), k.fillna(50).rolling(d).mean()


# ------------------------------------------------------------- cache por TF
_cache = {}


def cached(tf, key, fn):
    k = (tf, key)
    if k not in _cache:
        if len(_cache) > 400:
            _cache.clear()
        _cache[k] = fn()
    return _cache[k]


def trend_filter(df, tf, p):
    """+1 só compras, -1 só vendas, 0 ambos. Usa EMA longa (no mesmo TF)."""
    mode = p.get('trend', 'none')
    if mode == 'none':
        return np.ones(len(df), bool), np.ones(len(df), bool)
    n = p['trend_len']
    e = cached(tf, ('ema', n), lambda: ema(df['close'], n).values)
    c = df['close'].values
    if mode == 'with':
        return c > e, c < e
    else:  # against (só fade quando esticado contra a tendência)
        return c < e, c > e


# ------------------------------------------------------------- famílias
def f_bb_rsi(df, tf, p):
    n, k, rp, lo = p['bb_len'], p['bb_k'], p['rsi_len'], p['rsi_lo']
    m = cached(tf, ('sma', n), lambda: sma(df['close'], n).values)
    sd = cached(tf, ('std', n), lambda: df['close'].rolling(n).std().values)
    r = cached(tf, ('rsi', rp), lambda: rsi(df['close'], rp).values)
    c = df['close'].values
    lg = (c < m - k * sd) & (r < lo)
    sh = (c > m + k * sd) & (r > 100 - lo)
    return lg, sh


def f_rsi2(df, tf, p):
    rp, th = p['rsi_len'], p['rsi_lo']
    r = cached(tf, ('rsi', rp), lambda: rsi(df['close'], rp).values)
    return r < th, r > 100 - th


def f_vwap(df, tf, p):
    z = p['vwap_z']
    vw = cached(tf, ('vwap',), lambda: session_vwap(df).values)
    a = df['atr14'].values
    dev = (df['close'].values - vw) / a
    return dev < -z, dev > z


def f_zscore(df, tf, p):
    n, z = p['z_len'], p['z_th']
    m = cached(tf, ('sma', n), lambda: sma(df['close'], n).values)
    sd = cached(tf, ('std', n), lambda: df['close'].rolling(n).std().values)
    zz = (df['close'].values - m) / sd
    return zz < -z, zz > z


def f_consec(df, tf, p):
    n = p['n_bars']
    c = df['close']
    dn = cached(tf, ('dn', n), lambda: (c.diff() < 0).rolling(n).sum().values == n)
    up = cached(tf, ('up', n), lambda: (c.diff() > 0).rolling(n).sum().values == n)
    return dn, up


def f_stoch(df, tf, p):
    n, lo = p['st_len'], p['st_lo']
    k, d = cached(tf, ('stoch', n), lambda: tuple(x.values for x in stoch(df, n, 3)))
    kp = np.roll(k, 1)
    dp = np.roll(d, 1)
    lg = (kp < dp) & (k > d) & (kp < lo)
    sh = (kp > dp) & (k < d) & (kp > 100 - lo)
    return lg, sh


def f_ema_pullback(df, tf, p):
    fe, se = p['ema_fast'], p['ema_slow']
    f = cached(tf, ('ema', fe), lambda: ema(df['close'], fe).values)
    s = cached(tf, ('ema', se), lambda: ema(df['close'], se).values)
    lo, hi, c = df['low'].values, df['high'].values, df['close'].values
    lg = (f > s) & (lo <= f) & (c > f)
    sh = (f < s) & (hi >= f) & (c < f)
    return lg, sh


def f_donchian(df, tf, p):
    n = p['dc_len']
    hh = cached(tf, ('hh', n), lambda: df['high'].rolling(n).max().shift(1).values)
    ll = cached(tf, ('ll', n), lambda: df['low'].rolling(n).min().shift(1).values)
    c = df['close'].values
    return c > hh, c < ll


def f_donchian_fade(df, tf, p):
    """Fade de falso rompimento: vela fura o máximo/mínimo de N velas e fecha de volta dentro."""
    n = p['dc_len']
    hh = cached(tf, ('hh', n), lambda: df['high'].rolling(n).max().shift(1).values)
    ll = cached(tf, ('ll', n), lambda: df['low'].rolling(n).min().shift(1).values)
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    return (l < ll) & (c > ll), (h > hh) & (c < hh)


def f_macd(df, tf, p):
    fe, se, sg = p['macd_f'], p['macd_s'], 9
    m = cached(tf, ('macd', fe, se), lambda: (ema(df['close'], fe) - ema(df['close'], se)).values)
    s = cached(tf, ('macds', fe, se), lambda: ema(pd.Series(m), sg).values)
    mp, sp = np.roll(m, 1), np.roll(s, 1)
    return (mp < sp) & (m > s) & (m < 0), (mp > sp) & (m < s) & (m > 0)


def f_keltner_rev(df, tf, p):
    n, k = p['kc_len'], p['kc_k']
    e = cached(tf, ('ema', n), lambda: ema(df['close'], n).values)
    a = df['atr14'].values
    c = df['close'].values
    cp = np.roll(c, 1)
    # vela anterior fora do canal, vela atual volta para dentro -> reversão
    lg = (cp < e - k * a) & (c > e - k * a)
    sh = (cp > e + k * a) & (c < e + k * a)
    return lg, sh


def f_orb(df, tf, p):
    """Opening Range Breakout: range dos primeiros orb_min minutos a partir da hora orb_h (UTC);
    entra no primeiro fecho fora do range nas 3 horas seguintes (1 sinal por dia por lado)."""
    H, M = p['orb_h'], p['orb_min']
    def build():
        idx = df.index
        mins = (idx.hour - H) * 60 + idx.minute  # minutos desde a abertura
        day = idx.floor('D')
        in_rng = (mins >= 0) & (mins < M)
        hi = pd.Series(np.where(in_rng, df['high'].values, np.nan), index=idx).groupby(day).transform('max').values
        lo = pd.Series(np.where(in_rng, df['low'].values, np.nan), index=idx).groupby(day).transform('min').values
        after = (mins + tf >= M + tf) & (mins < M + 180)
        c = df['close'].values
        up = after & (c > hi)
        dn = after & (c < lo)
        # só o primeiro de cada dia
        upf = pd.Series(up, index=idx).groupby(day).cumsum().values == 1
        dnf = pd.Series(dn, index=idx).groupby(day).cumsum().values == 1
        return up & upf, dn & dnf
    return cached(tf, ('orb', H, M), build)


def f_pinbar(df, tf, p):
    """Pin bar (rejeição) fora das Bandas de Bollinger."""
    n, k, w = p['bb_len'], p['bb_k'], p['wick']
    m = cached(tf, ('sma', n), lambda: sma(df['close'], n).values)
    sd = cached(tf, ('std', n), lambda: df['close'].rolling(n).std().values)
    o, h, l, c = (df[x].values for x in ('open', 'high', 'low', 'close'))
    rng_ = np.maximum(h - l, 1e-9)
    lw = (np.minimum(o, c) - l) / rng_
    uw = (h - np.maximum(o, c)) / rng_
    lg = (l < m - k * sd) & (lw >= w)
    sh = (h > m + k * sd) & (uw >= w)
    return lg, sh


def f_inside_bo(df, tf, p):
    """Inside bar seguido de rompimento na direção da EMA."""
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    h1, l1, h2, l2 = np.roll(h, 1), np.roll(l, 1), np.roll(h, 2), np.roll(l, 2)
    inside = (h1 <= h2) & (l1 >= l2)
    return inside & (c > h1), inside & (c < l1)


FAMILIES = {
    'ORB_SESSION': (f_orb, dict(orb_h=[0, 1, 7, 8, 12, 13, 14, 15], orb_min=[15, 30, 45, 60])),
    'PINBAR_BB': (f_pinbar, dict(bb_len=[14, 20, 30, 50], bb_k=[1.0, 1.5, 2.0, 2.5], wick=[0.4, 0.5, 0.6, 0.7])),
    'INSIDE_BO': (f_inside_bo, dict(dummy=[0])),
    'BB_RSI_MR': (f_bb_rsi, dict(bb_len=[10, 14, 20, 30, 50], bb_k=[1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0], rsi_len=[2, 3, 4, 7, 14], rsi_lo=[5, 10, 15, 20, 25, 30, 35, 40])),
    'RSI_EXTREME': (f_rsi2, dict(rsi_len=[2, 3, 4, 5, 6, 7, 9, 14], rsi_lo=[3, 5, 8, 10, 12, 15, 18, 20, 25], htf=[0, 0, 60, 240], htf_len=[20, 50, 100, 200])),
    'VWAP_REV': (f_vwap, dict(vwap_z=[0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0])),
    'ZSCORE_MR': (f_zscore, dict(z_len=[10, 20, 30, 50, 75, 100, 200], z_th=[1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5])),
    'CONSEC_FADE': (f_consec, dict(n_bars=[2, 3, 4, 5, 6, 7, 8])),
    'STOCH_X': (f_stoch, dict(st_len=[5, 7, 9, 14, 21, 30], st_lo=[5, 10, 15, 20, 25, 30, 35])),
    'EMA_PULLBACK': (f_ema_pullback, dict(ema_fast=[5, 9, 13, 21, 34, 50], ema_slow=[50, 75, 100, 150, 200, 300])),
    'DONCHIAN_BO': (f_donchian, dict(dc_len=[5, 10, 15, 20, 30, 40, 55, 100])),
    'DONCHIAN_FADE': (f_donchian_fade, dict(dc_len=[5, 10, 15, 20, 30, 40, 55, 100])),
    'MACD_X': (f_macd, dict(macd_f=[5, 6, 8, 12, 16], macd_s=[13, 17, 21, 26, 35, 50])),
    'KELTNER_REV': (f_keltner_rev, dict(kc_len=[10, 20, 30, 50], kc_k=[1.0, 1.5, 2.0, 2.5, 3.0])),
}

COMMON = dict(
    tf=[1, 3, 5, 10, 15, 20, 30],
    trend=['none', 'with', 'against'],
    trend_len=[50, 75, 100, 150, 200, 300, 400],
    side=['both'],  # só setups simétricos (compra e venda) -> sem apostar na direção do mercado
    sl_mode=['usd', 'atr'],
    sl_usd=[100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 900, 1000, 1200, 1400, 1600, 2000],
    tp_usd=[40, 60, 80, 100, 125, 150, 175, 200, 250, 300, 400, 500, 600, 800, 1200],
    sl_atr=[0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0],
    tp_atr=[0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0],
    max_hold=[15, 30, 45, 60, 90, 120, 150, 180, 240, 360, 480],
    be_frac=[0.0, 0.0, 0.4, 0.5, 0.6, 0.7, 0.8],
    hours=['all', 'eu', 'us', 'eu_us', 'asia', 'no_asia'],
    weekend=['yes', 'no'],
    guard_mode=[0, 0, 1, 2],
    guard_pause_h=[4, 12, 24],
    atr_min=[0, 0, 0.5, 0.75, 1.0, 1.25],   # filtro de volatilidade: ATR/ATR média(100) mínimo
)

HOURS = {
    'all': set(range(24)),
    'asia': set(range(0, 7)),
    'eu': set(range(7, 13)),
    'us': set(range(13, 21)),
    'eu_us': set(range(7, 21)),
    'no_asia': set(range(7, 24)),
}


def htf_filter(df, tf, p):
    """Filtro de tendência num timeframe superior (última vela HTF já fechada)."""
    htf = p.get('htf', 0)
    if not htf:
        return None
    n = p.get('htf_len', 50)
    def build():
        H = tf_frame(htf)
        e = ema(H['close'], n).values
        c = H['close'].values
        h_end = H.index.values.astype('datetime64[s]').astype(np.int64) + htf * 60
        t_end = df.index.values.astype('datetime64[s]').astype(np.int64) + tf * 60
        j = np.searchsorted(h_end, t_end, side='right') - 1
        ok = j >= 0
        jj = np.clip(j, 0, len(c) - 1)
        up = ok & (c[jj] > e[jj])
        dn = ok & (c[jj] < e[jj])
        return up, dn
    return cached(tf, ('htf', htf, n), build)


def build_signals(p):
    """Devolve arrays (idx_1m, dir, sl_usd, tp_usd) prontos para o simulador."""
    tf = p['tf']
    df = tf_frame(tf)
    fn = FAMILIES[p['family']][0]
    lg, sh = fn(df, tf, p)
    lg = np.asarray(lg, bool).copy()
    sh = np.asarray(sh, bool).copy()
    tl, ts_ = trend_filter(df, tf, p)
    lg &= tl
    sh &= ts_
    hf = htf_filter(df, tf, p)
    if hf is not None:
        if p.get('htf_mode', 'with') == 'with':
            lg &= hf[0]; sh &= hf[1]
        else:
            lg &= hf[1]; sh &= hf[0]
    if p['side'] == 'long':
        sh[:] = False
    elif p['side'] == 'short':
        lg[:] = False
    hrs = HOURS[p['hours']]
    hm = np.isin(df['hour'].values, list(hrs))
    if p.get('weekend', 'yes') == 'no':
        hm &= df['dow'].values < 5
    lg &= hm
    sh &= hm
    a = df['atr14'].values
    if p.get('atr_min', 0) > 0:
        am = cached(tf, ('atrm',), lambda: pd.Series(a).rolling(100).mean().values)
        vm = a / am >= p['atr_min']
        lg &= vm
        sh &= vm
    lg &= ~np.isnan(a)
    sh &= ~np.isnan(a)
    sig = lg | sh
    # ignora sinais nas primeiras 400 velas (aquecimento de indicadores)
    sig[:400] = False
    pos = np.nonzero(sig)[0]
    idx = df['entry_idx'].values[pos].astype(np.int64)
    d = np.where(lg[pos], 1, -1).astype(np.int64)
    if p['sl_mode'] == 'usd':
        sl = np.full(len(pos), float(p['sl_usd']))
        tp = np.full(len(pos), float(p['tp_usd']))
    else:
        sl = a[pos] * p['sl_atr']
        tp = a[pos] * p['tp_atr']
        sl = np.maximum(sl, 30.0)
        tp = np.maximum(tp, 20.0)
    if p.get('tp_floor_pct', 0):
        # TP mínimo em % do preço (protege contra TPs minúsculos face ao spread)
        px = df['close'].values[pos]
        tp = np.maximum(tp, px * p['tp_floor_pct'] / 100.0)
    return idx, d, sl, tp
