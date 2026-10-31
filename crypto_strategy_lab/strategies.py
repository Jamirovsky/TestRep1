"""Famílias de estratégias (inspiradas em repositórios freqtrade-strategies, Connors, etc.)
Cada função recebe (I: Ind, p: dict) e devolve dict de sinal para engine.run."""
import numpy as np, pandas as pd
from engine import cross_up, cross_dn

# espaço de saída comum
EXIT_SPACE = dict(
    xmode=['atr', 'pct'],
    tp_k=[0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],      # múltiplos ATR  | pct -> /100*?
    sl_k=[1.0, 1.5, 2.0, 3.0, 4.0, 6.0],
    maxbars=[0, 12, 24, 48, 96],
    trail=[0, 0, 0.5, 1.0],                       # em ATR (convertido abaixo)
    dtrend=[0, 0, 20, 50, 100, 200],              # filtro de tendência em dias (SMA diária)
    minvol=[0, 0, 3, 5, 8],                       # ATR >= minvol x custo ida-e-volta
)
PCT_TP = {0: 0, 0.5: 0.005, 0.75: 0.0075, 1.0: 0.01, 1.5: 0.015, 2.0: 0.02, 3.0: 0.03}
PCT_SL = {1.0: 0.01, 1.5: 0.015, 2.0: 0.02, 3.0: 0.03, 4.0: 0.05, 6.0: 0.08}


def exits(I, p, sig):
    c = I.df.close
    if p['xmode'] == 'atr':
        a = I.atr(14) / c
        sig['tp'] = (p['tp_k'] * a).values if p['tp_k'] > 0 else 0.0
        sig['sl'] = (p['sl_k'] * a).values
        if p['trail'] > 0:
            med = float(a.median())
            sig['trail'] = p['trail'] * med; sig['trail_act'] = p['trail'] * med
    else:
        sig['tp'] = PCT_TP[p['tp_k']]; sig['sl'] = PCT_SL[p['sl_k']]
        if p['trail'] > 0:
            sig['trail'] = 0.005 * p['trail']; sig['trail_act'] = 0.01 * p['trail']
    sig['maxbars'] = p['maxbars']
    mv = p.get('minvol', 0)
    if mv:
        from engine import COST
        sig['entry'] = sig['entry'] & ((I.atr(14) / I.df.close) >= mv * 2 * COST)
    dt = p.get('dtrend', 0)
    if dt:
        m = I.sma(int(dt * I.bpd)); c = I.df.close
        sig['entry'] = sig['entry'] & ((c > m) if sig['dir'] == 1 else (c < m))
    return sig


def trend_ok(I, n, side):
    if n == 0:
        return True
    m = I.sma(n)
    return (I.df.close > m) if side == 1 else (I.df.close < m)


def bb(I, n, k):
    m = I.sma(n); s = I.std(n)
    return m - k * s, m, m + k * s


# ---------------------------------------------------------------------------
def s_bbrsi(I, p):          # freqtrade BbandRsi
    c = I.df.close; r = I.rsi(p['rsi_n']); lo, mid, up = bb(I, p['bb_n'], p['bb_k'])
    sd = p['side']
    if sd == 1:
        e = (r < p['rsi_lo']) & (c < lo) & trend_ok(I, p['trend'], 1)
        x = (r > p['rsi_x']) | ((c > mid) & p['x_mid'])
    else:
        e = (r > 100 - p['rsi_lo']) & (c > up) & trend_ok(I, p['trend'], -1)
        x = (r < 100 - p['rsi_x']) | ((c < mid) & p['x_mid'])
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_bbrsi = dict(side=[1, -1], rsi_n=[2, 3, 7, 14], rsi_lo=[10, 15, 20, 25, 30, 35], bb_n=[20, 40],
                bb_k=[1.5, 2.0, 2.5], rsi_x=[50, 60, 70, 80], x_mid=[True, False],
                trend=[0, 0, 50, 100, 200])


def s_connors(I, p):        # Larry Connors RSI(2)
    c = I.df.close; r = I.rsi(p['rsi_n']); sd = p['side']
    if sd == 1:
        e = (r < p['lo']) & trend_ok(I, p['trend'], 1)
        x = c > I.sma(p['xn'])
    else:
        e = (r > 100 - p['lo']) & trend_ok(I, p['trend'], -1)
        x = c < I.sma(p['xn'])
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_connors = dict(side=[1, -1], rsi_n=[2, 3, 4], lo=[2, 5, 10, 15, 20, 25], trend=[0, 50, 100, 200, 400],
                  xn=[3, 5, 7, 10])


