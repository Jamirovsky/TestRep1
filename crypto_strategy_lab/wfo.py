"""Walk-Forward Optimization: re-otimiza a cada 6 meses com a janela de treino anterior,
negoceia os 6 meses seguintes (nunca vistos). OOS concatenado: 2021-01 .. 2026-10."""
import sys, json, random, numpy as np, pandas as pd
from multiprocessing import Pool
from engine import load, run, Ind, S
from strategies import STRATS, EXIT_SPACE

STEP = 6
END = pd.Timestamp('2026-11-01')
FWD0 = pd.Timestamp('2025-07-01')
NP = int(sys.argv[2]) if len(sys.argv) > 2 else 400


def seq_metrics(r, mae):
    n = len(r)
    if n == 0: return dict(trades=0, winrate=0, pf=0, maxdd=0, ret=0)
    eq = 1.0; peak = 1.0; dd = 0.0
    for ri, mi in zip(r, mae):
        dd = max(dd, 1 - eq * (1 + mi) / peak)
        eq *= 1 + ri; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    w = r[r > 0].sum(); l = -r[r <= 0].sum()
    return dict(trades=n, winrate=(r > 0).mean() * 100, pf=w / l if l > 0 else 99.0, maxdd=dd * 100, ret=(eq - 1) * 100)


def job(args):
    name, tf = args
    fn, sp = STRATS[name]; space = {**sp, **EXIT_SPACE}
    df = load(tf); I = Ind(df); rng = random.Random(hash((name, tf)) % 10**6 + int(__import__('os').environ.get('SEED', '0')))
    cands = []; seen = set()
    while len(cands) < NP and len(seen) < NP * 3:
        p = {k: rng.choice(v) for k, v in space.items()}; key = json.dumps(p, sort_keys=True, default=str)
        if key in seen: continue
        seen.add(key)
        sig = fn(I, p)
        m, r, ti, to, mae = run(df, sig, '2018-01-01', '2026-12-31', tf, full_out=True)
        cands.append((key, r, df.index[ti].values, mae))
    return [wf(name, tf, cands, tm, 1.1, st, sm) for tm in (24, 36) for st in (3, 6) for sm in ('pf', 'rob')]


def wf(name, tf, cands, train_m, minpf, step=6, smode='pf'):
    TEST_STARTS = pd.date_range('2021-01-01', '2026-10-01', freq=f'{step}MS')
    oos_r = []; oos_mae = []; oos_t = []; log = []
    for ts in TEST_STARTS:
        tr0 = ts - pd.DateOffset(months=train_m); te1 = min(ts + pd.DateOffset(months=step), END)
        nmin = int(100 * train_m / 60)          # ~100 trades por 5 anos
        best = None; bs = -1e9
        for key, r, t, mae in cands:
            msk = (t >= np.datetime64(tr0)) & (t < np.datetime64(ts))
            if msk.sum() < nmin: continue
            m = seq_metrics(r[msk], mae[msk])
            if m['winrate'] < 57 or m['pf'] < minpf or m['maxdd'] >= 20: continue
            # recência: último ano do treino não pode ser negativo
            rec = msk & (t >= np.datetime64(ts - pd.DateOffset(months=12)))
            if rec.sum() >= 5 and seq_metrics(r[rec], mae[rec])['pf'] < 1: continue
            s = (min(m['pf'], 3) - 1) * np.log(m['trades'])
            if smode == 'rob':      # robustez: pior PF entre as duas metades do treino
                mid = np.datetime64(tr0 + (ts - tr0) / 2); m1 = msk & (t < mid); m2 = msk & (t >= mid)
                if m1.sum() < 5 or m2.sum() < 5: continue
                s = (min(seq_metrics(r[m1], mae[m1])['pf'], seq_metrics(r[m2], mae[m2])['pf'], 3) - 1) * np.log(m['trades'])
            if s > bs: bs, best = s, key
        if best is None:
            log.append((str(ts.date()), None)); continue          # sem params qualificados -> fica fora do mercado
        key, r, t, mae = next(c for c in cands if c[0] == best)
        msk = (t >= np.datetime64(ts)) & (t < np.datetime64(te1))
        oos_r += list(r[msk]); oos_mae += list(mae[msk]); oos_t += list(t[msk])
        log.append((str(ts.date()), best))
    r = np.array(oos_r); mae = np.array(oos_mae); t = np.array(oos_t, dtype='datetime64[ns]')
    allm = seq_metrics(r, mae)
    f = t >= np.datetime64(FWD0); fm = seq_metrics(r[f], mae[f]); pm = seq_metrics(r[~f], mae[~f])
    yrs = {}
    for y in range(2021, 2027):
        k = (t >= np.datetime64(f'{y}-01-01')) & (t < np.datetime64(f'{y + 1}-01-01'))
        mm = seq_metrics(r[k], mae[k]); yrs[y] = [mm['trades'], round(mm['winrate'], 1), round(min(mm['pf'], 99), 2)]
    return dict(strat=name, tf=tf, train_m=train_m, minpf=minpf, step=step, smode=smode,
                **{'wfo_' + k: v for k, v in allm.items()}, **{'pre_' + k: v for k, v in pm.items()},
                **{'fwd_' + k: v for k, v in fm.items()}, windows_active=sum(1 for _, b in log if b),
                yearly=json.dumps(yrs), log=json.dumps(log),
                trades=json.dumps([[str(a)[:16], round(float(b), 5), round(float(c), 5)] for a, b, c in zip(t, r, mae)]))


if __name__ == '__main__':
    tag = sys.argv[1]
    names = sys.argv[3].split(',') if len(sys.argv) > 3 else list(STRATS)
    tfs = sys.argv[4].split(',') if len(sys.argv) > 4 else ['15m', '1h', '4h']
    jobs = [(n, tf) for n in names for tf in tfs]
    with Pool(4) as pool:
        res = []
        for xs in pool.imap_unordered(job, jobs):
          for x in xs:
            res.append(x)
            print(f"{x['strat']:9s} {x['tf']:4s} tm={x['train_m']} st={x['step']} {x['smode']} | WFO n={x['wfo_trades']} wr={x['wfo_winrate']:.1f} pf={x['wfo_pf']:.2f} dd={x['wfo_maxdd']:.1f} | FWD n={x['fwd_trades']} wr={x['fwd_winrate']:.1f} pf={x['fwd_pf']:.2f} dd={x['fwd_maxdd']:.1f}", flush=True)
    pd.DataFrame(res).to_csv(f'{S}/wfo_{tag}.csv', index=False)
