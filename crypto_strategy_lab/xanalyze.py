import json, glob, numpy as np, pandas as pd
from engine import S
from wfo import seq_metrics
from xtransfer import PICKS

key = ['strat', 'tf', 'train_m', 'step', 'smode']


def size_for_dd(tr, target=19.9):
    """maior fração do capital por trade (≤100%) com DD < target"""
    r = np.array([x[1] for x in tr]); mae = np.array([x[2] for x in tr])
    if len(r) == 0: return 1.0
    for f in np.arange(1.0, 0.04, -0.05):
        if seq_metrics(r * f, mae * f)['maxdd'] < target: return round(f, 2)
    return 0.05


rows = []
for sym in ['ETH', 'SOL', 'XRP']:
    fs = glob.glob(f'{S}/wfo_x_{sym}_*_s*.csv')
    d = pd.concat([pd.read_csv(f).assign(run=f.split('_')[-1][:-4]) for f in fs])
    d['ok'] = (d.wfo_trades > 100) & (d.wfo_winrate >= 57) & (d.wfo_pf >= 1.05) & (d.wfo_maxdd < 20)
    d['fok'] = (d.fwd_trades >= 15) & (d.fwd_winrate >= 57) & (d.fwd_pf >= 1.05) & (d.fwd_maxdd < 20)
    for k in PICKS:
        q = d.merge(pd.DataFrame([dict(zip(key, k))]), on=key)
        if q.empty: continue
        q = q.assign(dist=(q.wfo_pf - q.wfo_pf.median()).abs()).sort_values(['dist', 'wfo_pf'])
        r = q.iloc[0]; tr = json.loads(r.trades)
        rows.append(dict(sym=sym, strat=k[0], tf=k[1], seeds=len(q), seeds_ok=int(q.ok.sum()), seeds_both=int((q.ok & q.fok).sum()),
                         pf_med=q.wfo_pf.median(), pf_min=q.wfo_pf.min(),
                         all_trades=r.wfo_trades, all_winrate=r.wfo_winrate, all_pf=r.wfo_pf, all_maxdd=r.wfo_maxdd, all_ret=r.wfo_ret,
                         fwd_trades=r.fwd_trades, fwd_winrate=r.fwd_winrate, fwd_pf=r.fwd_pf, fwd_maxdd=r.fwd_maxdd,
                         pass_all=bool(r.ok), pass_fwd=bool(r.fok), size_dd20=size_for_dd(tr), yearly=r.yearly,
                         current=next((p for _, p in reversed(json.loads(r.log)) if p), None)))
out = pd.DataFrame(rows)
out.to_csv(f'{S}/xwfo_summary.csv', index=False)
pd.set_option('display.width', 250)
print(out.drop(columns=['yearly', 'current']).round(2).to_string())
