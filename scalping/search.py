"""
Loop de geração/otimização de estratégias até um prazo (deadline).
  * fase aleatória: amostra família + timeframe + parâmetros + gestão de risco
  * fase de mutação: perturba os melhores setups (escolhidos SÓ pelo período de backtest)
O período forward é calculado mas NUNCA usado para escolher setups.
Uso: python -m scalping.search --deadline "2026-11-02 15:05" --out results/search.jsonl
"""
import argparse
import json
import os
import random
import time
from multiprocessing import Pool

import pandas as pd

from .strategies import FAMILIES, COMMON
from .backtest import run, score



def canon(p):
    """Remove parâmetros inativos para evitar avaliar setups duplicados."""
    q = dict(p)
    if q['sl_mode'] == 'usd':
        q.pop('sl_atr', None); q.pop('tp_atr', None)
    else:
        q.pop('sl_usd', None); q.pop('tp_usd', None)
    if q['trend'] == 'none':
        q.pop('trend_len', None)
    if q['guard_mode'] != 1:
        q.pop('guard_pause_h', None)
    if q.get('htf', None) == 0:
        q.pop('htf_len', None)
    return q


def fill(p, rng):
    q = dict(p)
    for k, vals in {**FAMILIES[p['family']][1], **COMMON}.items():
        if k not in q:
            q[k] = rng.choice(vals)
    return canon(q)


ALLOWED = list(FAMILIES)


def sample(rng):
    fam = rng.choice(ALLOWED)
    p = {'family': fam}
    for k, vals in FAMILIES[fam][1].items():
        p[k] = rng.choice(vals)
    for k, vals in COMMON.items():
        p[k] = rng.choice(vals)
    return canon(p)


def mutate(p, rng):
    q = fill(p, rng)
    space = {**FAMILIES[p['family']][1], **COMMON}
    keys = list(space)
    for _ in range(rng.randint(1, 3)):
        k = rng.choice(keys)
        vals = space[k]
        if k in q and q[k] in vals and rng.random() < 0.7:
            i = vals.index(q[k]) + rng.choice([-1, 1])
            q[k] = vals[max(0, min(len(vals) - 1, i))]
        else:
            q[k] = rng.choice(vals)
    return canon(q)


def evaluate(p):
    try:
        r = run(p)
    except Exception as e:  # noqa
        return {'params': p, 'error': repr(e)}
    sc = score(r)
    return {'params': p, 'score_bt': sc, **{k: v for k, v in r.items()}}


KEYS = ['trades', 'win_rate', 'profit_factor', 'net', 'max_dd_pct', 'max_consec_losses', 'ret_pct', 'expectancy']


def compact(r):
    out = {'params': r['params'], 'score_bt': round(r['score_bt'], 3)}
    for seg in ('backtest', 'forward', 'total', 'oos_2022_24'):
        out[seg] = {k: (round(r[seg][k], 4) if isinstance(r[seg][k], float) else r[seg][k]) for k in KEYS}
    out['chunks'] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items()} for c in r['chunks']]
    return out


def key(p):
    return json.dumps(p, sort_keys=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deadline', required=True)
    ap.add_argument('--out', default='results/search.jsonl')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--warm', nargs='*', default=[], help='ficheiros jsonl de rondas anteriores')
    ap.add_argument('--families', nargs='*', default=None, help='restringir a estas famílias')
    ap.add_argument('--seed-params', default=None, help='json com setups iniciais')
    a = ap.parse_args()
    global ALLOWED
    if a.families:
        ALLOWED = a.families
    deadline = pd.Timestamp(a.deadline, tz='UTC').timestamp()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    rng = random.Random(a.seed)
    seen = set()
    top = []  # (score, params)
    top_all = []
    fam_top = {}
    n = 0
    for wp in a.warm:
        for line in open(wp):
            r = json.loads(line)
            if r['params']['family'] not in ALLOWED:
                continue
            seen.add(key(r['params']))
            top_all.append((r['score_bt'], r['params']))
    if a.seed_params:
        for pp in json.load(open(a.seed_params)):
            r = evaluate(pp)
            top_all.append((r['score_bt'], r['params']))
    if top_all:
        for sc_, pp in top_all:
            fam_top.setdefault(pp['family'], []).append((sc_, pp))
        for fm in fam_top:
            fam_top[fm].sort(key=lambda x: -x[0])
            fam_top[fm] = fam_top[fm][:30]
        top_all = [x for v in fam_top.values() for x in v]
        top = sorted(top_all, key=lambda x: -x[0])[:300]
        n = 4000  # já passou a fase de exploração pura
    it = 0
    with Pool(a.workers) as pool, open(a.out, 'a') as f:
        while time.time() < deadline:
            it += 1
            batch = []
            explore = 1.0 if n < 4000 else 0.35
            while len(batch) < 400:
                if top and rng.random() > explore:
                    fams = [fm for fm in fam_top if fam_top[fm]]
                    fm = rng.choice(fams)
                    pool_ = fam_top[fm][:15] if rng.random() < 0.6 else top[:60]
                    base = rng.choice(pool_)[1]
                    p = mutate(base, rng)
                else:
                    p = sample(rng)
                k = key(p)
                if k in seen:
                    continue
                seen.add(k)
                batch.append(p)
            for r in pool.imap_unordered(evaluate, batch, chunksize=8):
                n += 1
                if 'error' in r:
                    continue
                top.append((r['score_bt'], r['params']))
                top_all.append((r['score_bt'], r['params']))
                bt = r['backtest']
                if r['score_bt'] > -40 or rng.random() < 0.005:
                    f.write(json.dumps(compact(r)) + '\n')
            f.flush()
            top.sort(key=lambda x: -x[0])
            top = top[:300]
            fam_top = {}
            for sc_, pp in top_all:
                fam_top.setdefault(pp['family'], []).append((sc_, pp))
            for fm in fam_top:
                fam_top[fm].sort(key=lambda x: -x[0])
                fam_top[fm] = fam_top[fm][:30]
            top_all = [x for v in fam_top.values() for x in v]
            print(f"[{time.strftime('%H:%M:%S')}] iter {it} avaliados {n} melhor score backtest {top[0][0]:.1f} "
                  f"{top[0][1]['family']} tf={top[0][1]['tf']}", flush=True)


if __name__ == '__main__':
    main()
