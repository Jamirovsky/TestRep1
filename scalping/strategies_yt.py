"""
Estratégias adaptadas de ideias públicas do canal Chart Fanatics e de campeões do
World Cup Trading Championship (Larry Williams, Andrea Unger), traduzidas para BTCUSD
em velas OHLC (sem order flow / footprint, que não existem nestes dados).

Cada família devolve (long, short, extra), onde extra pode ter:
  stop_l / stop_s : preço do stop estrutural (ex.: extremo do varrimento)
  tgt_l / tgt_s   : preço-alvo (ex.: VWAP)
Os sinais são avaliados no FECHO da vela; a entrada é na abertura seguinte.
"""
import numpy as np
import pandas as pd

from .strategies import FAMILIES, cached, ema, session_vwap


# ------------------------------------------------------------------ utilitários
def _day_feats(df, tf):
    def build():
        idx = df.index
        day = idx.floor('D')
        g = df.groupby(day)
        d = g.agg(o=('open', 'first'), h=('high', 'max'), l=('low', 'min'), c=('close', 'last'))
        prev = d.shift(1)
        rng = (d.h - d.l)
        avg10 = rng.shift(1).rolling(10).mean()
        m = lambda s: s.reindex(day).values
        hour = idx.hour.values
        run_h = g['high'].cummax().values
        run_l = g['low'].cummin().values
        def sess(h0, h1):
            mask = (hour >= h0) & (hour < h1)
            sh = pd.Series(np.where(mask, df['high'].values, np.nan), index=idx).groupby(day).transform('max').values
            sl = pd.Series(np.where(mask, df['low'].values, np.nan), index=idx).groupby(day).transform('min').values
            valid = hour >= h1  # só depois de a sessão terminar
            return np.where(valid, sh, np.nan), np.where(valid, sl, np.nan)
        asia_h, asia_l = sess(0, 7)
        lon_h, lon_l = sess(7, 13)
        return dict(day=day.values, pdh=m(prev.h), pdl=m(prev.l), prange=m(prev.h - prev.l),
                    dopen=m(d.o), run_h=run_h, run_l=run_l, asia_h=asia_h, asia_l=asia_l,
                    lon_h=lon_h, lon_l=lon_l, pr_avg10=m(avg10))
    return cached(tf, ('dayfeats',), build)


def _first_per_day(cond, day):
    cond = np.asarray(cond, bool)
    prev = np.concatenate([[False], cond[:-1]])
    cross = cond & ~prev
    cs = pd.Series(cross.astype(int)).groupby(day).cumsum().values
    return cross & (cs == 1)


def _crossed_up(x, lvl):
    xp = np.concatenate([[np.nan], x[:-1]])
    lp = np.concatenate([[np.nan], lvl[:-1]])
    return (x > lvl) & (xp <= lp)


def _crossed_dn(x, lvl):
    xp = np.concatenate([[np.nan], x[:-1]])
    lp = np.concatenate([[np.nan], lvl[:-1]])
    return (x < lvl) & (xp >= lp)


def adx(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    up = h.diff(); dn = -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = 1 / n
    atr_ = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=a, adjust=False).mean() / atr_
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=a, adjust=False).mean() / atr_
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean().fillna(0).values


def _rmin(x, w):
    return pd.Series(x).rolling(w, min_periods=1).min().values


def _rmax(x, w):
    return pd.Series(x).rolling(w, min_periods=1).max().values


# ------------------------------------------------------------------ Chart Fanatics
def f_cf_liq_raid(df, tf, p):
    """Kyle Ng / Jadecap (Chart Fanatics): varrimento de liquidez (máx/mín do dia anterior e
    das sessões Ásia/Londres) seguido de 'market structure shift' (fecho acima da máxima da
    vela anterior). Stop no extremo do varrimento."""
    F = _day_feats(df, tf)
    k = p['conf_bars']
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    lows = [F['pdl']] + ([F['asia_l'], F['lon_l']] if p['levels'] == 'pd_sess' else [])
    highs = [F['pdh']] + ([F['asia_h'], F['lon_h']] if p['levels'] == 'pd_sess' else [])
    wl = _rmin(l, k + 1); wh = _rmax(h, k + 1)
    hp = np.concatenate([[np.nan], h[:-1]]); lp = np.concatenate([[np.nan], l[:-1]])
    lg = np.zeros(len(c), bool); sh = np.zeros(len(c), bool)
    for L in lows:
        lg |= (wl < L) & (c > L) & (c > hp)
    for H in highs:
        sh |= (wh > H) & (c < H) & (c < lp)
    return lg, sh, dict(stop_l=wl, stop_s=wh)


