"""Ensemble definido ex-ante: todas as famílias de reversão à média num timeframe, meta-config WFO fixa,
pesos iguais (1/k do capital por componente)."""
import json, sys, numpy as np, pandas as pd
from engine import S
from wfo import seq_metrics

MR = ['bbrsi', 'connors', 'ibs', 'zscore', 'cluc', 'binh', 'swing', 'stoch', 'willr', 'downbars', 'scalp', 'keltner', 'combo']


def ensemble(d, tf, tm, step=6, smode='pf'):
    q = d[(d.tf == tf) & (d.train_m == tm) & (d.step == step) & (d.smode == smode) & d.strat.isin(MR)]
    q = q.drop_duplicates('strat')
    k = len(q); rows = []
    for r in q.itertuples():
        for t, ret, mae in json.loads(r.trades):
            rows.append((pd.Timestamp(t), ret / k, mae / k, r.strat))
    tr = pd.DataFrame(rows, columns=['t', 'r', 'mae', 's']).sort_values('t')
    m = seq_metrics(tr.r.values, tr.mae.values)
    f = tr.t >= pd.Timestamp('2025-07-01')
    fm = seq_metrics(tr.r.values[f.values], tr.mae.values[f.values])
    return k, m, fm, tr


if __name__ == '__main__':
    d = pd.read_csv(f'{S}/wfo_w1.csv'); d['step'] = 6; d['smode'] = 'pf'
    d = d[d.minpf == 1.1]
    for tf in ['15m', '1h', '4h']:
        for tm in [24, 36]:
            k, m, fm, tr = ensemble(d, tf, tm)
            print(tf, tm, k, {a: round(b, 2) for a, b in m.items()}, '| FWD', {a: round(b, 2) for a, b in fm.items()})
