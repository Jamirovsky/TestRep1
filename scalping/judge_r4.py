"""Ronda 4: seleção robusta (só 2022-26) e juiz 2018-2021 segundo results/REGRA_RONDA4.md."""
import json, sys
from multiprocessing import Pool
import numpy as np
from .search_r4 import evaluate, SPACE, canon4, window
from .backtest import _ts, run
from .engine import metrics


def neighbours(p):
    out = []
    for k, vals in SPACE.items():
        if k not in p or p[k] not in vals or len(vals) < 2:
            continue
        i = vals.index(p[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals) and vals[j] != p[k]:
                q = dict(p); q[k] = vals[j]
                if q.get('lim_atr') and 'lim_win' not in q: q['lim_win'] = 15
                if q.get('guard_mode') == 1: q.setdefault('guard_pause_h', 12)
                if q.get('htf'): q.setdefault('htf_len', 50)
                out.append(canon4(q))
    return out


def ok(m):
    return (m['trades'] > 100 and m['win_rate'] > 0.57 and m['profit_factor'] > 1.01
            and m['max_dd_pct'] <= 20 and m['max_consec_losses'] < 3)


def judge(p, a='2018-01-01', b='2022-01-01', costs=None):
    te, pnl, real, _ = run(p, costs=costs or {'spread_pct': 0.025}, raw=True)
    sel = real & (te >= _ts(a)) & (te < _ts(b))
    return metrics(pnl[sel], 116.0), te[sel], pnl[sel]


def main(path='results/search_r4.jsonl', top_n=150):
    rows = [json.loads(l) for l in open(path)]
    rows = [r for r in rows if ok(r['full'])]
    rows.sort(key=lambda r: -r['score'])
    seen, cands = set(), []
    for r in rows:
        sig = (r['full']['trades'], round(r['full']['ret_pct'], 2))
        if sig in seen: continue
        seen.add(sig); cands.append(r)
        if len(cands) >= top_n: break
    jobs, own = [], []
    for ci, r in enumerate(cands):
        for q in neighbours(r['params']):
            jobs.append(q); own.append(ci)
    with Pool(4) as pool:
        res = pool.map(evaluate, jobs, chunksize=8)
    nb = {}
    for ci, r in zip(own, res):
        nb.setdefault(ci, []).append(r.get('score', -999))
    for ci, r in enumerate(cands):
        r['score_vizinhos'] = float(np.median(nb.get(ci, [r['score']])))
        r['score_robusto'] = 0.4 * r['score'] + 0.6 * r['score_vizinhos']
    cands.sort(key=lambda r: -r['score_robusto'])
    json.dump(cands, open('results/robust_rank_r4.json', 'w'))
    for r in cands[:5]:
        print(round(r['score_robusto'], 1), round(r['score'], 1), r['full'], r['delay1']['profit_factor'], r['spread035']['max_consec_losses'], r['params'])


if __name__ == '__main__':
    main()