def s_ibs(I, p):            # Internal Bar Strength
    d = I.df; ibs = (d.close - d.low) / (d.high - d.low).replace(0, np.nan); sd = p['side']
    if sd == 1:
        e = (ibs < p['lo']) & trend_ok(I, p['trend'], 1) & (d.close < d.close.shift(p['lb']))
        x = (ibs > p['hi']) | (d.close > d.high.shift())
    else:
        e = (ibs > 1 - p['lo']) & trend_ok(I, p['trend'], -1) & (d.close > d.close.shift(p['lb']))
        x = (ibs < 1 - p['hi']) | (d.close < d.low.shift())
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_ibs = dict(side=[1, -1], lo=[0.05, 0.1, 0.15, 0.2, 0.25], hi=[0.6, 0.7, 0.8, 0.9], trend=[0, 50, 100, 200],
              lb=[1, 3, 5, 10])


def s_zscore(I, p):
    c = I.df.close; z = (c - I.sma(p['n'])) / I.std(p['n']); sd = p['side']
    if sd == 1:
        e = (z < -p['k']) & trend_ok(I, p['trend'], 1); x = z > p['xz']
    else:
        e = (z > p['k']) & trend_ok(I, p['trend'], -1); x = z < -p['xz']
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_zscore = dict(side=[1, -1], n=[10, 20, 30, 50, 100], k=[1.5, 2.0, 2.5, 3.0], xz=[-0.5, 0, 0.5, 1.0],
                 trend=[0, 100, 200, 400])


def s_cluc(I, p):           # ClucMay72018 / CombinedBinHAndCluc (perna Cluc)
    d = I.df; lo, mid, up = bb(I, 20, 2.0); es = I.ema(p['ema'])
    e = (d.close < es) & (d.close < p['k'] * lo) & (d.volume < I.volm(30).shift() * p['vm'])
    if p['trend'] > 0:
        e &= d.close > I.sma(p['trend']) * p['tr_tol']
    x = d.close > mid
    return exits(I, p, dict(entry=e, exit=x, dir=1))
SP_cluc = dict(ema=[20, 50, 100], k=[0.97, 0.98, 0.985, 0.99, 1.0], vm=[2, 5, 20], trend=[0, 200, 400],
               tr_tol=[0.9, 0.95, 1.0])


def s_binh(I, p):           # BinHV45
    d = I.df; m = I.sma(40); s = I.std(40); lower = m - 2 * s
    bbdelta = (m - lower).abs(); cd = (d.close - d.close.shift()).abs(); tail = (d.close - d.low).abs()
    e = (lower.shift() > 0) & (bbdelta > d.close * p['a']) & (cd > d.close * p['b']) & \
        (tail < bbdelta * p['t']) & (d.close < lower.shift()) & (d.close <= d.close.shift())
    e &= trend_ok(I, p['trend'], 1)
    x = d.close > m
    return exits(I, p, dict(entry=e, exit=x, dir=1))
SP_binh = dict(a=[0.004, 0.008, 0.012, 0.02], b=[0.005, 0.0087, 0.0125, 0.0175], t=[0.25, 0.5, 0.75],
               trend=[0, 200])


def s_swing(I, p):          # SwingHighToSky (CCI + RSI)
    cc = I.cci(p['cn']); r = I.rsi(p['rn']); sd = p['side']
    if sd == 1:
        e = (cc < -p['cl']) & (r < p['rl']) & trend_ok(I, p['trend'], 1)
        x = (cc > p['cx']) & (r > p['rx'])
    else:
        e = (cc > p['cl']) & (r > 100 - p['rl']) & trend_ok(I, p['trend'], -1)
        x = (cc < -p['cx']) & (r < 100 - p['rx'])
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_swing = dict(side=[1, -1], cn=[14, 20, 30, 50], rn=[7, 14, 21], cl=[100, 150, 200, 250], rl=[20, 25, 30, 35, 40],
                cx=[0, 50, 100, 150], rx=[50, 60, 70], trend=[0, 100, 200])


