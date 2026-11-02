"""
Seleção robusta (usa SÓ o backtest): para os melhores setups de cada família calcula
o score dos vizinhos (cada parâmetro +/- um passo). Score robusto =
0.4 * score próprio + 0.6 * mediana do score dos vizinhos.
Um setup isolado num "pico" (vizinhos maus) é despromovido; um setup num "planalto"
estável é promovido. O forward test continua intocado.
"""
import json
import sys
from multiprocessing import Pool

import numpy as np

from .backtest import run, score
from .robustness import neighbours
from .search import canon


def _score(p):
    try:
        return score(run(p))
    except Exception:
        return -999.0


def main(paths, out='results/robust_rank.json', per_family=60):
    rows = []
    for pth in paths:
        for line in open(pth):
            rows.append(json.loads(line))
    fam = {}
    for r in rows:
        fam.setdefault(r['params']['family'], []).append(r)
    cands = []
    for f, rs in fam.items():
        rs.sort(key=lambda r: -r['score_bt'])
        seen = set()
        for r in rs:
            sig = (r['backtest']['trades'], round(r['backtest']['ret_pct'], 2))
            if sig in seen:
                continue
            seen.add(sig)
            cands.append(r)
            if len(seen) >= per_family:
                break
    print('candidatos', len(cands), flush=True)
    jobs = []
    owners = []
    for ci, r in enumerate(cands):
        for k, v, q in neighbours(r['params']):
            jobs.append(canon(q) if 'sl_mode' in q else q)
            owners.append(ci)
    print('avaliações de vizinhos', len(jobs), flush=True)
    with Pool(4) as pool:
        scores = pool.map(_score, jobs, chunksize=16)
    nb = {}
    for ci, s in zip(owners, scores):
        nb.setdefault(ci, []).append(s)
    out_rows = []
    for ci, r in enumerate(cands):
        ns = nb.get(ci, [r['score_bt']])
        rob = 0.4 * r['score_bt'] + 0.6 * float(np.median(ns))
        out_rows.append({'params': r['params'], 'score_bt': r['score_bt'], 'score_vizinhos_mediana': float(np.median(ns)),
                         'score_vizinhos_p25': float(np.percentile(ns, 25)), 'score_robusto': rob,
                         'backtest': r['backtest'], 'forward': r['forward'], 'total': r['total'], 'chunks': r['chunks']})
    out_rows.sort(key=lambda x: -x['score_robusto'])
    with open(out, 'w') as f:
        json.dump(out_rows, f)
    for x in out_rows[:15]:
        print(round(x['score_robusto'], 1), round(x['score_bt'], 1), round(x['score_vizinhos_mediana'], 1), x['params']['family'], x['params']['tf'])


if __name__ == '__main__':
    main(sys.argv[1:])