def f_cf_ifvg(df, tf, p):
    """Josh (IFVG model, Chart Fanatics): varrimento de mínimos/máximos recentes e depois
    fecho através de um fair value gap contrário (inversão do FVG)."""
    W, N = p['ifvg_win'], p['sweep_len']
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    l2 = np.concatenate([[np.nan, np.nan], l[:-2]]); h2 = np.concatenate([[np.nan, np.nan], h[:-2]])
    bear_top = pd.Series(np.where(l2 > h, l2, np.nan)).ffill(limit=W).values   # FVG de baixa
    bull_bot = pd.Series(np.where(h2 < l, h2, np.nan)).ffill(limit=W).values   # FVG de alta
    wl = _rmin(l, W); wh = _rmax(h, W)
    prior_l = pd.Series(l).shift(W).rolling(N, min_periods=1).min().values
    prior_h = pd.Series(h).shift(W).rolling(N, min_periods=1).max().values
    lg = _crossed_up(c, bear_top) & (wl < prior_l)
    sh = _crossed_dn(c, bull_bot) & (wh > prior_h)
    return lg, sh, dict(stop_l=wl, stop_s=wh)


def f_cf_fabio(df, tf, p):
    """Fabio Valentini (Chart Fanatics, Auction Market): modelo de reversão (sai das bandas do
    VWAP e volta para dentro -> alvo VWAP) ou de tendência (pullback ao VWAP a favor da
    inclinação). Order flow aproximado por velas."""
    vw = cached(tf, ('vwap',), lambda: session_vwap(df).values)
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    if p['fab_model'] == 'mr':
        n, k = p['band_len'], p['band_k']
        sd = cached(tf, ('vwsd', n), lambda: pd.Series(c - vw).rolling(n).std().values)
        lo, hi = vw - k * sd, vw + k * sd
        lg = _crossed_up(c, lo); sh = _crossed_dn(c, hi)
        return lg, sh, dict(stop_l=_rmin(l, 3), stop_s=_rmax(h, 3), tgt_l=vw, tgt_s=vw)
    m = p['slope_len']
    slope = vw - np.concatenate([np.full(m, np.nan), vw[:-m]])
    lg = (slope > 0) & (l <= vw) & (c > vw)
    sh = (slope < 0) & (h >= vw) & (c < vw)
    return lg, sh, dict(stop_l=l, stop_s=h)


