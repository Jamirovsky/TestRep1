"""Ronda 5: loop de adaptação das estratégias Chart Fanatics / World Cup (2022-26 apenas)."""
import argparse, json, random, time
from multiprocessing import Pool
import numpy as np
import pandas as pd
from . import strategies_yt as Y
from .search_r4 import evaluate
from .strategies import HOURS

EXITS = dict(sl_mode=['struct', 'struct', 'atr'], rr=[0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
             sl_buf_atr=[0.0, 0.1, 0.25, 0.5, 1.0, 2.0], sl_atr=[1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0],
             tp_atr=[0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0], max_hold=[30, 60, 120, 240, 480],
             be_frac=[0.0, 0.0, 0.5, 0.7, 0.8], tf=[1, 3, 5, 10, 15, 30], hours=list(HOURS),
             trend=['none', 'with', 'against'], trend_len=[50, 100, 200], weekend=['yes', 'no'],
             guard_mode=[0, 0, 1, 2], guard_pause_h=[4, 12, 24], atr_min=[0, 0, 0.5, 1.0], side=['both'])


def space(fam):
    sp = {**Y.YT_FAMILIES[fam][1], **EXITS}
    if fam == 'CF_FABIO':
        sp['tp_mode'] = ['rr', 'target']
    return sp


def canon(p):
    q = dict(p)
    if q['sl_mode'] == 'struct':
        for k in ('sl_atr', 'tp_atr'): q.pop(k, None)
        if q.get('tp_mode') == 'target': q.pop('rr', None)
    else:
        for k in ('rr', 'sl_buf_atr', 'tp_mode'): q.pop(k, None)
    if q.get('trend') == 'none': q.pop('trend_len', None)
    if q.get('guard_mode') != 1: q.pop('guard_pause_h', None)
    if q['family'] == 'CF_FABIO':
        if q.get('fab_model') == 'mr': q.pop('slope_len', None)
        else: q.pop('band_len', None); q.pop('band_k', None); q.pop('tp_mode', None)
    return q


def sample(fam, rng):
    return canon({'family': fam, **{k: rng.choice(v) for k, v in space(fam).items()}})


def mutate(p, rng):
    sp = space(p['family'])
    q = dict(p)
    for k, v in sp.items():
        q.setdefault(k, rng.choice(v))
    for _ in range(rng.randint(1, 3)):
        k = rng.choice(list(sp)); vals = sp[k]
        if q.get(k) in vals and rng.random() < 0.7:
            i = vals.index(q[k]) + rng.choice([-1, 1]); q[k] = vals[max(0, min(len(vals) - 1, i))]
        else:
            q[k] = rng.choice(vals)
    return canon(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deadline', required=True)
    ap.add_argument('--out', default='results/search_yt.jsonl')
    a = ap.parse_args()
    deadline = pd.Timestamp(a.deadline, tz='UTC').timestamp()
    rng = random.Random(5)
    fams = list(Y.YT_FAMILIES)
    top = {f: [] for f in fams}
    seen, n = set(), 0
    with Pool(4) as pool, open(a.out, 'a') as fo:
        seeds = [canon(Y.published(f)) for f in fams]
        while time.time() < deadline:
            batch = list(seeds); seeds = []
            while len(batch) < 160:
                f = fams[len(batch) % len(fams)]
                p = mutate(rng.choice(top[f][:20])[1], rng) if top[f] and rng.random() < 0.65 else sample(f, rng)
                k = json.dumps(p, sort_keys=True)
                if k in seen: continue
                seen.add(k); batch.append(p)
            for r in pool.imap_unordered(evaluate, batch, chunksize=2):
                n += 1
                if 'error' in r: continue
                top[r['params']['family']].append((r['score'], r['params']))
                if r['score'] > -150: fo.write(json.dumps(r) + '\n')
            fo.flush()
            for f in fams:
                top[f].sort(key=lambda x: -x[0]); top[f] = top[f][:200]
            best = {f: round(top[f][0][0], 1) for f in fams if top[f]}
            print(f"[{time.strftime('%H:%M:%S')}] avaliados {n} {best}", flush=True)


if __name__ == '__main__':
    main()
