"""Forward test (holdout jul/2025-out/2026) dos candidatos selecionados SÓ com IS+VAL."""
import json, numpy as np, pandas as pd
from engine import load, run, Ind, IS_START, IS_END, S
from strategies import STRATS
from final_eval import VAL, FWD, ok

v = pd.read_csv(f'{S}/val_stage.csv')
v['sel'] = np.minimum(v.is_pf, v.val_pf.clip(upper=3)) * np.log(v.is_trades + v.val_trades) * (0.5 + v.stab)
v = v[v.stab >= 0.4].sort_values('sel', ascending=False)
# diversidade: máx 3 por (família, tf) e 5 por família
v = v.groupby(['strat', 'tf']).head(3).groupby('strat').head(5).head(30)
rows = []; curves = {}
rng = np.random.default_rng(0)
for i, r in enumerate(v.itertuples()):
    df = load(r.tf); I = Ind(df); p = json.loads(r.params); sig = STRATS[r.strat][0](I, p)
    f, fr, fti, fto = run(df, sig, *FWD, r.tf)
    full, ret, ti, to = run(df, sig, IS_START, FWD[1], r.tf)
    fst = run(df, sig, *FWD, r.tf, cost=0.0010)[0]
    # anos
    yrs = pd.Series(ret, index=df.index[to]).groupby(lambda t: t.year).agg(['count', lambda x: (x > 0).mean() * 100, lambda x: x[x > 0].sum() / max(1e-9, -x[x <= 0].sum())])
    yrs.columns = ['n', 'wr', 'pf']
    # Monte Carlo do drawdown (bootstrap dos trades pré-forward)
    pre = ret[df.index[to] < pd.Timestamp(FWD[0])]
    dds = []
    for _ in range(1000):
        s = rng.choice(pre, len(pre)); eq = np.cumprod(1 + s); pk = np.maximum.accumulate(np.r_[1, eq])[1:]
        dds.append((1 - eq / pk).max() * 100)
    eq = pd.Series(np.cumprod(1 + ret), index=df.index[to])
    rid = f'{r.strat}_{r.tf}_{i}'
    curves[rid] = eq.resample('W').last().ffill()
    exposure = float(np.sum(to - ti)) / max(1, (df.index.searchsorted(pd.Timestamp(FWD[1])) - df.index.searchsorted(pd.Timestamp(IS_START))))
    rows.append(dict(id=rid, strat=r.strat, tf=r.tf, params=r.params, sel=r.sel, stab=r.stab,
                     **{f'is_{k}': getattr(r, f'is_{k}') for k in ('trades', 'winrate', 'pf', 'maxdd', 'cagr')},
                     **{f'val_{k}': getattr(r, f'val_{k}') for k in ('trades', 'winrate', 'pf', 'maxdd', 'cagr')},
                     **{f'fwd_{k}': x for k, x in f.items()}, **{f'full_{k}': x for k, x in full.items()},
                     fwd_stress_pf=fst['pf'], fwd_stress_wr=fst['winrate'], mc_dd95=np.percentile(dds, 95),
                     years_pos=int((yrs.pf > 1).sum()), years_tot=len(yrs), exposure=exposure * 100,
                     yearly=json.dumps({int(y): [int(a.n), round(a.wr, 1), round(min(a.pf, 99), 2)] for y, a in yrs.iterrows()}),
                     fwd_pass=ok(f, 15)))
out = pd.DataFrame(rows)
out.to_csv(f'{S}/forward.csv', index=False)
pd.DataFrame(curves).to_csv(f'{S}/curves.csv')
pd.set_option('display.width', 300)
print(out[['id', 'is_trades', 'is_winrate', 'is_pf', 'is_maxdd', 'val_trades', 'val_winrate', 'val_pf', 'fwd_trades', 'fwd_winrate', 'fwd_pf', 'fwd_maxdd', 'fwd_ret', 'fwd_stress_pf', 'mc_dd95', 'years_pos', 'years_tot', 'stab', 'fwd_pass']].round(2).to_string())
print('FWD pass:', out.fwd_pass.sum(), '/', len(out))
