"""Seleção final em 3 fases:
  IS  (backtest/otimização): 2018-01-01 .. 2023-12-31
  VAL (validação/seleção):   2024-01-01 .. 2025-06-30
  FWD (forward test holdout):2025-07-01 .. 2026-10-31  -> nunca usado na seleção
"""
import sys, json, numpy as np, pandas as pd
from multiprocessing import Pool
from engine import load, run, Ind, IS_START, IS_END, S
from strategies import STRATS
from optimize import passes
from refine import neighbors, space_of

VAL = ('2024-01-01', '2025-06-30 23:59'); FWD = ('2025-07-01', '2026-12-31')


def ok(m, nmin):
    return m['trades'] >= nmin and m['winrate'] >= 57 and m['pf'] >= 1.05 and m['maxdd'] < 20


def stage1(args):
    """validação para lista de parâmetros de uma (strat, tf)"""
    name, tf, plist = args
    df = load(tf); I = Ind(df); fn = STRATS[name][0]; out = []
    for ps in plist:
        p = json.loads(ps); sig = fn(I, p)
        v = run(df, sig, *VAL, tf)[0]
        if not ok(v, 20): continue
        nb = neighbors(p, space_of(name)); good = 0
        for q in nb:
            sq = fn(I, q)
            mi = run(df, sq, IS_START, IS_END, tf)[0]; mv = run(df, sq, *VAL, tf)[0]
            good += passes(mi) and ok(mv, 15)
        out.append(dict(strat=name, tf=tf, params=ps, stab=good / max(1, len(nb)),
                        **{'val_' + k: x for k, x in v.items()}))
    return out


if __name__ == '__main__':
    d = pd.concat([pd.read_csv(f'{S}/res_{t}.csv') for t in ('r3', 'r4')]).drop_duplicates(['strat', 'tf', 'params'])
    d = d[d.is_pass & (d.rob > 1)]
    print('IS robust candidates', len(d))
    jobs = [(n, tf, list(g.params)) for (n, tf), g in d.groupby(['strat', 'tf'])]
    # dividir trabalhos grandes
    jj = []
    for n, tf, pl in jobs:
        for i in range(0, len(pl), 25): jj.append((n, tf, pl[i:i + 25]))
    with Pool(4) as pool:
        res = [r for rr in pool.imap_unordered(stage1, jj) for r in rr]
    v = pd.DataFrame(res).merge(d, on=['strat', 'tf', 'params'])
    v.to_csv(f'{S}/val_stage.csv', index=False)
    print('VAL pass', len(v))
