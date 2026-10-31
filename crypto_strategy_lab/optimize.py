import sys, json, random, time, itertools
import numpy as np, pandas as pd
from multiprocessing import Pool
from engine import load, run, Ind, IS_START, IS_END, OOS_START, OOS_END, S
from strategies import STRATS, EXIT_SPACE

CRIT = dict(wr=57.0, pf=1.05, dd=20.0, n=100)


def passes(m, nmin=CRIT['n']):
    return m['trades'] > nmin and m['winrate'] >= CRIT['wr'] and m['pf'] >= CRIT['pf'] and m['maxdd'] < CRIT['dd']


def score(m):
    if m['trades'] < 30: return -9
    pf = min(m['pf'], 3.0)
    # pontuação suave: penaliza falhas nos critérios (usada também para guiar o loop)
    s = (pf - 1) * np.log(m['trades'])
    s -= max(0, CRIT['wr'] - m['winrate']) * 0.05
    s -= max(0, m['maxdd'] - CRIT['dd']) * 0.05
    s -= max(0, CRIT['n'] + 1 - m['trades']) * 0.01
    return s


def sample(space, rng):
    return {k: rng.choice(v) for k, v in space.items()}


def job(args):
    name, tf, n, seed, fixed = args
    fn, sp = STRATS[name]
    space = {**sp, **EXIT_SPACE}
    if fixed: space.update({k: [v] if not isinstance(v, list) else v for k, v in fixed.items()})
    df = load(tf); I = Ind(df); rng = random.Random(seed)
    seen = set(); out = []
    for _ in range(n * 3):
        if len(out) >= n: break
        p = sample(space, rng)
        key = json.dumps(p, sort_keys=True, default=str)
        if key in seen: continue
        seen.add(key)
        try:
            sig = fn(I, p)
            mi, *_ = run(df, sig, IS_START, IS_END, tf)
        except Exception as ex:
            print('ERR', name, tf, p, ex, flush=True); continue
        rec = dict(strat=name, tf=tf, params=key, **{'is_' + k: v for k, v in mi.items()})
        rec['is_pass'] = passes(mi); rec['is_score'] = score(mi)
        if rec['is_pass'] or rec['is_score'] > 0.5:
            h1, *_ = run(df, sig, IS_START, '2020-12-31 23:59', tf)
            h2, *_ = run(df, sig, '2021-01-01', IS_END, tf)
            rec['h1_pf'] = h1['pf']; rec['h2_pf'] = h2['pf']; rec['h1_wr'] = h1['winrate']; rec['h2_wr'] = h2['winrate']
            rec['h1_n'] = h1['trades']; rec['h2_n'] = h2['trades']
            rec['rob'] = min(h1['pf'], h2['pf'])
        if rec['is_score'] > -1 or rec['is_pass']:
            mo, *_ = run(df, sig, OOS_START, OOS_END, tf)
            rec.update({'oos_' + k: v for k, v in mo.items()})
        out.append(rec)
    return out


if __name__ == '__main__':
    tag = sys.argv[1]; n = int(sys.argv[2]); tfs = sys.argv[3].split(',')
    names = sys.argv[4].split(',') if len(sys.argv) > 4 and sys.argv[4] != 'all' else list(STRATS)
    fixed = json.loads(sys.argv[5]) if len(sys.argv) > 5 else None
    jobs = [(s, tf, n, hash((s, tf, tag)) % 10**6, fixed) for s in names for tf in tfs]
    t = time.time(); res = []
    with Pool(min(len(jobs), 8)) as pool:
        for r in pool.imap_unordered(job, jobs):
            res += r
            if r: print(f"{r[0]['strat']:9s} {r[0]['tf']:4s} done n={len(r)} pass_is={sum(x['is_pass'] for x in r)} t={time.time()-t:.0f}s", flush=True)
    pd.DataFrame(res).to_csv(f'{S}/res_{tag}.csv', index=False)
    print('total', len(res), 'time', time.time() - t)