def s_stoch(I, p):          # cruzamento estocástico em sobrevenda + tendência
    k, dd = I.stoch(p['n']); sd = p['side']
    if sd == 1:
        e = cross_up(k, dd) & (k < p['lv']) & trend_ok(I, p['trend'], 1); x = k > p['xv']
    else:
        e = cross_dn(k, dd) & (k > 100 - p['lv']) & trend_ok(I, p['trend'], -1); x = k < 100 - p['xv']
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_stoch = dict(side=[1, -1], n=[5, 9, 14, 21], lv=[10, 15, 20, 25, 30], xv=[60, 70, 80, 90], trend=[0, 50, 100, 200])


def s_willr(I, p):
    w = I.willr(p['n']); sd = p['side']
    if sd == 1:
        e = (w < -100 + p['lv']) & trend_ok(I, p['trend'], 1); x = w > -p['xv']
    else:
        e = (w > -p['lv']) & trend_ok(I, p['trend'], -1); x = w < -100 + p['xv']
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_willr = dict(side=[1, -1], n=[2, 5, 10, 14, 20], lv=[2, 5, 10, 15, 20], xv=[10, 20, 30, 50], trend=[0, 50, 100, 200])


def s_downbars(I, p):       # N velas consecutivas contra a tendência
    c = I.df.close; sd = p['side']
    dn = (c < c.shift()).astype(int); up = (c > c.shift()).astype(int)
    if sd == 1:
        e = (dn.rolling(p['n']).sum() == p['n']) & trend_ok(I, p['trend'], 1)
        x = c > I.df.high.shift()
    else:
        e = (up.rolling(p['n']).sum() == p['n']) & trend_ok(I, p['trend'], -1)
        x = c < I.df.low.shift()
    return exits(I, p, dict(entry=e, exit=x if p['xsig'] else pd.Series(False, c.index), dir=sd))
SP_downbars = dict(side=[1, -1], n=[3, 4, 5, 6, 7], trend=[0, 50, 100, 200], xsig=[True, False])


def s_scalp(I, p):          # SmoothScalp
    d = I.df; el = d.low.ewm(span=5, adjust=False).mean(); eh = d.high.ewm(span=5, adjust=False).mean()
    k, dd = I.stoch(5); a, _, _ = I.adx(14)
    e = (d.open < el) & (a > p['adx']) & (I.mfi(14) < p['mfi']) & (k < p['kl']) & (dd < p['kl']) & \
        cross_up(k, dd) & (I.cci(20) < -p['cci'])
    e &= trend_ok(I, p['trend'], 1)
    x = (d.open >= eh) | ((k > 70) & (I.cci(20) > p['cci']))
    return exits(I, p, dict(entry=e, exit=x, dir=1))
SP_scalp = dict(adx=[0, 20, 25, 30], mfi=[20, 30, 40], kl=[20, 30, 40], cci=[50, 100, 150], trend=[0, 100, 200])


def s_keltner(I, p):        # reversão a partir do canal de Keltner
    c = I.df.close; m = I.ema(p['n']); a = I.atr(p['n']); sd = p['side']
    if sd == 1:
        e = (c < m - p['k'] * a) & trend_ok(I, p['trend'], 1); x = c > m
    else:
        e = (c > m + p['k'] * a) & trend_ok(I, p['trend'], -1); x = c < m
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_keltner = dict(side=[1, -1], n=[10, 20, 30, 50], k=[1.5, 2.0, 2.5, 3.0], trend=[0, 100, 200, 400])


def s_stpull(I, p):         # Supertrend + pullback RSI
    st = I.st(p['stn'], p['stm']); r = I.rsi(p['rn']); sd = p['side']
    if sd == 1:
        e = (st == 1) & (r < p['lo'])
    else:
        e = (st == -1) & (r > 100 - p['lo'])
    x = st != sd
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_stpull = dict(side=[1, -1], stn=[10, 14, 20], stm=[2.0, 3.0, 4.0], rn=[2, 3, 5, 14], lo=[10, 20, 30, 40])


def s_hlhb(I, p):           # hlhb (tendência, EMA5/10 + RSI + ADX)
    d = I.df; hl2 = (d.close + d.open) / 2
    r = I.get(('rsihl', p['rn']), lambda: __import__('engine').rsi(hl2, p['rn']))
    e5 = I.ema(p['f']); e10 = I.ema(p['s']); a, _, _ = I.adx(14); sd = p['side']
    if sd == 1:
        e = cross_up(e5, e10) & (r > 50) & (a > p['adx']) & trend_ok(I, p['trend'], 1)
        x = cross_dn(e5, e10)
    else:
        e = cross_dn(e5, e10) & (r < 50) & (a > p['adx']) & trend_ok(I, p['trend'], -1)
        x = cross_up(e5, e10)
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_hlhb = dict(side=[1, -1], rn=[10, 14], f=[5, 9], s=[10, 21], adx=[20, 25, 30], trend=[0, 200])


