"""Refinamento: hill-climb local no IS + estabilidade de vizinhança + verificação OOS + stress tests."""
import sys, json, numpy as np, pandas as pd
from multiprocessing import Pool
from engine import load, run, Ind, IS_START, IS_END, OOS_START, OOS_END, S
from strategies import STRATS, EXIT_SPACE
from optimize import passes, score

FULL_START = IS_START


def space_of(name):
    return {**STRATS[name][1], **EXIT_SPACE}


def neighbors(p, space):
    out = []
    for k, vals in space.items():
        vals = sorted(set(vals), key=lambda v: float(v) if isinstance(v, (int, float)) else hash(str(v)))
        if k not in p or p[k] not in vals: continue
        i = vals.index(p[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                q = dict(p); q[k] = vals[j]; out.append(q)
    return out


def evaluate(df, I, name, p, tf, periods=('is', 'oos')):
    fn = STRATS[name][0]; sig = fn(I, p); r = {}
    if 'is' in periods:
        r['is'] = run(df, sig, IS_START, IS_END, tf)[0]
        r['h1'] = run(df, sig, IS_START, '2020-12-31 23:59', tf)[0]
        r['h2'] = run(df, sig, '2021-01-01', IS_END, tf)[0]
    if 'oos' in periods:
        r['oos'] = run(df, sig, OOS_START, OOS_END, tf)[0]
    return r, sig


def is_obj(r):
    if not passes(r['is']) or min(r['h1']['pf'], r['h2']['pf']) < 1: return -9 + score(r['is'])
    return score(r['is'])


def oos_ok(m, nmin=30):
    return m['trades'] >= nmin and m['winrate'] >= 57 and m['pf'] >= 1.05 and m['maxdd'] < 20


def refine(args):
    name, tf, p0 = args
    df = load(tf); I = Ind(df); sp = space_of(name)
    cur = p0; r0, _ = evaluate(df, I, name, cur, tf, ('is',)); best = is_obj(r0)
    for it in range(4):                       # hill-climb só com dados IS
        improved = False
        for q in neighbors(cur, sp):
            rq, _ = evaluate(df, I, name, q, tf, ('is',))
            o = is_obj(rq)
            if o > best + 1e-9: best, cand, improved = o, q, True
        if not improved: break
        cur = cand
    # estabilidade: vizinhos que continuam a passar IS e OOS
    nb = neighbors(cur, sp); n_is = n_oos = 0
    for q in nb:
        rq, _ = evaluate(df, I, name, q, tf)
        n_is += passes(rq['is']); n_oos += oos_ok(rq['oos'])
    r, sig = evaluate(df, I, name, cur, tf)
    full = run(df, sig, FULL_START, OOS_END, tf)[0]
    stress = run(df, sig, OOS_START, OOS_END, tf, cost=0.0010)[0]       # custo 0.10%/lado
    stress_is = run(df, sig, IS_START, IS_END, tf, cost=0.0010)[0]
    rec = dict(strat=name, tf=tf, params=json.dumps(cur, sort_keys=True, default=str),
               orig=json.dumps(p0, sort_keys=True, default=str),
               stab_is=n_is / max(1, len(nb)), stab_oos=n_oos / max(1, len(nb)),
               st_oos_pf=stress['pf'], st_oos_wr=stress['winrate'], st_is_pf=stress_is['pf'])
    for k in ('is', 'oos', 'h1', 'h2'):
        rec.update({f'{k}_{m}': v for m, v in r[k].items()})
    rec.update({f'full_{m}': v for m, v in full.items()})
    return rec


if __name__ == '__main__':
    src = sys.argv[1]; top = int(sys.argv[2]); out = sys.argv[3]
    c = pd.read_csv(f'{S}/{src}')
    c['k'] = np.minimum(c.is_pf, c.oos_pf) * np.log(c.is_trades + c.oos_trades)
    c = c.sort_values('k', ascending=False)
    c = c.groupby(['strat', 'tf']).head(6).head(top)       # diversidade
    jobs = [(r.strat, r.tf, json.loads(r.params)) for r in c.itertuples()]
    with Pool(4) as pool:
        res = pool.map(refine, jobs)
    pd.DataFrame(res).to_csv(f'{S}/{out}', index=False)
    print('done', len(res))
