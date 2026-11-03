"""
Ronda 4: loop de melhoria da A2 com score robusto a atraso de execução e spread.
Otimiza em 15/01/2022..03/11/2026; o período 2018-2021 NÃO é calculado aqui (juiz final).
"""
import argparse, json, os, random, time
from multiprocessing import Pool
import numpy as np
import pandas as pd
from .backtest import run, _ts
from .engine import metrics
from .strategies import FAMILIES, COMMON
from .search import canon

START, END = _ts('2022-01-15'), _ts('2026-11-04')
YEARS = [(y, _ts(f'{y}-01-01'), _ts(f'{y + 1}-01-01')) for y in range(2022, 2027)]
BAL = 116.0
SPACE = {**FAMILIES['RSI_EXTREME'][1], **COMMON,
         'trend': ['with'], 'side': ['both'], 'tf': [5, 10, 15, 20, 30],
         'lim_atr': [0, 0, 0, 0.05, 0.1, 0.2], 'lim_win': [5, 15, 30],
         'tp_floor_pct': [0, 0, 0.04, 0.06, 0.08, 0.1, 0.15]}


def canon4(p):
    q = canon(p)
    if not q.get('lim_atr'):
        q.pop('lim_win', None)
    return q


def sample(rng):
    p = {'family': 'RSI_EXTREME'}
    for k, v in SPACE.items():
        p[k] = rng.choice(v)
    return canon4(p)


def mutate(p, rng):
    q = dict(p)
    for k, v in SPACE.items():
        q.setdefault(k, rng.choice(v))
    keys = list(SPACE)
    for _ in range(rng.randint(1, 3)):
        k = rng.choice(keys)
        vals = SPACE[k]
        if q.get(k) in vals and rng.random() < 0.7:
            i = vals.index(q[k]) + rng.choice([-1, 1])
            q[k] = vals[max(0, min(len(vals) - 1, i))]
        else:
            q[k] = rng.choice(vals)
    return canon4(q)


def window(p, costs):
    te, pnl, real, _ = run(p, costs=costs, raw=True)
    sel = real & (te >= START) & (te < END)
    return te[sel], pnl[sel]


def evaluate(p):
    try:
        te, pnl = window(p, {'spread_pct': 0.025})
        m0 = metrics(pnl, BAL)
        rets = [pnl[(te >= a) & (te < b)].sum() / BAL * 100 for _, a, b in YEARS]
        base = 0.5 * np.mean(rets) + min(rets)
        pen = 0.0
        if m0['trades'] < 100: pen += (100 - m0['trades'])
        if m0['win_rate'] < 0.57: pen += (0.57 - m0['win_rate']) * 500
        pf = min(m0['profit_factor'], 5)
        if pf < 1.05: pen += (1.05 - pf) * 200
        if m0['max_dd_pct'] > 20: pen += (m0['max_dd_pct'] - 20) * 5
        if m0['max_consec_losses'] > 2: pen += (m0['max_consec_losses'] - 2) * 15
        m1 = metrics(window({**p, 'entry_delay': 1}, {'spread_pct': 0.025})[1], BAL)
        m2 = metrics(window(p, {'spread_pct': 0.035})[1], BAL)
        for m in (m1, m2):
            pen += max(0.0, 1.3 - min(m['profit_factor'], 5)) * 60
            if m['max_consec_losses'] > 2: pen += (m['max_consec_losses'] - 2) * 5
        sc = base - pen
        short = lambda m: {k: (round(m[k], 4) if isinstance(m[k], float) else m[k]) for k in
                           ('trades', 'win_rate', 'profit_factor', 'ret_pct', 'max_dd_pct', 'max_consec_losses')}
        return {'params': p, 'score': round(sc, 3), 'full': short(m0), 'delay1': short(m1), 'spread035': short(m2),
                'anos': [round(x, 2) for x in rets]}
    except Exception as e:
        return {'params': p, 'error': repr(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deadline', required=True)
    ap.add_argument('--out', default='results/search_r4.jsonl')
    ap.add_argument('--seed', type=int, default=4)
    ap.add_argument('--seeds-json', default='results/ronda3_candidatos.json')
    a = ap.parse_args()
    deadline = pd.Timestamp(a.deadline, tz='UTC').timestamp()
    rng = random.Random(a.seed)
    seeds = [canon4(v) for k, v in json.load(open(a.seeds_json)).items() if v.get('trend') == 'with']
    seen, top, n = set(), [], 0
    with Pool(4) as pool, open(a.out, 'a') as f:
        for r in pool.imap_unordered(evaluate, seeds):
            if 'error' not in r:
                top.append((r['score'], r['params'])); f.write(json.dumps(r) + '\n')
        while time.time() < deadline:
            batch = []
            while len(batch) < 200:
                if top and rng.random() < 0.7:
                    top.sort(key=lambda x: -x[0])
                    p = mutate(rng.choice(top[:40])[1], rng)
                else:
                    p = sample(rng)
                k = json.dumps(p, sort_keys=True)
                if k in seen: continue
                seen.add(k); batch.append(p)
            for r in pool.imap_unordered(evaluate, batch, chunksize=4):
                n += 1
                if 'error' in r: continue
                top.append((r['score'], r['params']))
                if r['score'] > -60: f.write(json.dumps(r) + '\n')
            f.flush()
            top.sort(key=lambda x: -x[0]); top = top[:400]
            print(f"[{time.strftime('%H:%M:%S')}] avaliados {n} melhor score {top[0][0]:.1f}", flush=True)


if __name__ == '__main__':
    main()
