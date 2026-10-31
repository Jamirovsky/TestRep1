"""Teste de transferência: aplica a outros pares EXATAMENTE os parâmetros escolhidos no BTC
(WFO: a sequência de parâmetros por janela da corrida representativa; FIXO: os parâmetros fixos)."""
import json, numpy as np, pandas as pd
from engine import load, run, Ind, S
from strategies import STRATS
from wfo import seq_metrics

PICKS = [('swing', '15m', 24, 3, 'rob'), ('connors', '15m', 24, 3, 'pf'), ('willr', '15m', 24, 6, 'rob'),
         ('cluc', '15m', 24, 3, 'pf'), ('bbrsi', '15m', 24, 6, 'pf'), ('downbars', '15m', 36, 3, 'rob'),
         ('binh', '15m', 24, 3, 'pf'), ('stoch', '1h', 36, 6, 'pf')]
FIXED = {'stpull_4h_24': ('stpull', '4h'), 'ibs_4h_26': ('ibs', '4h')}
FWD0 = pd.Timestamp('2025-07-01')
d = pd.read_csv(f'{S}/wfo_all.csv')
key = ['strat', 'tf', 'train_m', 'step', 'smode']


def rep_log(k):
    q = d.merge(pd.DataFrame([dict(zip(key, k))]), on=key)
    q = q.assign(dist=(q.wfo_pf - q.wfo_pf.median()).abs()).sort_values(['dist', 'wfo_pf'])
    return json.loads(q.iloc[0].log)


def segs(t, r, mae, start):
    k = t >= np.datetime64(start); f = t >= np.datetime64(FWD0)
    return seq_metrics(r[k], mae[k]), seq_metrics(r[f], mae[f])


def yearly(t, r, mae):
    out = {}
    for y in range(2018, 2027):
        k = (t >= np.datetime64(f'{y}-01-01')) & (t < np.datetime64(f'{y + 1}-01-01'))
        if k.sum(): m = seq_metrics(r[k], mae[k]); out[y] = [m['trades'], round(m['winrate'], 1), round(min(m['pf'], 99), 2)]
    return out


rows = []
for sym in ['BTC', 'ETH', 'SOL', 'XRP']:
    cache = {}
    for k in PICKS:
        name, tf, tm, step, sm = k
        if tf not in cache: cache[tf] = (load(tf, sym), None)
        df = cache[tf][0]; I = Ind(df); fn = STRATS[name][0]
        R = []; M = []; T = []
        for ts, ps in rep_log(k):
            if not ps: continue
            ts = pd.Timestamp(ts); te = ts + pd.DateOffset(months=step)
            sig = fn(I, json.loads(ps))
            m, r, ti, to, mae = run(df, sig, str(ts - pd.DateOffset(days=5)), str(te + pd.DateOffset(days=10)), tf, full_out=True)
            t = df.index[ti].values; msk = (t >= np.datetime64(ts)) & (t < np.datetime64(te))
            R += list(r[msk]); M += list(mae[msk]); T += list(t[msk])
        r = np.array(R); mae = np.array(M); t = np.array(T, dtype='datetime64[ns]')
        o, f = segs(t, r, mae, '2021-01-01')
        rows.append(dict(sym=sym, strat=name, tf=tf, kind='WFO-transfer', **{'all_' + a: b for a, b in o.items()},
                         **{'fwd_' + a: b for a, b in f.items()}, yearly=json.dumps(yearly(t, r, mae))))
    fw = pd.read_csv(f'{S}/forward.csv')
    for rid, (name, tf) in FIXED.items():
        p = json.loads(fw[fw.id == rid].iloc[0].params)
        if tf not in cache: cache[tf] = (load(tf, sym), None)
        df = cache[tf][0]; I = Ind(df); sig = STRATS[name][0](I, p)
        m, r, ti, to, mae = run(df, sig, '2018-01-01', '2026-12-31', tf, full_out=True)
        t = df.index[ti].values
        o, f = segs(t, r, mae, '2018-01-01')
        rows.append(dict(sym=sym, strat=name, tf=tf, kind='FIXO', **{'all_' + a: b for a, b in o.items()},
                         **{'fwd_' + a: b for a, b in f.items()}, yearly=json.dumps(yearly(t, r, mae))))
    print(sym, 'done', flush=True)
out = pd.DataFrame(rows)
ok = lambda p, n: (out[p + '_trades'] > n) & (out[p + '_winrate'] >= 57) & (out[p + '_pf'] >= 1.05) & (out[p + '_maxdd'] < 20)
out['pass_all'] = ok('all', 100); out['pass_fwd'] = ok('fwd', 14)
out.to_csv(f'{S}/xtransfer.csv', index=False)
pd.set_option('display.width', 250)
print(out[['sym', 'strat', 'tf', 'kind', 'all_trades', 'all_winrate', 'all_pf', 'all_maxdd', 'all_ret', 'fwd_trades', 'fwd_winrate', 'fwd_pf', 'fwd_maxdd', 'pass_all', 'pass_fwd']].round(2).to_string())
