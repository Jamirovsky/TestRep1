"""Ronda 5: seleção robusta por família (só 2022-26) e juiz 2018-2021 (results/REGRA_RONDA5.md)."""
import json
from multiprocessing import Pool
import numpy as np
from . import strategies_yt as Y
from .search_yt import space, canon
from .search_r4 import evaluate
from .judge_r4 import ok, judge


def neighbours(p):
    sp = space(p['family']); out = []
    for k, vals in sp.items():
        if k not in p or p[k] not in vals or len(vals) < 2 or k in ('sl_mode', 'side'):
            continue
        i = vals.index(p[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                q = dict(p); q[k] = vals[j]
                if q.get('trend') != 'none': q.setdefault('trend_len', 100)
                if q.get('guard_mode') == 1: q.setdefault('guard_pause_h', 12)
                out.append(canon(q))
    return out


def main(path='results/search_yt.jsonl', per_fam=25):
    rows = [json.loads(l) for l in open(path)]
    cands = []
    for fam in Y.YT_FAMILIES:
        rs = sorted([r for r in rows if r['params']['family'] == fam and ok(r['full'])], key=lambda r: -r['score'])
        seen = set()
        for r in rs:
            sig = (r['full']['trades'], round(r['full']['ret_pct'], 2))
            if sig in seen: continue
            seen.add(sig); cands.append(r)
            if len(seen) >= per_fam: break
    print('candidatos que cumprem tudo em 2022-26:', {f: sum(c['params']['family'] == f for c in cands) for f in Y.YT_FAMILIES}, flush=True)
    jobs, own = [], []
    for ci, r in enumerate(cands):
        for q in neighbours(r['params']):
            jobs.append(q); own.append(ci)
    with Pool(4) as pool:
        res = pool.map(evaluate, jobs, chunksize=4)
    nb = {}
    for ci, r in zip(own, res):
        nb.setdefault(ci, []).append(r.get('score', -999))
    for ci, r in enumerate(cands):
        r['score_robusto'] = 0.4 * r['score'] + 0.6 * float(np.median(nb.get(ci, [r['score']])))
    A2 = json.load(open('results/ronda4_finalistas.json'))['A2']
    a2j, _, _ = judge(A2)
    out = {}
    for fam in Y.YT_FAMILIES:
        fc = sorted([c for c in cands if c['params']['family'] == fam], key=lambda c: -c['score_robusto'])
        if not fc:
            out[fam] = {'desafiante': None, 'motivo': 'nenhum setup cumpriu os pressupostos em 2022-26'}
            print(fam, '-> nenhum setup cumpre os pressupostos em 2022-26'); continue
        ch = fc[0]
        m, _, _ = judge(ch['params'])
        passa = ok(m)
        bate_a2 = passa and m['profit_factor'] > a2j['profit_factor'] and ch['full']['profit_factor'] > 1.83
        out[fam] = {'desafiante': ch, 'juiz_2018_21': m, 'passa': passa, 'bate_A2': bate_a2}
        print(f"{fam:15s} 2022-26 pf={ch['full']['profit_factor']:.2f} wr={ch['full']['win_rate']:.2f} n={ch['full']['trades']} | JUIZ 2018-21 n={m['trades']} wr={m['win_rate']:.2f} pf={m['profit_factor']:.2f} €={m['net']/1.16:.1f} dd={m['max_dd_pct']:.1f} mcl={m['max_consec_losses']} | passa={passa} bate_A2={bate_a2}")
        print('    ', ch['params'])
    out['A2_juiz'] = a2j
    json.dump(out, open('results/ronda5_resultado.json', 'w'), default=float)


if __name__ == '__main__':
    main()