def f_cf_round(df, tf, p):
    """Okala 80/20 (Chart Fanatics): reação a níveis 'redondos'. Em BTC usa-se uma grelha de
    níveis com espaçamento ~step_pct do preço (arredondado a 1-2-5); vende-se a rejeição de um
    nível por cima e compra-se a rejeição por baixo."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    raw = c * p['step_pct'] / 100.0
    mag = 10 ** np.floor(np.log10(np.maximum(raw, 1e-9)))
    r = raw / mag
    step = np.where(r < 1.5, 1, np.where(r < 3.5, 2, np.where(r < 7.5, 5, 10))) * mag
    cp = np.concatenate([[np.nan], c[:-1]])
    above = np.ceil(cp / step) * step     # nível acima do fecho anterior
    below = np.floor(cp / step) * step
    sh = (h >= above) & (c < above) & (cp < above)
    lg = (l <= below) & (c > below) & (cp > below)
    return lg, sh, dict(stop_l=l, stop_s=h)


# ------------------------------------------------------------------ World Cup Trading Championship
def f_wc_williams_vb(df, tf, p):
    """Larry Williams (campeão WCTC 1987): volatility breakout - compra quando o preço passa
    abertura do dia + k x amplitude do dia anterior; vende abaixo de abertura - k x amplitude.
    Stop estrutural na abertura do dia."""
    F = _day_feats(df, tf)
    c = df['close'].values
    up = F['dopen'] + p['vb_k'] * F['prange']
    dn = F['dopen'] - p['vb_k'] * F['prange']
    lg = _first_per_day(c > up, F['day']); sh = _first_per_day(c < dn, F['day'])
    return lg, sh, dict(stop_l=F['dopen'], stop_s=F['dopen'])


def f_wc_oops(df, tf, p):
    """Larry Williams 'Oops!': o preço fura a mínima (máxima) do dia anterior e volta para
    dentro -> compra (venda). Stop no extremo do dia."""
    F = _day_feats(df, tf)
    c = df['close'].values
    lg = _first_per_day((F['run_l'] < F['pdl']) & (c > F['pdl']), F['day'])
    sh = _first_per_day((F['run_h'] > F['pdh']) & (c < F['pdh']), F['day'])
    return lg, sh, dict(stop_l=F['run_l'], stop_s=F['run_h'])


def f_wc_unger_pdbo(df, tf, p):
    """Andrea Unger (4x campeão WCTC): rompimento da máxima/mínima do dia anterior dentro de
    uma janela horária, com filtro ADX."""
    F = _day_feats(df, tf)
    c = df['close'].values
    ad = cached(tf, ('adx', 14), lambda: adx(df, 14))
    ok = ad >= p['adx_min']
    lg = _first_per_day(c > F['pdh'], F['day']) & ok
    sh = _first_per_day(c < F['pdl'], F['day']) & ok
    return lg, sh, dict(stop_l=F['pdh'] - 0.5 * F['prange'], stop_s=F['pdl'] + 0.5 * F['prange'])


def f_wc_unger_comp(df, tf, p):
    """Andrea Unger 'compressed candle': depois de um dia de amplitude comprimida
    (< comp x média de 10 dias), opera o rompimento da máxima/mínima desse dia."""
    F = _day_feats(df, tf)
    c = df['close'].values
    comp = F['prange'] < p['comp'] * F['pr_avg10']
    lg = _first_per_day(c > F['pdh'], F['day']) & comp
    sh = _first_per_day(c < F['pdl'], F['day']) & comp
    return lg, sh, dict(stop_l=F['pdl'], stop_s=F['pdh'])


YT_FAMILIES = {
    'CF_LIQ_RAID': (f_cf_liq_raid, dict(levels=['pd', 'pd_sess'], conf_bars=[1, 2, 3, 5, 8])),
    'CF_IFVG': (f_cf_ifvg, dict(ifvg_win=[5, 10, 15, 20], sweep_len=[10, 20, 40, 60])),
    'CF_FABIO': (f_cf_fabio, dict(fab_model=['mr', 'trend'], band_len=[30, 60, 120], band_k=[1.5, 2.0, 2.5, 3.0], slope_len=[3, 6, 12])),
    'CF_ROUND_8020': (f_cf_round, dict(step_pct=[0.1, 0.2, 0.3, 0.5, 1.0])),
    'WC_WILLIAMS_VB': (f_wc_williams_vb, dict(vb_k=[0.25, 0.4, 0.5, 0.6, 0.8, 1.0])),
    'WC_OOPS': (f_wc_oops, dict(dummy=[0])),
    'WC_UNGER_PDBO': (f_wc_unger_pdbo, dict(adx_min=[0, 15, 20, 25, 30])),
    'WC_UNGER_COMP': (f_wc_unger_comp, dict(comp=[0.4, 0.5, 0.6, 0.7, 0.8])),
}
FAMILIES.update(YT_FAMILIES)

# Parâmetros "tal como publicados" (sem otimização), para o teste de base
AS_PUBLISHED = {
    'CF_LIQ_RAID': dict(tf=5, levels='pd_sess', conf_bars=3, hours='us', sl_mode='struct', rr=2.0, sl_buf_atr=0.1, max_hold=240),
    'CF_IFVG': dict(tf=5, ifvg_win=10, sweep_len=20, hours='us', sl_mode='struct', rr=2.0, sl_buf_atr=0.1, max_hold=240),
    'CF_FABIO': dict(tf=5, fab_model='mr', band_len=60, band_k=2.0, slope_len=6, hours='eu', sl_mode='struct', tp_mode='target', rr=1.0, sl_buf_atr=0.25, max_hold=240),
    'CF_ROUND_8020': dict(tf=1, step_pct=0.3, hours='us', sl_mode='struct', rr=1.5, sl_buf_atr=0.25, max_hold=60),
    'WC_WILLIAMS_VB': dict(tf=5, vb_k=0.5, hours='all', sl_mode='struct', rr=1.0, sl_buf_atr=0.0, max_hold=480),
    'WC_OOPS': dict(tf=15, dummy=0, hours='all', sl_mode='struct', rr=1.5, sl_buf_atr=0.1, max_hold=480),
    'WC_UNGER_PDBO': dict(tf=15, adx_min=20, hours='eu_us', sl_mode='atr', sl_atr=2.0, tp_atr=3.0, max_hold=480),
    'WC_UNGER_COMP': dict(tf=15, comp=0.6, hours='all', sl_mode='atr', sl_atr=2.0, tp_atr=3.0, max_hold=480),
}
COMMON_DEFAULTS = dict(trend='none', side='both', be_frac=0.0, weekend='yes', guard_mode=0, atr_min=0)


def published(fam):
    return {'family': fam, **COMMON_DEFAULTS, **AS_PUBLISHED[fam]}
