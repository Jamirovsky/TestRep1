import json, numpy as np, pandas as pd
import final as F
from engine import S, load, run, Ind
from strategies import STRATS
from wfo import seq_metrics
pick = [('swing','15m',24,3,'rob'),('keltner','15m',24,6,'pf'),('connors','15m',24,3,'pf'),('willr','15m',24,6,'rob'),
        ('cluc','15m',24,3,'pf'),('bbrsi','15m',24,6,'pf'),('binh','15m',24,3,'pf'),('downbars','15m',36,3,'rob'),('stoch','1h',36,6,'pf'),('cluc','15m',24,3,'rob')]
res = []
for k in pick:
    row = F.g.set_index(F.key).loc[k].copy(); row = pd.concat([pd.Series(dict(zip(F.key, k))), row])
    det = F.detail(row); o, f = det['oos'], det['fwd']
    det['pass_oos'] = bool(o['trades'] > 100 and o['winrate'] >= 57 and o['pf'] >= 1.05 and o['maxdd'] < 20)
    det['pass_fwd'] = bool(f['trades'] >= 15 and f['winrate'] >= 57 and f['pf'] >= 1.05 and f['maxdd'] < 20)
    res.append(det)
    print(k, det['ok_runs'], det['runs'], {a: round(b,2) for a,b in o.items()}, {a: round(b,2) for a,b in f.items()}, round(det['stress']['pf'],2), round(det['mc_dd95'],1), det['pass_oos'], det['pass_fwd'])
# estratégias de parâmetros fixos (holdout estrito)
fw = pd.read_csv(f'{S}/forward.csv')
for rid in ['stpull_4h_24', 'ibs_4h_26']:
    r = fw[fw.id == rid].iloc[0]; df = load(r.tf); I = Ind(df); p = json.loads(r.params); sig = STRATS[r.strat][0](I, p)
    m, ret, ti, to, mae = run(df, sig, '2018-01-01', '2026-12-31', r.tf, full_out=True)
    t = df.index[ti]
    def seg(a, b):
        k = (t >= a) & (t < b); return seq_metrics(ret[k], mae[k])
    o = seg('2021-01-01', '2026-12-31'); f = seg('2025-07-01', '2026-12-31')
    eq = pd.Series(np.cumprod(1 + ret), index=t)
    k21 = t >= '2021-01-01'; eq21 = pd.Series(np.cumprod(1 + ret[k21]), index=t[k21])
    curve = eq21.resample('MS').last().reindex(pd.date_range('2021-01-01', '2026-10-01', freq='MS')).ffill().fillna(1.0)
    det = dict(kind='FIXO', strat=r.strat, tf=r.tf, meta='parâmetros fixos · otimizado 2018-23 · validado 2024-jun/25', params=p,
               is_=dict(trades=r.is_trades, winrate=r.is_winrate, pf=r.is_pf, maxdd=r.is_maxdd), val=dict(trades=r.val_trades, winrate=r.val_winrate, pf=r.val_pf, maxdd=r.val_maxdd),
               fwd=dict(trades=r.fwd_trades, winrate=r.fwd_winrate, pf=r.fwd_pf, maxdd=r.fwd_maxdd, ret=r.fwd_ret),
               full=dict(trades=r.full_trades, winrate=r.full_winrate, pf=r.full_pf, maxdd=r.full_maxdd, cagr=r.full_cagr),
               oos=o, stress_fwd_pf=r.fwd_stress_pf, mc_dd95=r.mc_dd95, yearly=json.loads(r.yearly), curve=[round(x, 4) for x in curve.values], stab=r.stab)
    det['pass_fwd'] = bool(r.fwd_pass); det['pass_full'] = bool(r.full_trades > 100 and r.full_winrate >= 57 and r.full_pf >= 1.05 and r.full_maxdd < 20)
    res.append(det); print(rid, det['full'], det['pass_full'], o)
json.dump(res, open(f'{S}/final_pick.json', 'w'), default=float, indent=1)