def s_combo(I, p):          # combinação (reverse-engineering dos melhores: RSI+MFI+BB+ADX regime)
    d = I.df; r = I.rsi(p['rn']); lo, mid, up = bb(I, 20, p['bbk']); a, pdi, mdi = I.adx(14); mf = I.mfi(14)
    sd = p['side']
    regime = a < p['adx_max']                     # mercado sem tendência forte -> reversão funciona melhor
    if sd == 1:
        e = (r < p['rl']) & (d.close < lo) & (mf < p['ml']) & regime & trend_ok(I, p['trend'], 1)
        x = d.close > mid
    else:
        e = (r > 100 - p['rl']) & (d.close > up) & (mf > 100 - p['ml']) & regime & trend_ok(I, p['trend'], -1)
        x = d.close < mid
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_combo = dict(side=[1, -1], rn=[3, 7, 14], rl=[15, 20, 25, 30, 35], bbk=[1.5, 2.0, 2.5], ml=[20, 30, 40, 100],
                adx_max=[20, 25, 30, 40, 100], trend=[0, 100, 200])


def s_binhatr(I, p):        # BinHV45 reverse-engineered: limiares normalizados por ATR (adaptam ao regime de volatilidade)
    d = I.df; n = p['bbn']; m = I.sma(n); s = I.std(n); lower = m - p['bbk'] * s; upper = m + p['bbk'] * s
    a = I.atr(14); cd = (d.close - d.close.shift()).abs(); sd = p['side']
    if sd == 1:
        tail = (d.close - d.low).abs()
        e = (cd > p['b'] * a) & (tail < p['t'] * a) & (d.close < lower.shift()) & (d.close <= d.close.shift())
        x = d.close > m
    else:
        tail = (d.high - d.close).abs()
        e = (cd > p['b'] * a) & (tail < p['t'] * a) & (d.close > upper.shift()) & (d.close >= d.close.shift())
        x = d.close < m
    e &= (2 * p['bbk'] * s) > p['a'] * a
    e &= trend_ok(I, p['trend'], sd)
    return exits(I, p, dict(entry=e, exit=x if p['xmid'] else pd.Series(False, d.index), dir=sd))
SP_binhatr = dict(side=[1, 1, -1], bbn=[20, 40], bbk=[2.0, 2.5], a=[1, 2, 3, 4], b=[1.0, 1.5, 2.0, 2.5, 3.0],
                  t=[0.1, 0.25, 0.5], trend=[0, 200], xmid=[True, False])


def s_capit(I, p):          # capitulação / blow-off: vela de range extremo + volume + RSI extremo
    d = I.df; a = I.atr(p['an']); rng_ = d.high - d.low; vm = I.volm(p['vn']); r = I.rsi(p['rn']); sd = p['side']
    big = (rng_ > p['k'] * a.shift()) & (d.volume > p['v'] * vm.shift())
    pos = (d.close - d.low) / rng_.replace(0, np.nan)
    if sd == 1:
        e = big & (d.close < d.open) & (r < p['rl']) & (pos > p['wick'])
        x = d.close > I.ema(p['xe'])
    else:
        e = big & (d.close > d.open) & (r > 100 - p['rl']) & (pos < 1 - p['wick'])
        x = d.close < I.ema(p['xe'])
    e &= trend_ok(I, p['trend'], sd)
    return exits(I, p, dict(entry=e, exit=x, dir=sd))
SP_capit = dict(side=[1, 1, -1], an=[14, 50], vn=[20, 50], rn=[3, 7, 14], k=[1.5, 2.0, 2.5, 3.0], v=[1.0, 1.5, 2.0, 3.0],
                rl=[20, 25, 30, 40, 100], wick=[0.0, 0.2, 0.35], xe=[5, 10, 20], trend=[0, 200])


STRATS = {k[2:]: (v, globals()['SP_' + k[2:]]) for k, v in list(globals().items()) if k.startswith('s_')}
