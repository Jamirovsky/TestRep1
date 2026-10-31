"""Constrói o top10 final (JSON para o report)."""
import json, numpy as np, pandas as pd
from engine import S
from wfo import seq_metrics

d = pd.read_csv(f'{S}/wfo_all.csv')
key = ['strat', 'tf', 'train_m', 'step', 'smode']
g = d.groupby(key).agg(runs=('run', 'count'), ok=('ok', 'sum'), both=('both', 'sum'), pf_med=('wfo_pf', 'median'),
                       pf_min=('wfo_pf', 'min'), fpf_med=('fwd_pf', 'median'), fn_med=('fwd_trades', 'median')).reset_index()
g = g[g.runs >= 3]
g['ok_rate'] = g.ok / g.runs
g['rob_score'] = g.pf_med.clip(upper=2.5) * (0.5 + g.ok_rate) * np.minimum(1, g.pf_min)


def detail(row):
    q = d.merge(pd.DataFrame([row[key]]), on=key)
    # corrida representativa = mediana do PF (não a melhor)
    q = q.assign(dist=(q.wfo_pf - q.wfo_pf.median()).abs()).sort_values(['dist', 'wfo_pf'])
    r = q.iloc[0]
    tr = pd.DataFrame(json.loads(r.trades), columns=['t', 'r', 'mae']); tr['t'] = pd.to_datetime(tr.t)
    f = tr.t >= '2025-07-01'
    pre = seq_metrics(tr.r.values[~f.values], tr.mae.values[~f.values])
    allm = seq_metrics(tr.r.values, tr.mae.values); fm = seq_metrics(tr.r.values[f.values], tr.mae.values[f.values])
    st = seq_metrics(tr.r.values - 0.0006, tr.mae.values - 0.0006)
    eq = (1 + tr.set_index('t').r).cumprod()
    curve = eq.resample('MS').last().reindex(pd.date_range('2021-01-01', '2026-10-01', freq='MS')).ffill().fillna(1.0)
    logs = json.loads(r.log); cur = next((json.loads(p) for _, p in reversed(logs) if p), None)
    yrs = json.loads(r.yearly)
    # Monte Carlo DD
    rng = np.random.default_rng(1); dds = []
    for _ in range(1000):
        ix = rng.integers(0, len(tr), len(tr)); dds.append(seq_metrics(tr.r.values[ix], tr.mae.values[ix])['maxdd'])
    return dict(kind='WFO', strat=r.strat, tf=r.tf, meta=f"treino {int(r.train_m)}m · re-otimização a cada {int(r.step)}m · seleção {'robusta' if r.smode == 'rob' else 'PF'}",
                runs=int(row.runs), ok_runs=int(row.ok), pf_med=row.pf_med, pf_min=row.pf_min,
                oos=allm, pre=pre, fwd=fm, stress=st, mc_dd95=float(np.percentile(dds, 95)),
                yearly=yrs, curve=[round(x, 4) for x in curve.values], current=cur,
                windows_active=int(r.windows_active), windows=len(logs))


sel = g.sort_values('rob_score', ascending=False)
out = []; seen = {}
for _, row in sel.iterrows():
    k = (row.strat, row.tf)
    if seen.get(k, 0) >= 2: continue
    det = detail(row)
    o, f = det['oos'], det['fwd']
    det['pass_oos'] = bool(o['trades'] > 100 and o['winrate'] >= 57 and o['pf'] >= 1.05 and o['maxdd'] < 20)
    det['pass_fwd'] = bool(f['trades'] >= 15 and f['winrate'] >= 57 and f['pf'] >= 1.05 and f['maxdd'] < 20)
    det['rob_score'] = row.rob_score
    out.append(det); seen[k] = seen.get(k, 0) + 1
    if len(out) >= 16: break
for x in out:
    print(f"{x['strat']:8s} {x['tf']:4s} {x['meta'][:40]:40s} runs {x['ok_runs']}/{x['runs']} pfmed {x['pf_med']:.2f} | OOS n={x['oos']['trades']} wr={x['oos']['winrate']:.1f} pf={x['oos']['pf']:.2f} dd={x['oos']['maxdd']:.1f} | FWD n={x['fwd']['trades']} wr={x['fwd']['winrate']:.1f} pf={x['fwd']['pf']:.2f} dd={x['fwd']['maxdd']:.1f} | stress pf={x['stress']['pf']:.2f} mc95={x['mc_dd95']:.1f} {x['pass_oos']} {x['pass_fwd']}")
json.dump(out, open(f'{S}/final_wfo.json', 'w'), default=float, indent=1)
